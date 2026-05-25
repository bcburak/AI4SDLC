---
name: observability
description: Use when adding structlog logging, configuring OpenTelemetry tracing, wrapping a graph node with @traced_node, propagating trace_id into a PR comment footer, or wiring the local OTLP collector / Jaeger setup under docs/observability/.
---

# observability

Every PR review is one trace. Each graph node is one span. The PR comment carries the trace ID so reviewers can pull up the full execution from a single click. This skill captures how that wiring stays consistent.

## When to use this skill

- Adding a new graph node and wrapping it with `@traced_node`.
- Adding or changing structlog calls inside agent code.
- Editing `agent/telemetry.py` (the tracer/exporter setup).
- Updating the PR-comment footer format (it carries `trace_id`).
- Touching `docs/observability/` (local docker-compose for OTLP collector + Jaeger).

## Conventions

**Logging.**

- Use `structlog`, never `print()` and never stdlib `logging` directly.
- Get a logger at module top: `log = structlog.get_logger(__name__)`.
- Log with structured fields, not formatted strings:

  ```python
  log.info("sast.complete", tool="bandit", findings=len(findings), trace_id=state["trace_id"])
  ```

  Not `log.info(f"bandit found {len(findings)} findings")`.

**Tracing setup** (`agent/telemetry.py`):

- A `get_tracer()` helper configures the OTLP exporter from `OTEL_EXPORTER_OTLP_ENDPOINT`. If the env var is unset, fall back to a no-op tracer so local dev without a collector still works.
- A `@traced_node` decorator wraps a graph node in a span named `node.<func.__name__>`, records `input_keys` and `output_keys` as span attributes, attaches `trace_id` from state, and records exceptions on the span before re-raising.

**Trace ID lifecycle.**

- Generated **once** in `ingest_pr` (`uuid4().hex` is fine — keep the format short for the PR comment footer).
- Stored in `state["trace_id"]` and propagated by every node automatically through `@traced_node`.
- Included in the PR-comment footer alongside agent version and prompt version, so a reviewer can copy/paste it into the trace backend.

**PR-comment footer format:**

```
---
*Reviewed by ai4sdlc-agent v{agent_version} · prompt {prompt_version} · trace {trace_id}*
```

**Local development.** `docs/observability/docker-compose.yml` runs an OTLP collector and a Jaeger UI on localhost. `docs/observability/README.md` documents the workflow: start the stack, set `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`, run the agent locally, open Jaeger at `http://localhost:16686`.

**Production exporter.** The Actions workflow sets `OTEL_EXPORTER_OTLP_ENDPOINT` to whatever the team is using (e.g., Langfuse, Honeycomb, an org-internal collector). The agent code is endpoint-agnostic — only the env var changes.

## Pitfalls

- **Logging raw LLM prompt/response at default level.** Diffs and findings can contain credentials, internal hostnames, etc. Log lengths, model name, latency, and outcomes — never the full text at INFO. If you need full payloads for debugging, gate them behind a DEBUG-level log *and* a config flag.
- **Stuffing dicts into log messages.** `log.info(f"state: {state}")` defeats structured logging and leaks fields uncontrollably. Pass fields as kwargs.
- **Forgetting `@traced_node`.** A node without the decorator doesn't appear in the trace, which makes the rest of the trace look correct but with a missing step. Apply it to *every* node, including stubs.
- **Creating a tracer per call.** `get_tracer()` should be idempotent and module-cached. Repeated initialization re-registers the exporter and double-exports spans.
- **Swallowing exceptions inside `@traced_node`.** The decorator records the exception on the span *and* re-raises. Letting the exception propagate is what makes the graph's error edge fire.
- **Trace ID format too long for a PR comment.** A full 128-bit OTel trace ID is fine in the span but unwieldy in the comment footer. The hex of a `uuid4()` (32 chars) or the first 16 chars is the sweet spot — long enough to grep, short enough to skim.
- **No-op when OTLP env var is missing.** If `get_tracer()` raises when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, local runs break. Fall back to a no-op tracer so the agent runs the same way with and without a collector.
- **Mixing trace IDs across PR re-runs.** Each re-run is a *new* trace. Don't reuse a trace ID across runs to "stitch" them — the comment footer should reflect the latest run's trace.
