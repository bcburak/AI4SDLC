# ai4sdlc-pr-review-agent

> An agentic AI workflow that reviews pull requests and proposes remediations for security findings — built as a reusable building block for the **AI4SDLC** vision (AI accelerating the software delivery lifecycle).

[![Status](https://img.shields.io/badge/status-work%20in%20progress-yellow)](#roadmap)
[![Python](https://img.shields.io/badge/python-3.11+-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Why this exists

Most teams have CI/CD pipelines, SAST scanners, and code review checklists, but the **interpretation** of findings still falls on engineers — slow, error-prone, and inconsistent across teams.

This project explores how an **LLM-backed agent**, wired into the same SDLC ecosystem developers already use (GitHub, Actions, SAST tools), can:

1. Read a pull request and its diff.
2. Run static analysis (Trivy, Bandit, Semgrep) on the changed files.
3. Cross-reference findings with the diff context.
4. Produce a structured PR comment with prioritized review notes and concrete remediation suggestions.

The agent is designed as a **horizontal capability** — not a one-off bot, but a reusable component other teams can adopt with minimal configuration.

## Architecture

```
┌────────────────┐    ┌──────────────────────┐    ┌─────────────────┐
│  GitHub PR     │───▶│  GitHub Actions       │───▶│  Review Agent   │
│  (event)       │    │  workflow             │    │  (Python +      │
└────────────────┘    │                       │    │   LangGraph)    │
                      │  ┌─────────────────┐  │    └────────┬────────┘
                      │  │ SAST scanners   │  │             │
                      │  │ Trivy / Bandit  │──┼─────────────┤
                      │  │ Semgrep         │  │             │
                      │  └─────────────────┘  │             ▼
                      └───────────────────────┘    ┌─────────────────┐
                                                   │  PR comment +   │
                                                   │  review summary │
                                                   └─────────────────┘
```

Agent graph (LangGraph):

```
ingest_pr  →  fetch_diff  →  run_sast  →  correlate  →  draft_review  →  post_comment
                                  │
                                  └──▶  guardrail_check  ──▶  (loop if low confidence)
```

## What's in the repo

| Path | Purpose |
|---|---|
| `agent/` | LangGraph agent definition, prompts, tool wrappers |
| `scanners/` | Adapters for Trivy, Bandit, Semgrep — normalized output schema |
| `.github/workflows/review.yml` | GitHub Actions workflow that runs the agent on every PR |
| `tests/` | Unit tests for tool wrappers + integration tests with recorded fixtures |
| `examples/` | Sample PRs and the resulting review comments |
| `docs/` | Architecture notes, prompt design, evaluation setup |

## Quick start

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Set credentials
export OPENAI_API_KEY=...
export GITHUB_TOKEN=...

# 3. Run locally against a public PR
python -m agent.cli review \
  --repo owner/repo \
  --pr 123 \
  --scanners trivy,bandit,semgrep \
  --dry-run
```

## Design principles

- **Secure by design.** The agent runs in a restricted execution environment, has read-only repo access, and posts comments via a least-privilege token. No code execution against the PR.
- **Identity- and entitlement-aware.** All actions flow through a single, auditable service identity. Every comment is signed with the agent version and scanner versions used.
- **Observable.** OpenTelemetry traces for each node in the agent graph; structured logs; PR comments include the trace ID for debugging.
- **Evaluable.** A growing test set of recorded PRs with expected behaviour, scored with a deterministic eval harness.
- **Reusable.** Drop-in `review.yml` workflow + a single config file is enough to onboard a new repo.

## Roadmap

- [x] Repo scaffolding and minimal agent loop
- [x] Trivy + Bandit scanner adapters
- [ ] Semgrep scanner adapter
- [ ] Confidence-scored guardrail node (skip low-signal comments)
- [ ] Evaluation harness with `promptfoo`
- [ ] Reusable GitHub Action published to the Marketplace
- [ ] Companion repo: **sdlc4ai-template** — secure lifecycle template for shipping LLM apps

## Background

This work is part of a broader interest in the intersection of **agentic AI** and **secure software delivery**. It builds on my MSc research on a low-code platform for developing Belief-Desire-Intention (BDI) agents (Çelik, Kardas, Tezel — ISGR 2023), now applied to a different kind of agent: one that operates inside the developer's toolchain rather than as a standalone application.

## License

MIT — see [LICENSE](LICENSE).
