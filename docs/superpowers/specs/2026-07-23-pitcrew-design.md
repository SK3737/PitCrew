# PitCrew - Design Specification

Status: approved (architecture signed off 2026-07-23, revised after design review same day).
Owner: SK.
Goal: turn the existing Vehicle Service Prediction API into a full-stack AI product that reads as senior-level AI/LLM Engineer work on a CV.

Scope of this document: principles and architecture only.
Phase sequencing lives in `plan.md`, so this spec stays accurate even as phases reorder.

## 1. Purpose and success criteria

PitCrew is a fleet maintenance copilot.
It predicts when each vehicle needs service and lets a user ask a multi-agent assistant about any vehicle, its schedule, and maintenance knowledge, with cited answers.

This project exists to demonstrate hireable AI-Engineer skills, not to ship a commercial product.
It succeeds when a reviewer opening the repo can see, without running anything:

- A clean multi-agent architecture with a LangGraph supervisor and typed specialists.
- A production-style RAG pipeline with hybrid retrieval, reranking, and citations.
- Evaluations wired into CI as a regression gate, with scores in the README.
- Observability with linked traces (a screenshot in the README).
- Real auth and RBAC, async Postgres, tests, ADRs, and a live demo URL.

Stated CV signals, chosen deliberately (not incidental scope):

- AI/agent engineering is the primary signal: orchestration, RAG, evals, observability.
- Security awareness is a secondary signal: the auth design (Section 4.2) is kept concrete on purpose.

Hard constraint: no paid LLM API (Anthropic or otherwise) is ever called anywhere in the code, because this is a demo project, not a revenue product.
Live chat completion uses a free-tier third-party inference API (Groq), chosen deliberately because it costs nothing and needs no local GPU, so the hosted demo can be genuinely live rather than replay-only.
Embeddings and reranking run locally on CPU, so RAG never depends on any metered service either.
Tests run against recorded traces (replay) so CI never depends on Groq's uptime or burns its free-tier quota.

## 2. Users, roles, and where the model runs

Four roles, enforced by RBAC:

- admin: full access, manage users and models.
- mechanic: read all vehicles, create service records, run predictions, use the assistant.
- owner: read and manage only their own vehicles.
- demo: read-only, assistant answers from replay.

The assistant runs live on the free Groq API in every environment, local dev and hosted alike, so there is no live-versus-replay split by environment.
The "demo" role still describes the public site's read-only persona; it just means read-only, not "replay-only," since Groq makes a real live assistant free to host.
Replay is a testing concern, not a deployment mode: CI runs the whole suite against `ReplayClient` so tests are deterministic and never touch Groq or its rate limits.
There is no GPU anywhere in this system, hosted or local.

## 3. System shape

Monorepo with two deployables plus shared infra.

```
pitcrew/
  backend/        FastAPI app, agents, RAG, evals
  frontend/       Next.js 16 app
  docs/           spec, ADRs, architecture diagram, case study
  docker-compose.yml   Postgres+pgvector, Ollama, backend, frontend for local dev
```

Data flow for an assistant question:

1. Frontend sends the question over SSE to the backend assistant endpoint.
2. The LangGraph supervisor classifies intent and routes to one or more specialists.
3. A specialist calls tools (predict_service, search_kb, schedule_service) through the pluggable LLMClient.
4. RAG retrieves and reranks context for knowledge questions.
5. The backend streams tokens back; the UI renders the answer, inline citations, and the agent activity trace.
6. Langfuse records the full trace, correlated to the UI by run_id.

## 4. Backend

### 4.1 Persistence

Replace JSON file storage with Postgres.
Async stack: SQLAlchemy 2.0 async, asyncpg, Alembic for migrations.
pgvector extension for embeddings.

Core tables: users, refresh_tokens, vehicles, service_history, predictions, kb_documents, kb_chunks (with vector and tsvector columns), eval_runs.

### 4.2 Auth and RBAC

This subsystem is kept concrete on purpose, as the project's stated security signal.

JWT access token, 15-minute lifetime, sent in the Authorization header.
Refresh token in an HttpOnly, Secure, SameSite cookie, with rotation and reuse detection backed by a server-side jti store.
Password hashing with Argon2id via argon2-cffi.
Do not use passlib or bcrypt, which are unmaintained and silently truncate long passwords.
Authorization is expressed as require_permission(...) dependencies on routes, not scattered checks.

The rotation-plus-reuse-detection logic is hand-written rather than delegated to an auth library, because it is a small, legible, checkable demonstration of the security understanding the CV claims.

### 4.3 Prediction service

Keep the existing 3-tier dispatcher: model v2, then v1, then rules.
Wrap model selection in a small model registry so the active model and its metadata (version, MAE) are explicit and swappable.
Fix the training-data bias: the current synthetic dataset only samples vehicles at the service threshold, so models predict near-zero remaining km and days for fresh inputs.
Regenerate or reweight the dataset so it spans the full life of a service interval, then retrain and record the new MAE.

### 4.4 Agents

Orchestration uses LangGraph; specialists use PydanticAI.

The supervisor is a LangGraph graph that classifies intent and routes to three specialists:

- Diagnostics: predicts next service from history and metadata using the prediction service.
- Scheduling: proposes and, on explicit confirmation, writes a service booking.
- Knowledge: answers maintenance questions from the knowledge base via RAG.

Each specialist is a PydanticAI agent with typed inputs, outputs, and tools.

Decision and tradeoff (resolving the framework tension explicitly):
A hand-written supervisor would be simpler to read, but the project's goal is to read as senior AI-engineer work, and LangGraph is the most sought-after agent-orchestration signal in 2026 hiring.
Using LangGraph for the graph and PydanticAI for typed agents shows framework proficiency where reviewers look for it, while keeping the routing logic inspectable in one graph definition.
The cost is one more framework dependency and its learning curve, accepted deliberately.

Guardrails:

- Scheduling writes require human-in-the-loop confirmation before any state change.
- A max-iteration kill switch bounds agent loops.
- A Groq rate-limit (429) response is caught and surfaced as a friendly "assistant is busy, try again shortly" message, never a crash or a silent retry storm.
- These map to OWASP LLM Top-10, notably LLM06 Excessive Agency.

### 4.5 Pluggable LLMClient

All chat/reasoning calls go through one LLMClient interface, so no agent code knows which backend serves it.
Two implementations:

- GroqClient: live, free-tier, used in every environment (local dev and hosted). Calls Groq's OpenAI-compatible chat completions API with `llama-3.3-70b-versatile`.
- ReplayClient: returns recorded responses from cassettes, keyed by a hash of the request. On a cache miss it fails hard rather than calling out. Used by the test suite (`LLM_BACKEND=replay`) so CI is deterministic and never touches Groq.

Cassettes follow the VCR.py pattern, recorded at temperature 0 with a fixed seed.
`LLM_BACKEND=groq` for live use (dev and hosted); `LLM_BACKEND=replay` for tests.

Embeddings and reranking are not part of this live/replay split: they run locally on CPU (Section 4.6) in every environment, since they are free and light enough to need no API at all.

### 4.6 RAG

Corpus: a curated synthetic maintenance knowledge base, authored as markdown from publicly-known manufacturer service-interval norms.
It covers per-make/model service schedules (oil, filter, brake, coolant intervals) and common maintenance issues, enough to give the Knowledge agent real, citable content without redistributing any copyrighted manual.

Embeddings use a local CPU sentence-transformer (`all-MiniLM-L6-v2`); reranking uses a local CPU cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`). Both run in-process, no API and no GPU.

Hybrid retrieval: pgvector dense ANN search plus Postgres tsvector BM25, fused with Reciprocal Rank Fusion.
Retrieve roughly the top 20, rerank with the cross-encoder to the top 4 to 6.
Chunks carry metadata (source, section, chunk_id) so answers cite sources with inline [n] markers.
On weak retrieval the Knowledge agent refuses rather than inventing an answer.

### 4.7 Evaluations

Evals are the headline signal, not an afterthought.
`make eval` runs two complementary suites, kept separate because they measure different things:

- Ragas (with GroqClient as the judge, free tier) scores retrieval and answer quality: faithfulness, answer relevancy, context precision, context recall.
- DeepEval scores agent trajectory and tool-selection correctness, which Ragas does not cover.

CI runs `make eval` as a regression gate and the README shows current scores.

### 4.8 Observability

Langfuse Cloud (free tier) traces every agent run.
The cloud tier is chosen over self-hosting so no observability service has to be persisted in production, which keeps the infra ceiling intact.
Langfuse is an observability SaaS, not a model, so it does not touch the no-paid-LLM constraint.
A run_id links the UI, the backend logs, and the Langfuse trace.
The README includes an annotated trace screenshot.

### 4.9 Streaming

Server-Sent Events via FastAPI StreamingResponse.
The frontend consumes it through a Next.js Route Handler that returns a ReadableStream, read on the client with fetch and getReader, not EventSource.

### 4.10 Testing

Backend: pytest with httpx AsyncClient for unit and integration tests against the async app, plus a Postgres test database.
Frontend: Playwright for end-to-end tests against a production build (auth flow, dashboard, assistant streaming).
The eval suites (Section 4.7) are a third, separate gate, not a substitute for these.

## 5. Frontend

Next.js 16 App Router, TypeScript, Tailwind, shadcn/ui, server-first.
Visual direction: Midnight Indigo (dark, deep blue-black ground, periwinkle-indigo accent #7C8CFF).
Status colors are reserved for meaning and never reused as the accent: green on-track, amber due-soon, red overdue.

Screens: Dashboard (KPI tiles, predicted-services chart, next-service gauge, vehicles table) and Assistant (streaming chat with inline citations and a live agent activity trace).

Auth lives in a server-only Data Access Layer with a cache()-memoized session check.
proxy.ts / middleware is optimistic redirect only, never the authorization boundary, because of CVE-2025-29927.

## 6. Deployment

- Database: Neon Postgres with pgvector. Chosen because its free tier does not expire and resumes from scale-to-zero in about a second.
- Backend: Render free web service, running `LLM_BACKEND=groq`, so the public demo is genuinely live with no GPU and no paid API. `GROQ_API_KEY` is a Render secret.
- Frontend: Vercel Hobby.
- Observability: Langfuse Cloud free tier (no self-hosted service).
- CI/CD: GitHub Actions. Public repo. Conventional Commits.
- Cold-start mitigation: a scheduled ping keeps the Render backend warm. This targets Render's container cold start, not Neon, whose sub-second resume needs no keep-warm.

## 7. Documentation

README with overview, architecture diagram, live link, eval scores, trace screenshot, and setup.
ADRs for the significant decisions (auth design, LangGraph-plus-PydanticAI agent choice, RAG design, deploy stack, live-versus-replay model strategy).
A short case study describing the problem, the design, and the tradeoffs.

## 8. Explicit non-goals

- No paid LLM API calls, ever.
- No GPU anywhere; live inference is a free third-party API (Groq), not a self-hosted model.
- No full MLOps platform: no Kubernetes, Terraform, MLflow, or microservices. docker-compose plus managed hosts is the ceiling.
- No self-hosted observability stack; Langfuse Cloud free tier only.
- No end-user billing, teams, or multi-tenancy beyond the four roles.
