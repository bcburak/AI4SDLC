# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project purpose

`ai4sdlc-pr-review-agent` is an agentic AI workflow that reviews GitHub pull requests and proposes remediations for security findings. It runs as a GitHub Action on every PR, executes SAST scanners (Bandit, Trivy, Semgrep) against the changed files, correlates findings with the diff, and posts a consolidated review comment via an LLM. Two framings drive the work: **AI4SDLC** — using AI to accelerate the software delivery lifecycle (what the agent does) — and **SDLC4AI** — building the agent in a secure, observable, evaluable way (how the agent is built). It is the practical counterpart to MSc research on a low-code platform for Belief-Desire-Intention (BDI) agents (Çelik, Kardas, Tezel — ISGR 2023).

## Architecture overview

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

LangGraph node sequence:

```
ingest_pr → fetch_diff → run_sast → correlate → draft_review → guardrail_check → post_comment
                                                                       │
                                                                       └──▶ (loop if low confidence; skip post_comment if review empty)
```

State is a TypedDict keyed by `repo`, `pr_number`, `head_sha`, `diff`, `changed_files`, `findings`, `draft_review`, `posted_comment_id`, `trace_id`. The conditional edge after `guardrail_check` skips `post_comment` when the review is empty or all comments were dropped.

## Coding conventions

- Type hints on every function and class.
- Pydantic models for all I/O boundaries (scanner outputs, LLM outputs, PR payloads).
- `structlog` instead of `print()`.
- No bare `except`.
- Public functions get a docstring with a single-line summary and an `Args` / `Returns` section.

Additional standards in force across the project:

- Python 3.11+.
- LLM responses used in tests must be stored as fixtures under `tests/fixtures/llm_responses/` — tests must not hit the Anthropic API.
- Structured output from Claude is enforced via tool use (a `submit_review` tool whose `input_schema` matches the Pydantic model), not by parsing free text.
- PR-comment posting is idempotent: re-runs on the same PR update the existing comment (matched by an `<!-- ai4sdlc-agent vX.Y.Z -->` HTML marker) rather than creating a new one.

## Commands

- Tests: `pytest -v`
- Lint + types: `ruff check . && mypy agent scanners`
- Single test file: `pytest -v tests/test_models.py`
- Single test by name: `pytest -v -k test_name`
- Integration tests (require Bandit/Trivy installed): `pytest -v -m integration`
- Local agent run (Phase 5+): `python -m agent.cli review --repo owner/repo --pr 123 --scanners trivy,bandit,semgrep --dry-run`

Required env vars at runtime: `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`. Optional: `OTEL_EXPORTER_OTLP_ENDPOINT`.

Environment setup with uv: `uv sync --extra dev` creates `.venv` and installs runtime + dev dependencies from `pyproject.toml`.

## When in doubt

The development plan (`development-plan.md` at the repo root) is the source of truth for what to build and in what order — Phases 0–7, with each task written as a self-contained prompt. Check the **Progress** checklist at the bottom of that file before starting work; implement one task at a time, review the diff, commit, then continue.

For implementation specifics, read the matching `SKILL.md` under `.claude/skills/` **before** touching the area it covers — these encode project-specific patterns and pitfalls that are easy to miss:

| Topic | Skill |
|---|---|
| Graph nodes, state transitions, guardrail loops, OTel hooks | `.claude/skills/langgraph-agent/SKILL.md` |
| Scanner adapters (Bandit/Trivy/Semgrep), SARIF/JSON parsing, the unified `Finding` model | `.claude/skills/sast-adapter/SKILL.md` |
| PyGithub usage, diff fetching, posting/editing PR comments, rate limits, token scopes | `.claude/skills/github-pr-integration/SKILL.md` |
| Prompts, JSON output via tool use, prompt versioning, `promptfoo` | `.claude/skills/prompt-design/SKILL.md` |
| structlog, OpenTelemetry tracing, propagating `trace_id` into PR comments | `.claude/skills/observability/SKILL.md` |

If a node is doing work a skill covers but ignoring the skill's patterns, re-read the skill and refactor — that's the failure mode the skill system exists to prevent.
