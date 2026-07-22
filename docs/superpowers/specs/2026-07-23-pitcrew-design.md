# PitCrew - Design Specification

Status: approved (architecture signed off 2026-07-23).
Owner: SK.
Goal: turn the existing Vehicle Service Prediction API into a full-stack AI product that reads as senior-level AI/LLM Engineer work on a CV.

## 1. Purpose and success criteria

PitCrew is a fleet maintenance copilot.
It predicts when each vehicle needs service and lets a user ask a multi-agent assistant about any vehicle, its schedule, and maintenance knowledge, with cited answers.

This project exists to demonstrate hireable AI-Engineer skills, not to ship a commercial product.
It succeeds when a reviewer opening the repo can see, without running anything:

- A clean multi-agent architecture with a supervisor and specialists.
- A production-style RAG pipeline with hybrid retrieval, reranking, and citations.
- Evaluations wired into CI as a regression gate, with scores in the README.
- Observability with linked traces (a screenshot in the README).
- Real auth and RBAC, async Postgres, tests, ADRs, and a live demo URL.

Hard constraint: no paid LLM or third-party model API is ever called anywhere in the code.
Every AI feature runs either on a local free model (Ollama) or on recorded traces (replay).

## 2. Users and roles

Four roles, enforced by RBAC:

- admin: full access, manage users and models.
- mechanic: read all vehicles, create service records, run predictions, use the assistant.
- owner: read and manage only their own vehicles.
- demo: read-only, assistant runs in replay mode. This is the role the public demo uses.

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
2. Supervisor classifies intent and routes to one or more specialists.
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

JWT access token, 15-minute lifetime, sent in the Authorization header.
Refresh token in an HttpOnly, Secure, SameSite cookie, with rotation and reuse detection backed by a server-side jti store.
Password hashing with Argon2id via argon2-cffi.
Do not use passlib or bcrypt, which are unmaintained and silently truncate long passwords.
Authorization is expressed as require_permission(...) dependencies on routes, not scattered checks.

### 4.3 Prediction service

Keep the existing 3-tier dispatcher: model v2, then v1, then rules.
Wrap model selection in a small model registry so the active model and its metadata (version, MAE) are explicit and swappable.
Fix the training-data bias: the current synthetic dataset only samples vehicles at the service threshold, so models predict near-zero remaining km and days for fresh inputs.
Regenerate or reweight the dataset so it spans the full life of a service interval, then retrain and record the new MAE.

### 4.4 Agents

A thin, hand-written supervisor routes to three specialists built on PydanticAI:

- Diagnostics: predicts next service from history and metadata using the prediction service.
- Scheduling: proposes and, on explicit confirmation, writes a service booking.
- Knowledge: answers maintenance questions from the knowledge base via RAG.

The supervisor is deliberately simple code, not a heavy framework, so its routing logic is readable and testable.

Guardrails:

- Scheduling writes require human-in-the-loop confirmation before any state change.
- A max-iteration kill switch bounds agent loops.
- These map to OWASP LLM Top-10, notably LLM06 Excessive Agency.

### 4.5 Pluggable LLMClient

All model access goes through one LLMClient interface, so no agent code knows which backend serves it.
Two implementations:

- OllamaClient: live, local, free. Qwen3-8B (Q4_K_M) for agents, nomic-embed-text for embeddings, bge-reranker-v2-m3 for reranking.
- ReplayClient: returns recorded responses from cassettes, keyed by a hash of the request. On a cache miss it fails hard rather than calling out.

Cassettes follow the VCR.py pattern, recorded at temperature 0 with a fixed seed.
Two layers: hash-keyed cassettes for CI determinism, and a handful of curated golden-scenario cassettes for the public demo.
DEMO_MODE selects ReplayClient; local dev uses OllamaClient.

### 4.6 RAG

Hybrid retrieval: pgvector dense ANN search plus Postgres tsvector BM25, fused with Reciprocal Rank Fusion.
Retrieve roughly the top 20, rerank with the cross-encoder to the top 4 to 6.
Chunks carry metadata (source, section, chunk_id) so answers cite sources with inline [n] markers.
On weak retrieval the Knowledge agent refuses rather than inventing an answer.

### 4.7 Evaluations

Evals are the headline signal, not an afterthought.
`make eval` runs Ragas metrics (faithfulness, answer relevancy, context precision, context recall) with a local Ollama judge, plus DeepEval trajectory tests for the agents.
CI runs `make eval` as a regression gate and the README shows current scores.

### 4.8 Observability

Langfuse (self-hosted, MIT) traces every agent run.
A run_id links the UI, the backend logs, and the Langfuse trace.
The README includes an annotated trace screenshot.

### 4.9 Streaming

Server-Sent Events via FastAPI StreamingResponse.
The frontend consumes it through a Next.js Route Handler that returns a ReadableStream, read on the client with fetch and getReader, not EventSource.

## 5. Frontend

Next.js 16 App Router, TypeScript, Tailwind, shadcn/ui, server-first.
Visual direction: Midnight Indigo (dark, deep blue-black ground, periwinkle-indigo accent #7C8CFF).
Status colors are reserved for meaning and never reused as the accent: green on-track, amber due-soon, red overdue.

Screens: Dashboard (KPI tiles, predicted-services chart, next-service gauge, vehicles table) and Assistant (streaming chat with inline citations and a live agent activity trace).

Auth lives in a server-only Data Access Layer with a cache()-memoized session check.
proxy.ts / middleware is optimistic redirect only, never the authorization boundary, because of CVE-2025-29927.

## 6. Deployment

- Database: Neon Postgres with pgvector. Chosen because its free tier does not expire and resumes from scale-to-zero in about a second.
- Backend: Render free web service, running in DEMO_MODE (ReplayClient), so the public demo needs no GPU and no paid API.
- Frontend: Vercel Hobby.
- CI/CD: GitHub Actions. Public repo. Conventional Commits.
- A keep-warm ping hits a DB-backed endpoint to reduce cold starts.

## 7. Documentation

README with overview, architecture diagram, live link, eval scores, trace screenshot, and setup.
ADRs for the significant decisions (auth design, agent framework choice, RAG design, deploy stack).
A short case study describing the problem, the design, and the tradeoffs.

## 8. Explicit non-goals

- No paid LLM API calls, ever.
- No full MLOps platform: no Kubernetes, Terraform, MLflow, or microservices. docker-compose plus managed hosts is the ceiling.
- No end-user billing, teams, or multi-tenancy beyond the four roles.
- LangGraph is an optional stretch only, not part of the core.

## 9. Build order

Phases, each a shippable slice with tests:

0. Repo hygiene and monorepo layout (remove committed virtualenv, set up backend/ and frontend/, docker-compose).
1. Postgres migration (schema, async stack, Alembic, move data off JSON).
2. Auth and RBAC.
3. Data-bias fix and model registry.
4. Next.js scaffold and Dashboard.
5. Agent core (supervisor, specialists, LLMClient, guardrails).
6. RAG (ingest, hybrid retrieval, rerank, citations).
7. Replay and DEMO_MODE (cassettes, golden scenarios).
8. Assistant UI (SSE streaming, citations, trace panel).
9. CI/CD and deploy (GitHub Actions, Neon, Render, Vercel, evals in CI).
10. Docs, ADRs, and case study.
