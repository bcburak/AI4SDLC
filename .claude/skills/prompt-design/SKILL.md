---
name: prompt-design
description: Use when writing or editing a prompt under agent/prompts/, enforcing structured output via Anthropic tool use, versioning a prompt, designing few-shot examples, or wiring promptfoo eval cases.
---

# prompt-design

The agent's LLM step (`draft_review`) is the most expensive and most variable part of the pipeline. This skill captures how prompts are structured, versioned, and tested so changes are auditable and regressions are catchable.

## When to use this skill

- Creating a new prompt under `agent/prompts/<name>_v<N>.md`.
- Editing an existing prompt's role, task, rules, or few-shot examples.
- Defining or changing the Anthropic tool that enforces structured output (`submit_review`).
- Bumping a prompt version and regenerating fixtures.
- Authoring `promptfoo` test cases under `evals/`.

## Conventions

**File layout.** Prompts live in `agent/prompts/<name>_v<N>.md`. The current review prompt is `review_v1.md`. Versions are immutable once committed — to change behavior, write `review_v2.md` and update the loader. Never edit a published version.

**Required section structure** in every prompt file:

```markdown
## Role
You are an experienced security reviewer...

## Task
Given a unified diff and a list of SAST findings, produce a structured
review by calling the submit_review tool.

## Rules
- Only comment on lines that appear in the diff.
- Cite the SAST rule_id that motivated each comment (or "manual").
- Set confidence < 0.6 when inferring intent rather than reading explicit risk.
- Keep messages under 80 words.
- For remediation_snippet, produce a minimal patch in unified diff format when feasible.

## Examples
(2-3 worked examples — concrete diff + findings → tool call)
```

A test asserts each `##` header exists; don't rename them.

**Structured output via tool use.** Do not ask for JSON in free text. Define a single Anthropic tool whose `input_schema` mirrors the Pydantic output model and **require** Claude to call it:

```python
tools = [{
    "name": "submit_review",
    "description": "Submit the structured PR review.",
    "input_schema": ReviewOutput.model_json_schema(),
}]
tool_choice = {"type": "tool", "name": "submit_review"}
```

Parse `response.content[i].input` from the `tool_use` block — do not regex-scrape free text.

**Model.** Use the latest Sonnet. As of this writing that's `claude-sonnet-4-6`; verify the model ID against the Anthropic docs before hardcoding, and update it in one place (`agent/nodes/review.py`).

**Few-shot examples.** Each example shows a `(diff, findings) → submit_review(args)` mapping. Keep them small (one or two findings each) and chosen to demonstrate the *rules* — not just to look impressive. If you can't articulate which rule an example demonstrates, drop it.

**Prompt context layout in the request.** System message is the prompt file. The diff and the findings list go in the user message, clearly delimited:

```
<diff>
...unified diff...
</diff>

<findings>
[{...}, {...}]
</findings>
```

Don't embed the diff in the system message — it inflates the cached-prefix portion needlessly.

**Versioning.** Use prompt semver in the file name (`_v1`, `_v2`). Read the version number from the file path at startup and inject it into the PR comment footer + OTel span attributes. Bumping a version invalidates fixtures under `tests/fixtures/llm_responses/` — regenerate them in the same PR.

**Testing.**

- Unit tests for `draft_review` use a monkeypatched Anthropic client that returns a fixture from `tests/fixtures/llm_responses/`. No live calls.
- Eval cases under `evals/cases/<name>/` carry `{diff.patch, findings.json, expected.json}` and are driven by `evals/promptfooconfig.yaml`.

## Pitfalls

- **Asking for JSON in text.** Even when the model is good, free-text JSON is unreliable across versions and locales. Use tools.
- **Optional tool calls.** If `tool_choice` is left as `auto`, Claude may respond in text and skip the tool. Set `tool_choice` to require the specific tool.
- **Editing a published prompt version.** That silently invalidates every fixture and eval that referenced `_v1`'s behavior. Write `_v2` instead.
- **Few-shot bloat.** Each example you add increases per-call cost on every PR forever. Keep the set small and trim aggressively.
- **Mismatched schema.** `input_schema` drifting from the Pydantic model means Claude produces fields the parser drops, or omits fields the parser requires. Generate the schema from the model (`Model.model_json_schema()`), don't hand-write it.
- **Confidence as a hedge.** A blanket `confidence: 0.9` on every comment makes the guardrail useless. The prompt's rules tie confidence to *evidence*; if you change that rule, update the few-shot examples to match.
- **Inlining the diff in the system prompt.** It defeats prompt caching and inflates every request. User-message only.
