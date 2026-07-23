# ADR 0002: LangGraph supervisor with PydanticAI specialists

## Status

Accepted. Implemented in Phase 5, extended in Phases 6-8.

## Context

PitCrew's assistant needs to classify a user's question, route it to the right domain logic (diagnostics, scheduling, or knowledge lookup), and let each domain agent call typed tools safely.
Two real options existed: a small hand-written router (an if/elif over an intent string, or a single-function dispatcher), or a graph-based orchestration framework.

The design spec names this tension explicitly rather than treating the choice as obvious.
A hand-written supervisor would be simpler to read and would have less dependency surface.
But this project's stated purpose is to read as senior AI-engineer work on a CV, and LangGraph is, as of this writing, one of the most recognized agent-orchestration signals reviewers look for.

## Decision

Use LangGraph's `StateGraph` for the supervisor's routing (`backend/app/agents/supervisor.py`), and PydanticAI for each specialist's typed inputs, outputs, and tool calls (`backend/app/agents/specialists/`).

The compiled graph is: `START -> classify_intent --route--> {diagnostics | scheduling | knowledge} -> compose -> END`.
`classify_intent` asks the LLM to name the route in one word and defaults to `knowledge` (the safest failure mode - it degrades to "no documentation on this" rather than misfiring a write path or a wrong prediction) if the answer does not parse cleanly.
Each specialist is invoked through its own PydanticAI agent, with the shared `LLMClient` and `AgentDeps` (vehicle data, KB search) injected as dependencies, and each specialist's tool calls (`predict_service`, `schedule_service`, `search_kb`) are typed Pydantic models, not free-form dict payloads.

One deliberate, disclosed inconsistency: `classify_intent` calls `LLMClient.complete()` directly rather than going through a PydanticAI agent, specifically so intent classification stays provable via a single `ReplayClient` cassette exactly like every other LLM call in the app (see the module's own docstring).
This keeps the typed-agent pattern for the three specialists, where the extra structure pays for itself, while keeping the one-word classification step as simple as it can be.

## Consequences

**Positive**:
The routing logic is inspectable in one graph definition rather than scattered across conditionals, and this shows in the streaming trace UI - `astream(stream_mode="updates")` yields genuine per-node events (`classify_intent`, the chosen specialist, `compose`) that the frontend's agent-activity trace renders directly, with no synthetic step list to maintain separately.
Guardrails (the iteration-budget kill switch, and catching a Groq rate limit as a friendly message rather than a crash) are wired uniformly at every node, because every node goes through the same graph machinery.
PydanticAI's typed tool interface caught a real bug during Phase 5 review: a tool provider was silently defaulting `kms_driven` to `0.0`, feeding a fabricated feature into the real prediction model rather than genuinely degrading; the typed contract made the wrong value visible enough to trace end to end.

**Negative**:
This is one more framework dependency and its own learning curve, a cost the spec accepts deliberately rather than treating as free.
`compose` is currently a pass-through node (each specialist already produces a final, citable answer), kept as its own graph node mainly so a later phase could add cross-specialist formatting without touching routing - today it adds a small amount of indirection for no behavioral gain yet.
The scheduling specialist's persistence is an in-memory `InMemoryScheduler` stub (no `appointments` table exists), which is a reasonable scope choice for a demo but means a booking does not survive a process restart; the guardrail test that requires explicit `confirmed=True` before any write is genuinely meaningful regardless, since it exercises the real tool boundary, not a mock of it.
