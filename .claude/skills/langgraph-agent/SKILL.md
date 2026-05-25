---
name: langgraph-agent
description: Use when adding a node to the LangGraph review agent, editing AgentState, wiring conditional edges or guardrail loops, adding retry/backoff to a node, or attaching OpenTelemetry instrumentation to graph execution.
---

# langgraph-agent

The review agent is built as a LangGraph state machine. This skill captures the conventions for that graph so nodes stay testable in isolation and the conditional routing stays predictable.

## When to use this skill

- Adding or modifying a node in `agent/graph.py` or `agent/nodes/`.
- Changing the shape of `AgentState` (adding/removing/renaming a field).
- Wiring or modifying a conditional edge (e.g., the `guardrail_check → post_comment` skip logic).
- Adding retry/backoff to a node, or threading checkpointing through the graph.
- Hooking OpenTelemetry spans into graph execution (`@traced_node`).

## Conventions

**State shape.** `AgentState` is a `TypedDict` (LangGraph convention — not Pydantic). Canonical keys, in roughly the order they're populated:

```
repo: str               # owner/name
pr_number: int
head_sha: str | None
diff: str | None
changed_files: list[str]
findings: list[Finding]
draft_review: ReviewOutput | None
posted_comment_id: int | None
trace_id: str
```

**Node signatures.** Each node is a pure function `node(state: AgentState) -> dict` that returns a *partial state update*, not a mutated state. LangGraph merges the returned dict into the running state. Never reach into `state[...] = ...` and mutate in place.

**Node sequence.**

```
ingest_pr → fetch_diff → run_sast → correlate → draft_review → guardrail_check → post_comment
```

**Conditional edges.** Implement edge predicates as named module-level functions that return a `Literal["proceed", "skip", ...]`. Wire them with `add_conditional_edges(node, predicate, {"proceed": next, "skip": END})`. The mapping keys must match the predicate's return literals exactly — typos here fail silently at runtime.

**Guardrail loop.** When a guardrail drops *all* comments, set `state["draft_review"] = None` and return `"skip"` so `post_comment` is bypassed. Don't retry the LLM call inside the guardrail itself; if a retry is genuinely needed, route back to `draft_review` via a conditional edge.

**Instrumentation.** Every node is decorated with `@traced_node` (defined in `agent/telemetry.py`). The decorator names the span `node.<func.__name__>`, records input/output keys as attributes, and records exceptions on the span. `trace_id` is generated once in `ingest_pr` and propagated via `state["trace_id"]`.

**Testing.** Each node is unit-testable by calling `node({...minimal state...})` directly. Graph-level tests in `tests/test_graph.py` build the graph with node stubs to assert routing.

## Pitfalls

- **Mutating state in place** breaks LangGraph's update semantics. Return a partial dict; never `state[key] = value`.
- **Conditional-edge typos.** The predicate's return literal and the `add_conditional_edges` mapping key must match character-for-character. Pin both via a `Literal[...]` type alias and reuse it on both sides.
- **Hidden graph dependencies inside a node.** If a node imports the compiled graph or another node directly, unit tests become integration tests. Nodes should depend only on `AgentState` and the modules in `agent/nodes/`.
- **Retry loops as a coping mechanism for flaky LLM output.** That's what `guardrail_check` is for — drop low-confidence comments, don't paper over them with retries.
- **Forgetting `@traced_node`.** A node without the decorator is invisible in traces and silently swallows exceptions in different ways than the rest of the graph. Apply it to every node, including stubs.
- **Stale `head_sha`.** `ingest_pr` captures `head_sha` once. If the PR is pushed to mid-run, downstream nodes still operate against the original SHA — that's intentional, but the PR-comment footer should reference that SHA so reviewers know which commit was reviewed.
