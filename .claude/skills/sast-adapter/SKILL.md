---
name: sast-adapter
description: Use when adding or modifying a SAST scanner adapter (Bandit, Trivy, Semgrep), parsing SARIF/JSON scanner output, mapping scanner severities to the unified Finding enum, deduplicating findings across scanners, or writing fixtures for scanner tests.
---

# sast-adapter

The agent normalizes output from multiple SAST tools into a single `Finding` model so downstream nodes don't need to know which scanner produced what. This skill captures the shape every adapter must match.

## When to use this skill

- Adding a new scanner adapter under `scanners/` (e.g., `semgrep_adapter.py`).
- Editing an existing adapter (Bandit, Trivy).
- Touching `scanners/models.py` (the `Finding` model).
- Writing or updating fixtures under `tests/fixtures/` that drive scanner tests.
- Implementing or changing the dedup logic that aggregates findings.

## Conventions

**Adapter shape.** Each adapter exposes a single entry point:

```python
def run_<tool>(paths: list[str]) -> list[Finding]: ...
```

It runs the scanner CLI as a subprocess, parses stdout, and maps each issue to a `Finding` via a `Finding.from_<tool>(raw_issue)` classmethod. Keep parsing in the classmethod; keep `run_<tool>` focused on the subprocess and error handling.

**The Finding model** (`scanners/models.py`) is the single I/O boundary:

```
tool: Literal["bandit", "trivy", "semgrep"]
rule_id: str
severity: Literal["critical", "high", "medium", "low", "info"]
file_path: str           # relative to repo root
line_start: int
line_end: int
message: str
remediation_hint: str | None
raw: dict[str, Any]      # the original tool output for that finding
```

Always populate `raw` with the unmodified tool output for the issue. Downstream debugging needs it.

**Severity mapping.**

- **Trivy:** map `Severity` field directly — CRITICAL/HIGH/MEDIUM/LOW → same; UNKNOWN → `"info"`.
- **Bandit:** combine `issue_severity` and `issue_confidence`. Rule of thumb: HIGH+HIGH → `"high"`, HIGH+MEDIUM → `"medium"`, MEDIUM+HIGH → `"medium"`, LOW+LOW → `"info"`, anything else → `"low"`. Document the table in the adapter.
- **Semgrep:** map `severity` field (ERROR/WARNING/INFO) plus rule metadata when available.

**File paths** in `Finding.file_path` are always **relative to the repo root**. Convert tool-specific absolute paths before constructing the `Finding`.

**Deduplication.** Findings are deduplicated by the tuple `(tool, rule_id, file_path, line_start)`. Dedup happens in `agent/nodes/sast.py`, not inside individual adapters. Adapters return everything they find; the node decides what's a duplicate.

**Subprocess invocation.**

- `bandit -r <paths> -f json`
- `trivy fs --format json --quiet <paths>`
- `semgrep --json --quiet <paths>` (use a pinned ruleset)

Capture stdout; let stderr surface for debugging. Do **not** use `check=True` blindly — most of these tools exit non-zero when findings exist (see Pitfalls).

**Tests.**

- Unit tests mock `subprocess.run` and feed parsing logic a recorded JSON blob. These never call the real binary.
- Integration tests carry `@pytest.mark.integration` and are skipped when the binary isn't on `PATH` (use `shutil.which`).
- Fixtures live under `tests/fixtures/` — small, focused, and committed to the repo so they're stable.

## Pitfalls

- **Non-zero exits aren't errors.** Bandit, Trivy, and Semgrep all exit non-zero when issues are detected. That's the *normal* "issues found" exit code. Parse stdout regardless and only treat exit codes outside the documented set as failures.
- **Mixing severity and confidence.** Bandit gives you both; using only one loses signal. Define an explicit mapping table and stick to it.
- **Path normalization.** Trivy reports paths relative to its scan root, Bandit reports absolute paths, Semgrep can do either depending on flags. Normalize to "relative to repo root" before constructing the `Finding`.
- **Dedup keyed on message text.** Don't — messages drift across tool versions. Use `(tool, rule_id, file_path, line_start)`.
- **Trivy needs the manifest file in the path list.** `trivy fs <dir>` works, but if you pass a directory that doesn't contain a recognizable manifest (`requirements.txt`, `package.json`, etc.), Trivy returns nothing. When scanning a changed-files subset, include the manifest explicitly.
- **Losing tool-specific context.** Don't normalize fields away — preserve them in `raw`. The LLM prompt and the eval harness both pull from `raw` when they need more than the normalized fields.
- **Fixture drift.** Pin scanner versions in CI. Fixture JSON regenerated against a newer scanner may not match what CI sees.
