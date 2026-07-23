"""
Task 9.1/9.2: Ragas + DeepEval suites, built against this codebase's own
`LLMClient` abstraction (see `app.evals.judge_adapter`) rather than either
library's default OpenAI-backed judge - so `make eval` runs deterministically
offline under `LLM_BACKEND=replay` (CI, this environment) and, unmodified,
against a live judge under `LLM_BACKEND=groq` once a human has a real
`GROQ_API_KEY` (same two-backend story as every other LLM call in this app).
"""
