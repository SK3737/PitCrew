# ADR 0005: Free-tier Groq for live chat, local CPU embeddings and reranking for RAG

## Status

Accepted. Implemented in Phases 5-7.

## Context

This project's hardest constraint (stated in the design spec's non-goals) is that no paid LLM API is ever called anywhere in the code, because this is a portfolio demo, not a revenue product, and the assistant still needs to feel like a real, live, multi-turn agent rather than a canned script.
Separately, RAG needs embeddings for dense retrieval and a cross-encoder for reranking, and calling a metered embedding API for every ingest and every query would reintroduce exactly the cost dependency the no-paid-API rule exists to avoid.

## Decision

**Live chat/reasoning**: Groq's free tier (`llama-3.3-70b-versatile`, OpenAI-compatible chat completions API), reached only through this project's own `LLMClient` abstraction (`backend/app/agents/llm_client.py`) so no agent code ever imports a provider SDK directly.
Groq was chosen specifically because it costs nothing and needs no local GPU, which is what makes a genuinely live hosted demo possible at all under this project's constraints.
The same `LLMClient` interface also has a `ReplayClient` implementation: deterministic, cassette-backed, the only backend the test suite and CI ever exercise (`LLM_BACKEND=replay`), so tests never depend on Groq's uptime and never burn its free-tier quota.
An unrecorded request under replay raises a typed `CassetteMiss` rather than silently falling back to a live call - a safety property, not just a convenience.

**Embeddings and reranking**: run locally on CPU in every environment, live and replay alike, and are deliberately **not** part of the live/replay split at all.
Dense retrieval uses `sentence-transformers/all-MiniLM-L6-v2`; reranking uses `cross-encoder/ms-marco-MiniLM-L-6-v2`.
Both are free, light enough to need no GPU, and are exercised identically in tests and in production, so there is no "replay embeddings" concept to maintain.

## Consequences

**Positive**:
A real, live, free assistant is possible to host at all, which is the entire point of choosing Groq over a paid provider - the demo does not have to be replay-only in production the way a paid-API constraint would otherwise force.
CI stays fully deterministic and offline: 119 backend tests, the Playwright e2e suite, and the eval gate (Ragas + DeepEval) all run under `LLM_BACKEND=replay` with zero network calls and zero dependency on Groq's own availability or rate limits.
Local embeddings/reranking mean RAG's cost scales with compute, not with API calls, so ingesting or querying the knowledge base repeatedly never touches a metered service.

**Negative - the real rate-limit tradeoff**:
Groq's free tier has genuine per-minute and per-day rate limits, and a real deployment under actual reviewer traffic (even light traffic, since this is a portfolio demo, not production load) can hit a `429` more often than a paid tier would.
The supervisor catches this at every graph node and degrades to a friendly "assistant is busy, try again shortly" message rather than crashing or silently retrying into a storm, which is the correct guardrail, but it is still a materially worse user experience than a paid tier's higher limits would give, and this tradeoff is accepted deliberately, not accidentally.
A second, smaller cost: the eval suite's judge scores in this repository were produced with `LLM_BACKEND=replay` and hand-synthesized judge cassettes (see the README's eval scores table and `.superpowers/sdd/task-9-report.md`), not a live Groq judge call, precisely because a live judge run would also compete with the free tier's rate limits; a future live-Groq-judged run is expected to produce broadly similar but not necessarily byte-identical scores.
Local model inference also adds first-request latency on a cold Render container (loading `sentence-transformers`/cross-encoder weights into memory), which the keep-warm mitigation named in ADR 0004 is intended to reduce but does not eliminate.
