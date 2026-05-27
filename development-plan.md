# Development Plan

> A phased plan for building **ai4sdlc-pr-review-agent** with [Claude Code](https://docs.claude.com/en/docs/claude-code/overview). Each phase ends with a commit. Each task is a single, self-contained prompt for Claude Code — give them one at a time, review the diff, commit, move on.

---

## How to use this plan

1. Open the repo in your terminal and start Claude Code (`claude` or `claude code`).
2. Run `/init` once to let Claude scaffold an initial `CLAUDE.md`; you'll refine it in Task 0.2.
3. Copy each **Task** block below as a single message to Claude Code. Wait for it to finish, review the diff, run the tests it added, then commit.
4. Read the relevant **Skill** files (under `.claude/skills/`) before starting a phase — Claude Code will auto-load them, but you should know what's in them so you can spot when it's drifting.

> **Cost note.** Phase 3 onwards calls the Anthropic API. Store all LLM responses used in tests as fixtures under `tests/fixtures/llm_responses/` so the test suite doesn't hit the API on every run.

---

## Project context (for `CLAUDE.md`)

This repository implements an **agentic AI workflow** that reviews GitHub pull requests and proposes remediations for security findings. It is a personal exploration of two themes:

- **AI4SDLC** — using AI to accelerate the software delivery lifecycle (the agent itself).
- **SDLC4AI** — building the agent in a secure, observable, evaluable way (how the agent is built).

The agent runs as a GitHub Action on every PR, executes SAST scanners (Bandit, Trivy, Semgrep) against the changed files, correlates findings with the diff, and posts a consolidated review comment via an LLM.

Companion to my MSc thesis on a low-code platform for developing BDI agents (Çelik, Kardas, Tezel — ISGR 2023).

---

## Skill list (under `.claude/skills/`)

Five skills cover the specialized knowledge for this project. Claude Code auto-loads them based on the description field, so write descriptions with concrete trigger words.

| Skill | Triggers when… | Contains |
|---|---|---|
| `langgraph-agent` | Adding nodes, state transitions, guardrail loops, checkpointing. | State schema patterns, conditional edges, retry/backoff, OpenTelemetry instrumentation hooks. |
| `sast-adapter` | Wiring a new scanner (Trivy, Bandit, Semgrep, …). | Each tool's JSON/SARIF schema, severity mapping, dedup strategy, the unified `Finding` model, test fixtures. |
| `github-pr-integration` | PyGithub usage — PR fetch, diff fetch, posting comments. | Least-privilege token scopes, rate-limit handling, idempotent comment posting, diff parsing. |
| `prompt-design` | Writing or evaluating prompts, JSON output enforcement, prompt versioning. | System-prompt structure, few-shot examples, `promptfoo` config patterns, prompt semver. |
| `observability` | Logging, tracing, metrics, propagating trace IDs into PR comments. | OpenTelemetry setup, structlog patterns, Langfuse / local OTLP collector wiring. |

---

## Phase 0 — Repo bootstrap (≈ 15 min)

### Task 0.1
```
Initialize this repository as a Python 3.11+ project. Use uv if available,
otherwise pip. Create the directory structure:

  agent/
  scanners/
  tests/
  examples/
  docs/
  evals/
  .claude/skills/
  .github/workflows/

Add a minimal pyproject.toml with dependencies:
  - langgraph
  - anthropic
  - PyGithub
  - pydantic
  - structlog
  - opentelemetry-api
  - opentelemetry-sdk

Dev dependencies: pytest, pytest-cov, ruff, mypy.

Generate a Python .gitignore. Add an MIT LICENSE with my name (Burak Çelik)
and the current year. Add an empty __init__.py to each package directory.
```

### Task 0.2
```
Create CLAUDE.md at the repo root. Include:

- Project purpose (a one-paragraph summary of the AI4SDLC PR-review agent
  and SDLC4AI build approach — pull from docs/development-plan.md).
- Architecture overview (the ASCII diagram from README.md).
- Coding conventions:
    - Type hints on every function and class.
    - Pydantic models for all I/O boundaries.
    - structlog instead of print().
    - No bare except.
    - Public functions get a docstring with a single-line summary and an
      Args/Returns section.
- Test command: pytest -v
- Lint commands: ruff check . && mypy agent scanners
- A "When in doubt" section pointing to the relevant SKILL.md files under
  .claude/skills/.
```

### Task 0.3
```
Create five skill directories under .claude/skills/ with their SKILL.md
files:

  langgraph-agent/SKILL.md
  sast-adapter/SKILL.md
  github-pr-integration/SKILL.md
  prompt-design/SKILL.md
  observability/SKILL.md

Each SKILL.md must:
- Start with YAML frontmatter containing `name` and `description`.
- The description must use concrete trigger phrases (e.g., for sast-adapter:
  "Use when adding or modifying a SAST scanner adapter (Bandit, Trivy,
  Semgrep), parsing SARIF/JSON scanner output, or mapping findings to the
  unified Finding model.").
- Be under 200 lines.
- Have a short "When to use this skill" section, a "Conventions" section,
  and a "Pitfalls" section.

For now write the skill content based on the trigger areas described in
docs/development-plan.md — we'll refine each skill in the phase that uses
it.
```

**Commit:** `chore: scaffold project structure, CLAUDE.md, and Claude Code skills`

---

## Phase 1 — Core data model + first scanners (≈ 30–45 min)

### Task 1.1
```
Design the unified Finding model in scanners/models.py as a pydantic
BaseModel. Fields:

  - tool: Literal["bandit", "trivy", "semgrep"]
  - rule_id: str
  - severity: Literal["critical", "high", "medium", "low", "info"]
  - file_path: str (relative to repo root)
  - line_start: int
  - line_end: int
  - message: str
  - remediation_hint: str | None
  - raw: dict[str, Any]  (the original tool output for that finding)

Add a from_bandit() / from_trivy() / from_semgrep() classmethod stub on
the model that we'll fill in later.

Write unit tests in tests/test_models.py covering:
  - Valid construction
  - Severity validation (rejects invalid values)
  - Serialization round-trip via .model_dump_json()
```

### Task 1.2
```
Implement the Bandit adapter in scanners/bandit_adapter.py. It must:

1. Provide a function `run_bandit(paths: list[str]) -> list[Finding]` that
   runs `bandit -r <paths> -f json` as a subprocess, captures stdout, and
   parses the JSON.
2. Map each Bandit issue to a Finding via Finding.from_bandit(...).
3. Map Bandit's severity (LOW/MEDIUM/HIGH) and confidence to our severity
   enum sensibly (e.g., HIGH severity + HIGH confidence -> "high"; LOW
   severity + LOW confidence -> "info").
4. Handle the case where bandit exits non-zero because findings were found
   (that is NOT an error — it's the normal "issues detected" exit code).

Before starting, read .claude/skills/sast-adapter/SKILL.md.

Add tests in tests/test_bandit_adapter.py:
  - Use a fixture file tests/fixtures/sample_vulnerable.py containing
    one assert_used issue and one hardcoded_password_string issue.
  - Assert that run_bandit returns exactly two findings with the expected
    rule_ids.
  - Mock subprocess.run for unit-level tests; mark integration tests with
    @pytest.mark.integration and skip them when bandit is not installed.
```

### Task 1.3
```
Add the Trivy filesystem-scan adapter in scanners/trivy_adapter.py with
the same shape as the Bandit one (run_trivy(paths) -> list[Finding]).
Trivy invocation: `trivy fs --format json --quiet <paths>`. Map Trivy's
"Severity" field directly to our enum (CRITICAL/HIGH/MEDIUM/LOW/UNKNOWN
-> info for UNKNOWN).

Add tests in tests/test_trivy_adapter.py. Use a small fixture
requirements.txt with a known-vulnerable pinned package version (e.g.,
`requests==2.19.0`) so Trivy will report CVEs reliably.
```

**Commit:** `feat(scanners): add Finding model and Bandit + Trivy adapters with tests`

---

## Phase 2 — Agent skeleton (≈ 45–60 min)

### Task 2.1
```
Implement the LangGraph agent skeleton in agent/graph.py. Define the
AgentState as a TypedDict:

  - repo: str  (owner/name)
  - pr_number: int
  - head_sha: str | None
  - diff: str | None
  - changed_files: list[str]
  - findings: list[Finding]
  - draft_review: ReviewOutput | None
  - posted_comment_id: int | None
  - trace_id: str

Wire the nodes as stubs (each just logs and returns the state unchanged):
  ingest_pr -> fetch_diff -> run_sast -> correlate -> draft_review
  -> guardrail_check -> post_comment

Use a conditional edge after guardrail_check: if the review is empty or
all comments were dropped, skip post_comment; otherwise proceed.

Before starting, read .claude/skills/langgraph-agent/SKILL.md.

Add a smoke test in tests/test_graph.py that builds the graph and runs
it end-to-end with all nodes stubbed — should complete without error.
```

### Task 2.2
```
Implement ingest_pr and fetch_diff using PyGithub.

ingest_pr(state) should:
  - Use the GITHUB_TOKEN env var.
  - Fetch the PR via repo.get_pull(pr_number).
  - Populate state["head_sha"] and state["changed_files"].

fetch_diff(state) should:
  - Use the GitHub REST API "diff" media type to fetch the unified diff.
  - Populate state["diff"].

Before starting, read .claude/skills/github-pr-integration/SKILL.md.

Add tests in tests/test_ingest.py using a mocked Github client (no real
HTTP). Provide one fixture PR payload at tests/fixtures/pr_payload.json.
```

### Task 2.3
```
Implement run_sast in agent/nodes/sast.py. It must:

  - Read state["changed_files"].
  - Filter to file types each scanner can handle (Bandit -> .py only,
    Trivy -> requirements.txt, pyproject.toml, package.json, etc.).
  - Run each enabled scanner against just those files (not the whole repo).
  - Aggregate findings, deduplicate by (tool, rule_id, file_path,
    line_start), and write to state["findings"].

Add a test using the fixtures from Phase 1.
```

**Commit:** `feat(agent): scaffold LangGraph state, ingest + diff + sast nodes`

---

## Phase 3 — LLM node (≈ 45 min)

### Task 3.1
```
Implement the draft_review node in agent/nodes/review.py.

Input: state["diff"], state["findings"].
Output: state["draft_review"] = ReviewOutput.

Define ReviewOutput in agent/models.py:
  - summary: str
  - comments: list[ReviewComment]
  - confidence: float  (0.0 - 1.0)

ReviewComment:
  - file_path: str
  - line: int
  - severity: Literal["critical", "high", "medium", "low", "info"]
  - message: str
  - remediation_snippet: str | None
  - source_finding_ids: list[str]  (rule_ids that motivated the comment)
  - confidence: float

Use the Anthropic SDK with model "claude-sonnet-4-6" (or the latest
sonnet — verify the model string in the Anthropic docs before hardcoding).
Enforce structured output using tool use: define a single tool
"submit_review" whose input_schema matches ReviewOutput, and require
Claude to call it. Parse tool_use blocks rather than parsing free text.

Before starting, read .claude/skills/prompt-design/SKILL.md.

Add tests with a recorded API response under
tests/fixtures/llm_responses/review_basic.json. Use a monkeypatched
Anthropic client that returns the fixture so tests don't hit the API.
```

### Task 3.2
```
Implement guardrail_check in agent/nodes/guardrail.py. It must drop a
ReviewComment if:

  - confidence < 0.6
  - file_path is not in state["changed_files"]
  - line is outside the line range of any hunk in the diff for that file
  - the comment duplicates an existing scanner finding without adding
    new context (compare message similarity > 0.85 using difflib)

Return a filtered ReviewOutput. If all comments are dropped, set
state["draft_review"] = None and signal "skip" in the conditional edge.

Add tests covering each drop reason.
```

### Task 3.3
```
Write the system prompt and few-shot examples in
agent/prompts/review_v1.md. Structure:

  ## Role
  You are an experienced security reviewer...

  ## Task
  Given a unified diff and a list of SAST findings, produce a structured
  review by calling the submit_review tool.

  ## Rules
  - Only comment on lines that appear in the diff.
  - For each comment, cite the SAST rule_id that motivated it (or "manual"
    if it's your own observation).
  - Set confidence < 0.6 when you're inferring intent rather than reading
    explicit risk.
  - Keep messages under 80 words.
  - For remediation_snippet, produce a minimal patch in unified diff
    format when feasible.

  ## Examples
  (2-3 worked examples)

Add a test that asserts the file exists and contains each section header
("## Role", "## Task", "## Rules", "## Examples").

Wire agent/nodes/review.py to load this file at startup.
```

**Commit:** `feat(agent): add LLM review node with structured output and guardrails`

---

## Phase 4 — Comment posting + observability (≈ 30 min)

### Task 4.1
```
Implement post_comment in agent/nodes/post.py.

It must:
  - Format the ReviewOutput as a single markdown comment (not many small
    inline comments — one consolidated review).
  - Include a footer with: agent version (read from importlib.metadata),
    prompt version (read from agent/prompts/review_v1.md), trace_id.
  - Be idempotent: if a previous comment on this PR has the same
    "<!-- ai4sdlc-agent vX.Y.Z -->" HTML comment marker, update it via
    issue_comment.edit() instead of creating a new one.

Add tests that exercise both the create and update paths via a mocked
Github client.
```

### Task 4.2
```
Add OpenTelemetry instrumentation to every node in the graph.

Setup in agent/telemetry.py:
  - A get_tracer() helper that configures OTLP exporter from
    OTEL_EXPORTER_OTLP_ENDPOINT env var.
  - A @traced_node decorator that wraps a graph node in a span named
    "node.<name>", records input keys and output keys as attributes, and
    records exceptions.

Apply @traced_node to every node. Generate state["trace_id"] in
ingest_pr and inject it as a span attribute on every subsequent span.

Add a docker-compose.yml under docs/observability/ that runs a local
OTLP collector + Jaeger UI for development. Document the workflow in
docs/observability/README.md.

Before starting, read .claude/skills/observability/SKILL.md.
```

**Commit:** `feat(agent): idempotent PR comment + OpenTelemetry instrumentation`

---

## Phase 5 — GitHub Actions workflow (≈ 20 min)

### Task 5.1
```
Write .github/workflows/review.yml. Requirements:

  - Trigger: pull_request types [opened, synchronize, reopened].
  - Permissions: pull-requests: write, contents: read.
  - Job runs on ubuntu-latest with Python 3.11.
  - Cache pip dependencies via actions/setup-python's built-in cache.
  - Install the package: pip install -e .
  - Install scanner CLIs: bandit, trivy (download the binary release).
  - Run: python -m agent.cli review \
           --repo "$GITHUB_REPOSITORY" \
           --pr "${{ github.event.pull_request.number }}"
  - Secrets: ANTHROPIC_API_KEY required; GITHUB_TOKEN provided by Actions.

Also create agent/cli.py exposing the `review` subcommand using argparse
or click.
```

### Task 5.2
```
Test the workflow end-to-end:

1. Push the current branch.
2. Open a PR against main that intentionally introduces a vulnerable
   snippet (e.g., a Python file using `eval(user_input)` and a
   requirements.txt with `requests==2.19.0`).
3. Watch the Actions run; confirm the agent posts a single consolidated
   review comment.
4. Capture screenshots into docs/screenshots/ (the PR comment, the
   Actions log, a Jaeger trace if you ran the collector locally).
5. Reference these screenshots in README.md under a new
   "## How it works in practice" section.
```

**Commit:** `ci: add review workflow + end-to-end demo screenshots`

---

## Phase 6 — Evaluation harness (≈ 30–45 min)

### Task 6.1
```
Set up an evaluation harness under evals/.

Option A (preferred): promptfoo
  - Create evals/promptfooconfig.yaml with 5–10 test cases.
  - Each test case is a recorded (diff, findings) pair under
    evals/cases/<name>/{diff.patch, findings.json, expected.json}.
  - Assertions:
      - exact match on comment count
      - regex match on key remediation phrases
      - severity distribution within expected bounds

Option B (fallback): a pytest-based eval at evals/test_eval.py with the
same fixtures.

Add a Makefile (or `just`-file) target `eval` that runs the harness.
```

### Task 6.2
```
Add a nightly evaluation CI job in .github/workflows/eval.yml:

  - Trigger: schedule "0 3 * * *" + workflow_dispatch.
  - Run the eval harness.
  - On failure or score regression > 10%, open or update a GitHub Issue
    titled "Nightly eval regression — <date>" with the diff vs. last
    passing run.

This shows recruiters you take eval-driven development seriously.
```

**Commit:** `test: add promptfoo evaluation harness + nightly CI`

---

## Phase 7 — Polish (≈ 20 min)

### Task 7.1
```
Polish README.md:
  - Replace the placeholder ASCII screenshot with the real one from
    docs/screenshots/.
  - Expand "Architecture" with a Mermaid diagram of the LangGraph nodes.
  - Update the "Roadmap" checkboxes to match actually completed items.
  - Add a "Run locally" section with the exact commands.
  - Add a "Cost" section: approx Anthropic API cost per PR review
    (measure from the trace and document it honestly).
```

### Task 7.2
```
Repo cosmetics:
  - Add GitHub repository topics: langgraph, agentic-ai, devsecops, sast,
    ai4sdlc, github-actions, claude.
  - Set the repo description (one sentence).
  - Pin this repo on my GitHub profile (instruct me to do this manually).
  - Add a CODE_OF_CONDUCT.md and CONTRIBUTING.md (short, link to GitHub's
    templates).
```

### Task 7.3
```
Write a draft LinkedIn post in docs/launch-post.md announcing the project.
3 paragraphs:

1. What the project is and the AI4SDLC framing — why I built it.
2. Connection to my MSc thesis on a low-code platform for BDI agents,
   and how this is a real-world counterpart focused on developer-
   productivity agents inside the SDLC.
3. A call-to-action — link to the repo, invite feedback, mention I'm
   exploring opportunities in this space.

Don't post it yet; just have the draft ready.
```

**Commit:** `docs: polish README, repo metadata, and launch post`

---

## Estimated time

| Phase | Active time |
|---|---|
| 0 — Bootstrap | 15 min |
| 1 — Data model + first scanners | 30–45 min |
| 2 — Agent skeleton | 45–60 min |
| 3 — LLM node | 45 min |
| 4 — Comments + observability | 30 min |
| 5 — GitHub Actions | 20 min |
| 6 — Eval harness | 30–45 min |
| 7 — Polish | 20 min |
| **Total** | **~3.5–4 hours** |

Reasonable as a single Saturday project, or two weekday-evening sessions (Phases 0–3 first, 4–7 next).

---

## Working tips for Claude Code

- **One task at a time.** Pasting two tasks at once causes Claude to interleave context. Wait for completion, review, commit.
- **Trust the tests.** If Claude writes code without tests in a phase that calls for them, push back: "Add unit tests for this module before we move on."
- **Re-read skills if drift appears.** If a node is doing GitHub work but ignoring the patterns in `github-pr-integration/SKILL.md`, tell Claude explicitly: "Re-read `.claude/skills/github-pr-integration/SKILL.md` and refactor this node to follow it."
- **Stage skill refinement.** Skills are living documents. When you spot Claude making the same mistake twice, add a "Pitfalls" entry to the relevant SKILL.md — that's the point of the system.
- **Don't commit secrets.** Verify `.env` is in `.gitignore` before any `git commit`. Claude Code will respect it if you tell it to, but verify.

---

*Last updated: maintain this file as the source of truth for the project plan. Update task checkmarks below as you complete each phase.*

### Progress

- [x] Phase 0 — Bootstrap
- [x] Phase 1 — Data model + scanners
- [ ] Phase 2 — Agent skeleton
- [ ] Phase 3 — LLM node
- [ ] Phase 4 — Comments + observability
- [ ] Phase 5 — GitHub Actions
- [ ] Phase 6 — Evaluation harness
- [ ] Phase 7 — Polish
