---
name: github-pr-integration
description: Use when fetching a PR or its diff with PyGithub, posting or editing a PR comment, parsing unified diff hunks to validate line numbers, choosing GitHub token scopes, or handling GitHub API rate limits.
---

# github-pr-integration

The agent reads PR metadata and diffs from GitHub and posts a single consolidated review comment back. This skill captures the patterns for getting those interactions right — and idempotent.

## When to use this skill

- Implementing `ingest_pr` or `fetch_diff` in `agent/nodes/`.
- Implementing `post_comment` (idempotent create-or-update).
- Parsing the unified diff to validate which lines are in which hunk (used by `guardrail_check`).
- Choosing or auditing the GitHub Actions workflow's `permissions:` block.
- Investigating rate-limit failures or pagination issues.

## Conventions

**Auth.** Use the `GITHUB_TOKEN` env var. In GitHub Actions this is auto-provided; locally, use a fine-grained PAT scoped to a single repo.

**Token scopes** (in the workflow's `permissions:` block):

```yaml
permissions:
  pull-requests: write   # post/edit the review comment
  contents: read         # read PR metadata and the diff
```

Never grant `write` to `contents` from this workflow — the agent does not commit code.

**PR fetch.**

```python
from github import Github
gh = Github(os.environ["GITHUB_TOKEN"])
repo = gh.get_repo(state["repo"])            # "owner/name"
pr = repo.get_pull(state["pr_number"])
state["head_sha"] = pr.head.sha
state["changed_files"] = [f.filename for f in pr.get_files()]
```

`pr.get_files()` is paginated — iterate over the `PaginatedList`, don't index into it. PyGithub handles pagination transparently during iteration.

**Diff fetch.** PyGithub doesn't expose the raw unified diff cleanly. Use the REST API with the `diff` media type:

```python
import requests
url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
r = requests.get(url, headers={
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github.v3.diff",
})
r.raise_for_status()
state["diff"] = r.text  # text/plain, not JSON
```

**Idempotent comment posting.** Every comment the agent posts carries an HTML marker as its first line:

```html
<!-- ai4sdlc-agent v{version} -->
```

`post_comment` must:

1. List existing issue comments on the PR (`pr.get_issue_comments()`).
2. Find the one whose body starts with the marker (any version).
3. If found, call `comment.edit(new_body)`; if not, `pr.create_issue_comment(body)`.
4. Store `posted_comment_id` in state for traceability.

This is one **issue** comment on the PR, not a *review* comment (no inline file/line). The body is rendered markdown.

**Diff parsing for guardrail.** When validating "is this line in the diff?", parse hunks of the form `@@ -a,b +c,d @@` and check whether the candidate line falls inside `[c, c+d)` for the right file. A small parser in `agent/diff.py` is fine; don't pull in a full diff library for this.

**Rate limits.** Wrap GitHub calls with a retry-on-`403`-with-`X-RateLimit-Remaining: 0` handler that sleeps until `X-RateLimit-Reset`. PyGithub raises `RateLimitExceededException` — catch it and respect the reset timestamp.

**Testing.** All tests mock the `Github` client. No test should make a real HTTP call. Use a fixture PR payload at `tests/fixtures/pr_payload.json`.

## Pitfalls

- **Posting per-finding comments.** The product is *one* consolidated comment, not many inline comments. Resist the urge to use review comments per line — they don't dedupe on re-runs and clutter the PR.
- **`comment.edit()` vs creating a new one.** If you create a new comment with an identical body instead of editing, the PR accumulates duplicates on every run. The marker + edit path is mandatory.
- **Marker version drift.** When the agent version bumps, the marker bumps too. Match on the marker *prefix* (`<!-- ai4sdlc-agent v`) when looking up an existing comment, not the full string — otherwise you'll create a new comment on every version bump.
- **`pr.diff_url` is not authenticated.** Don't fetch it without credentials for private repos. Use the REST endpoint with the `diff` media type and the bearer token.
- **PyGithub pagination by indexing.** `pr.get_files()[0]` forces a single-page fetch and then re-queries; iterate instead.
- **Treating the diff media type response as JSON.** It's `text/plain`. Use `r.text`, not `r.json()`.
- **Permissions block too permissive.** A leaked `contents: write` token from this workflow is a supply-chain risk. Keep it `read`.
- **Mocking `requests.get` for the diff but not for PyGithub.** Tests need to mock *both* surfaces — the PyGithub `Github` constructor and the `requests` call for the diff.
