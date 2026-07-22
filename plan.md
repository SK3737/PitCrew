# PitCrew Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the existing Vehicle Service Prediction API into PitCrew, a full-stack fleet-maintenance copilot with a LangGraph multi-agent assistant, RAG, auth/RBAC, a Next.js dashboard, evals-in-CI, and a free live demo.

**Architecture:** Monorepo (`backend/` FastAPI + `frontend/` Next.js). Async Postgres+pgvector. LangGraph supervisor routing to PydanticAI specialists (Diagnostics, Scheduling, Knowledge/RAG). All chat/reasoning goes through a pluggable `LLMClient` with a `GroqClient` backend (free-tier, live in every environment) and a `ReplayClient` backend (recorded cassettes, used by the test suite so CI is deterministic) so no paid LLM API is ever called. Embeddings and reranking run locally on CPU (no API, no GPU). Langfuse Cloud for tracing.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, asyncpg, Alembic, pgvector, argon2-cffi, PyJWT, LangGraph, PydanticAI, Groq (`llama-3.3-70b-versatile`, free tier), sentence-transformers (`all-MiniLM-L6-v2`) for embeddings, cross-encoder (`ms-marco-MiniLM-L-6-v2`) for rerank, Ragas, DeepEval, Langfuse; Next.js 16 + TypeScript + Tailwind + shadcn/ui; pytest + httpx, Playwright; Neon + Render + Vercel; GitHub Actions.

**Authoritative spec:** `docs/superpowers/specs/2026-07-23-pitcrew-design.md`. If this plan and the spec disagree, the spec wins - stop and reconcile.

---

## How to use this plan (read first)

- Execute phases **in order**; each phase is a shippable, tested slice. Do not start a phase until the prior phase's acceptance gate passes.
- Within a phase, follow **strict TDD**: write the failing test, run it (confirm it fails), write minimal code, run it (confirm it passes), commit. One logical change per commit.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`). No em dashes anywhere. Never add an agent as co-author.
- **Never** call a paid LLM API. All live chat/reasoning goes through `GroqClient` (free tier, used in dev and hosted alike); the test suite runs on `ReplayClient`. A replay cache miss must raise, never fall back to a network call.
- **Do not push to origin directly.** Use `/no-mistakes` (or `git push no-mistakes`) when a phase is ready to ship.
- When a phase says "verify," actually run the command and read the output before ticking the box. Evidence before claims.
- If a step is blocked or reality differs from the plan, stop and report; do not invent a workaround that contradicts the spec.

## Global conventions

- **Python:** 3.11+, `ruff` for lint/format, type hints on all public functions, `pydantic` v2 models for all API and tool schemas.
- **Backend layout (inside `backend/`):**
  ```
  app/
    main.py               FastAPI app + lifespan
    config.py             Settings (pydantic-settings), reads env
    db/                   engine, session, base
    models/               SQLAlchemy ORM models
    schemas/              pydantic request/response models
    repositories/         data-access functions (no business logic in routers)
    routers/              thin HTTP layer
    services/             business logic (predictor, registry)
    auth/                 hashing, tokens, deps, rbac
    agents/               llm_client, embeddings, supervisor (LangGraph), specialists (PydanticAI), tools
    rag/                  ingest, retrieval, rerank
    evals/                ragas + deepeval suites
    observability/        langfuse setup, run_id
  alembic/                migrations
  tests/                  mirrors app/ layout
  ```
- **Env vars (`backend/.env.example` must list all):** `DATABASE_URL`, `JWT_SECRET`, `ACCESS_TOKEN_MINUTES=15`, `REFRESH_TOKEN_DAYS=14`, `LLM_BACKEND=groq|replay`, `GROQ_API_KEY`, `GROQ_MODEL=llama-3.3-70b-versatile`, `EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2`, `RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `CASSETTE_DIR`.
- **Test DB:** a separate Postgres database; tests never touch dev data. Use a `pytest` fixture that creates a transactional session rolled back per test.
- **Frontend layout (inside `frontend/`):** Next.js App Router, `app/`, `components/ui/` (shadcn), `lib/` (data-access layer, api client, session), `app/api/` route handlers (BFF that forwards cookies to FastAPI).

---

## Phase 0: Repo hygiene and monorepo layout

**Goal:** A clean monorepo skeleton with the committed virtualenv removed and local Postgres+pgvector running via docker-compose. No GPU or model-server container is needed anywhere in this project.

**Dependencies:** none.

**Files:**
- Create: `.gitignore`, `docker-compose.yml`, `backend/README.md`, `frontend/README.md`, `Makefile`
- Move: existing `app/`, `models/`, `storage/`, `data/`, `services/` under `backend/` (preserve history where possible)
- Remove from tracking: `myenv/` (committed virtualenv, 5500+ files)

**Tasks:**

- [ ] **0.1 Snapshot current state.** Run `git status` and `git log --oneline -5`; confirm clean tree before restructuring.
- [ ] **0.2 Add `.gitignore`.** Include `myenv/`, `.venv/`, `__pycache__/`, `*.pyc`, `.env`, `node_modules/`, `.next/`, `frontend/out/`, `*.pkl` only if regenerated (keep existing model pkls tracked for now), `.pytest_cache/`, `cassettes/*.local`.
- [ ] **0.3 Untrack the virtualenv.** Run `git rm -r --cached myenv` then commit `chore: remove committed virtualenv from tracking`.
- [ ] **0.4 Create monorepo dirs.** `mkdir -p backend frontend`. Move backend source: `git mv app backend/app`, `git mv models backend/models`, `git mv storage backend/storage`, `git mv services backend/services` (if present at root), `git mv data backend/data`. Update imports if any break.
- [ ] **0.5 Add `docker-compose.yml`** with a `db` service (image `pgvector/pgvector:pg16`, env POSTGRES_USER/PASSWORD/DB, named volume, port 5432) and placeholders for `backend`/`frontend` (build contexts, `depends_on: db`).
- [ ] **0.6 Add `Makefile`** targets (stubs that will fill in over later phases): `dev`, `test`, `eval`, `migrate`, `seed`, `lint`, `fmt`. For now `lint` runs `ruff check backend`, `fmt` runs `ruff format backend`.
- [ ] **0.7 Verify.** Run `docker compose up -d db`; confirm the container is healthy (`docker compose ps`). Run `docker compose exec db psql -U <user> -d <db> -c "CREATE EXTENSION IF NOT EXISTS vector;"` and confirm no error.
- [ ] **0.8 Commit** `chore: establish monorepo layout and local infra`.

**Acceptance gate:** `myenv/` no longer tracked (`git ls-files | grep myenv` returns nothing); `docker compose ps` shows db running; pgvector extension creatable.

---

## Phase 1: Postgres migration (async stack)

**Goal:** All persistence on Postgres via async SQLAlchemy + Alembic; existing JSON/pkl data flow replaced; existing predict endpoints still work against the DB.

**Dependencies:** Phase 0.

**Files:**
- Create: `backend/app/config.py`, `backend/app/db/base.py`, `backend/app/db/session.py`, `backend/app/models/{user,vehicle,service_history,prediction}.py`, `backend/app/repositories/{vehicles,service_history}.py`, `backend/alembic.ini`, `backend/alembic/env.py`, first migration
- Create: `backend/tests/conftest.py`, `backend/tests/test_vehicles_repo.py`
- Modify: `backend/app/main.py`, `backend/app/routers/vehicles.py`, `backend/app/routers/predict.py`

**Tasks:**

- [ ] **1.1 Install deps.** Add to `backend/requirements.txt`: `sqlalchemy[asyncio]>=2.0`, `asyncpg`, `alembic`, `pydantic-settings`, `pgvector`. Install.
- [ ] **1.2 Write `config.py`.** `Settings(BaseSettings)` reading env from Global-conventions list. Provide `settings = Settings()`.
- [ ] **1.3 Write `db/base.py` + `db/session.py`.** Async engine from `settings.DATABASE_URL` (asyncpg URL), `async_sessionmaker`, `DeclarativeBase` subclass `Base`, and a `get_session()` FastAPI dependency yielding an `AsyncSession`.
- [ ] **1.4 TDD the Vehicle model + repo.** Write `tests/test_vehicles_repo.py::test_create_and_get_vehicle` first (create a vehicle, fetch by id, assert fields). Run - expect fail (no model). Implement `models/vehicle.py` (`id`, `make`, `model`, `year`, `fuel_type`, `registered_at`) and `repositories/vehicles.py` (`create`, `get`, `list`). Run - expect pass. Commit `feat: add vehicle model and repository`.
- [ ] **1.5 Add remaining models.** `service_history` (vehicle_id FK, service_type, serviced_at, odo_km), `prediction` (vehicle_id FK, model_version, days_left, km_left, created_at), `user` (stub: id, email, hashed_password, role) - full auth fields land in Phase 2. Add repos for service_history.
- [ ] **1.6 Wire Alembic (async).** Configure `alembic/env.py` for async engine; autogenerate initial migration; run `alembic upgrade head` against the compose DB. Verify tables exist via `psql \dt`.
- [ ] **1.7 Migrate existing data.** Write `backend/scripts/import_json.py` that reads the current JSON store and inserts vehicles + history. Run it; verify row counts.
- [ ] **1.8 Repoint routers.** Update `routers/vehicles.py` and `routers/predict.py` to read/write through repositories + `get_session`, not the JSON store. Keep the 3-tier predictor call intact.
- [ ] **1.9 Integration test.** `tests/test_predict_route.py`: spin app with httpx AsyncClient, POST a known vehicle, assert a prediction returns and a `prediction` row is written.
- [ ] **1.10 Verify + commit.** `make test` green. Commit `feat: move persistence to async Postgres`.

**Acceptance gate:** `pytest backend/tests -q` passes; `/predict` and `/vehicles/{id}/*` work against Postgres; Alembic `upgrade head` clean from empty DB.

---

## Phase 2: Auth and RBAC

**Goal:** JWT access + rotating refresh (reuse-detected) auth with Argon2id hashing and `require_permission` route guards for the four roles.

**Dependencies:** Phase 1.

**Files:**
- Create: `backend/app/auth/{hashing,tokens,deps,rbac}.py`, `backend/app/schemas/auth.py`, `backend/app/routers/auth.py`, `backend/app/models/refresh_token.py`
- Create: `backend/tests/test_auth_*.py`
- Modify: `backend/app/models/user.py`, `backend/app/main.py`

**Tasks:**

- [ ] **2.1 Deps.** Add `argon2-cffi`, `pyjwt`. Install.
- [ ] **2.2 TDD hashing.** `test_hashing.py::test_hash_and_verify` (hash a password, verify true; verify wrong false). Implement `auth/hashing.py` using `argon2.PasswordHasher` (`hash`, `verify` wrapping `VerifyMismatchError`). Do NOT use passlib/bcrypt.
- [ ] **2.3 TDD access tokens.** `test_tokens.py::test_access_token_roundtrip` (encode with sub+role+jti+exp, decode returns claims; expired token raises). Implement `auth/tokens.py` (`create_access_token`, `decode_token`) with PyJWT HS256, 15-min exp from settings.
- [ ] **2.4 Refresh model + rotation.** Implement `models/refresh_token.py` (`jti`, `user_id`, `issued_at`, `expires_at`, `revoked`, `replaced_by`). TDD `test_refresh_rotation.py`: issuing a new refresh revokes the old and links `replaced_by`; presenting a revoked (already-rotated) token triggers reuse detection -> revoke the whole chain for that user and reject. Implement in `auth/tokens.py` + a repo.
- [ ] **2.5 Auth routes.** `routers/auth.py`: `POST /auth/register`, `POST /auth/login` (sets refresh cookie HttpOnly+Secure+SameSite=strict, returns access token in body), `POST /auth/refresh` (rotates), `POST /auth/logout` (revokes). Schemas in `schemas/auth.py`.
- [ ] **2.6 Current-user dep + RBAC.** `auth/deps.py::get_current_user` (reads Authorization bearer, decodes, loads user). `auth/rbac.py::require_permission(*perms)` returning a dependency that 403s if the user's role lacks the permission. Define a role->permissions map (admin: all; mechanic: read_vehicles, write_service, run_predict, use_assistant; owner: read_own_vehicles, manage_own; demo: read_only, use_assistant_replay).
- [ ] **2.7 Guard existing routes.** Apply `require_permission` to vehicle/predict routes. Add an owner-scoping check so `owner` only sees their vehicles.
- [ ] **2.8 E2E auth test.** `test_auth_flow.py`: register -> login -> call a protected route with the access token (200) and without (401) and as wrong role (403) -> refresh -> reuse old refresh (rejected).
- [ ] **2.9 Verify + commit.** `make test` green. Commit `feat: add JWT auth with rotating refresh tokens and RBAC`.

**Acceptance gate:** full auth flow test passes including reuse detection and 403-on-wrong-role; passwords hashed with Argon2id; refresh only ever in HttpOnly cookie (never in a response body).

---

## Phase 3: Data-bias fix and model registry

**Goal:** Retrain on a corrected dataset that spans the full service interval (not just the threshold), behind an explicit model registry that reports the active model and its MAE.

**Dependencies:** Phase 1.

**Files:**
- Create: `backend/app/services/model_registry.py`, `backend/scripts/generate_dataset.py`, `backend/scripts/train.py`, `backend/tests/test_model_registry.py`, `backend/tests/test_dataset_distribution.py`
- Modify: `backend/app/services/predictor.py`

**Tasks:**

- [ ] **3.1 Characterize the bias (test first).** `test_dataset_distribution.py::test_targets_span_interval`: load the training set, assert `days_left`/`km_left` targets are NOT clustered near zero (e.g. assert the 25th-75th percentile spread exceeds a threshold and mean is meaningfully above 0). Run against current data - expect FAIL (documents the bug).
- [ ] **3.2 Regenerate dataset.** `scripts/generate_dataset.py`: synthesize vehicles sampled uniformly across the interval life (0..interval), so targets range from "just serviced" to "overdue." Re-run 3.1 - expect PASS.
- [ ] **3.3 Retrain.** `scripts/train.py`: train v2 on the corrected data, print MAE, write `service_predictor_v2.pkl`. Record MAE.
- [ ] **3.4 TDD registry.** `test_model_registry.py`: registry exposes `active()` -> (name, version, mae, predict_fn); loads v2, falls back to v1, then rules if a file is missing. Implement `model_registry.py`. Refactor `predictor.py` to get its tiers from the registry.
- [ ] **3.5 Sanity check predictions.** Add `test_predictor.py::test_fresh_vehicle_not_zero`: a brand-new vehicle predicts a non-trivial remaining interval (guards the original bug at the API level).
- [ ] **3.6 Verify + commit.** `make test` green. Commit `fix: correct training-data bias and add model registry`.

**Acceptance gate:** dataset distribution test passes; a fresh vehicle no longer predicts ~0 days/km; registry reports active model + MAE.

---

## Phase 4: Next.js scaffold and Dashboard

**Goal:** The Midnight Indigo dashboard rendering real data from the backend, behind login, server-first.

**Dependencies:** Phases 1-3 (data + auth to read).

**Files:**
- Create: `frontend/` Next.js app; `frontend/lib/{api,session,dal}.ts`; `frontend/app/(auth)/login/page.tsx`; `frontend/app/dashboard/page.tsx`; dashboard components under `frontend/components/`; `frontend/app/api/[...]/route.ts` BFF handlers
- Design tokens: port from `scratchpad/pitcrew-indigo.html` (data-dir="a" token block)

**Tasks:**

- [ ] **4.1 Scaffold.** `npx create-next-app@latest frontend --ts --tailwind --app --eslint`. Init shadcn/ui. Commit `chore: scaffold Next.js frontend`.
- [ ] **4.2 Port Midnight Indigo tokens.** Copy the `:root[data-dir="a"]` CSS custom properties from `scratchpad/pitcrew-indigo.html` into `frontend/app/globals.css` as the theme (bg #0A0B12, surface #12141C, accent #7C8CFF, ink/muted/faint, status good/warn/crit). Set dark as the committed theme.
- [ ] **4.3 Data Access Layer.** `lib/session.ts`: a `cache()`-memoized `verifySession()` that reads the access token (from an HttpOnly cookie set by the BFF) and returns the user or redirects. `lib/dal.ts`: server-only functions (`getVehicles`, `getKpis`) that call the backend with the forwarded token. Middleware (`proxy.ts`) is optimistic redirect ONLY - never the auth boundary (CVE-2025-29927).
- [ ] **4.4 BFF route handlers.** `app/api/.../route.ts`: forward requests to FastAPI, attach the cookie, stream where needed. Login handler exchanges credentials, stores the refresh cookie, keeps the access token server-side.
- [ ] **4.5 Login page + dashboard.** Build `login/page.tsx` (server action posts to BFF). Build `dashboard/page.tsx` as a server component pulling from the DAL: KPI tiles, predicted-services chart (follow the `dataviz` skill: one hue, reserved status colors, direct-labeled endpoint), next-service gauge, vehicles table with status pills.
- [ ] **4.6 Playwright e2e.** `frontend/e2e/dashboard.spec.ts`: login -> dashboard renders KPIs and the vehicles table with real seeded data. Run against a production build.
- [ ] **4.7 Verify + commit.** `npm run build` clean; Playwright green. Commit `feat: add Midnight Indigo dashboard behind auth`.

**Acceptance gate:** production build passes; logging in shows a dashboard populated from Postgres; unauthenticated access redirects; authorization is enforced server-side in the DAL, not in middleware.

---

## Phase 5: Agent core (LangGraph supervisor + PydanticAI specialists + LLMClient)

**Goal:** A working supervisor graph that routes to Diagnostics/Scheduling/Knowledge specialists, all chat/reasoning behind `LLMClient`, with guardrails - running live on the free Groq API in every environment.

**Dependencies:** Phases 1-3 (tools need the DB + predictor). RAG (Phase 6) fills in the Knowledge specialist's retrieval; here it can return a stub "no KB yet."

**Files:**
- Create: `backend/app/agents/llm_client.py` (interface + `GroqClient` + `ReplayClient`), `backend/app/agents/tools.py`, `backend/app/agents/specialists/{diagnostics,scheduling,knowledge}.py`, `backend/app/agents/supervisor.py` (LangGraph), `backend/app/agents/guardrails.py`, `backend/app/routers/assistant.py`
- Create: `backend/tests/test_llm_client.py`, `backend/tests/test_supervisor_routing.py`, `backend/tests/test_guardrails.py`

**Tasks:**

- [ ] **5.1 Deps.** Add `langgraph`, `pydantic-ai`, `groq`, `langfuse`. Install. Sign up for a free Groq API key at console.groq.com and set `GROQ_API_KEY` in `backend/.env` (never commit it).
- [ ] **5.2 TDD the LLMClient interface.** `test_llm_client.py`: define an abstract `LLMClient` with `complete(messages, tools, **params)`. Test `ReplayClient` returns a recorded response for a known request hash and RAISES `CassetteMiss` on an unknown one (never a network call). Implement the interface + `ReplayClient` (hash of model+messages+tools+temp+seed -> cassette file). Implement `GroqClient` calling Groq's chat completions API (`GROQ_MODEL`, default `llama-3.3-70b-versatile`) via the `groq` SDK, catching a 429 response and raising a typed `RateLimited` error rather than retrying silently.
- [ ] **5.3 Tools.** `tools.py`: `predict_service(vehicle_id)` (calls the registry/predictor), `search_kb(query)` (Phase 6 fills the body; stub returns `[]`), `schedule_service(vehicle_id, date, confirmed: bool)` (writes only if `confirmed`). Each tool is a typed pydantic function usable by PydanticAI.
- [ ] **5.4 Specialists.** Each specialist is a PydanticAI agent constructed with the injected `LLMClient` and its allowed tools. Diagnostics -> predict_service; Scheduling -> schedule_service; Knowledge -> search_kb. Typed output models.
- [ ] **5.5 Supervisor graph.** `supervisor.py`: a LangGraph `StateGraph` whose entry node classifies intent (diagnostics/scheduling/knowledge) and routes to the matching specialist node, then a compose node produces the final answer with citations. State carries the question, route, tool results, and `run_id`.
- [ ] **5.6 TDD routing.** `test_supervisor_routing.py` (using `ReplayClient` cassettes so it is deterministic and free): a diagnostics-style question routes to Diagnostics and calls `predict_service`; a knowledge question routes to Knowledge. Assert on the recorded trajectory.
- [ ] **5.7 Guardrails.** `guardrails.py`: (a) scheduling writes require `confirmed=True` - `test_guardrails.py::test_schedule_requires_confirmation` asserts an unconfirmed schedule does NOT write and instead returns a confirmation prompt; (b) a max-iteration counter aborts runaway loops; (c) `test_guardrails.py::test_rate_limit_is_friendly` asserts a `RateLimited` error from `GroqClient` is caught and turned into a friendly "assistant is busy, try again shortly" response, not a 500. Wire into the graph.
- [ ] **5.8 Assistant endpoint (non-streaming first).** `routers/assistant.py::POST /assistant/ask` runs the graph and returns the answer + trajectory + run_id. Guard with `require_permission(use_assistant)`.
- [ ] **5.9 Verify + commit.** `make test` green (all agent tests run on ReplayClient, no network). Commit `feat: add LangGraph supervisor with PydanticAI specialists behind LLMClient`.

**Acceptance gate:** routing + guardrail tests pass deterministically on ReplayClient; scheduling never writes without confirmation; a rate-limit response degrades gracefully; switching `LLM_BACKEND=groq` runs the same graph live, in dev or hosted, with only `GROQ_API_KEY` set.

---

## Phase 6: RAG (ingest, hybrid retrieval, rerank, citations)

**Goal:** The Knowledge specialist answers from a real synthetic KB with hybrid retrieval + rerank + inline citations + refusal on weak retrieval.

**Dependencies:** Phase 5 (Knowledge specialist), Phase 1 (pgvector tables).

**Files:**
- Create: `backend/app/agents/embeddings.py` (local embed + rerank helpers), `backend/app/rag/{ingest,retrieval,rerank}.py`, `backend/data/kb/*.md` (the corpus), `backend/scripts/ingest_kb.py`, `backend/tests/test_retrieval.py`, `backend/tests/test_knowledge_agent.py`
- Modify: `backend/app/agents/tools.py` (`search_kb` body), `backend/app/models` (kb_documents, kb_chunks if not already added in Phase 1)

**Tasks:**

- [ ] **6.0 Embeddings/rerank deps.** Add `sentence-transformers`. Install. `agents/embeddings.py::embed_texts(texts) -> list[list[float]]` loads `EMBED_MODEL` (`sentence-transformers/all-MiniLM-L6-v2`) once at module load and encodes on CPU; `rerank(query, candidates) -> list[(candidate, score)]` loads `RERANK_MODEL` (`cross-encoder/ms-marco-MiniLM-L-6-v2`) and scores query/candidate pairs. Both run locally in every environment - no API, no GPU, no live/replay split.
- [ ] **6.1 Author the corpus.** Write `data/kb/*.md`: per-make/model service schedules (oil/filter/brake/coolant intervals) and common issues, from publicly-known service-interval norms. No copyrighted manual text. Each file has front-matter (source title, section).
- [ ] **6.2 Chunk + embed ingest.** `rag/ingest.py`: structure-aware chunking (by markdown section), embed each chunk via `embeddings.embed_texts`, store vector + tsvector + metadata in `kb_chunks`. `scripts/ingest_kb.py` runs it. Verify row counts.
- [ ] **6.3 TDD hybrid retrieval.** `test_retrieval.py::test_hybrid_finds_known_fact`: for a query with a known answer in the corpus, hybrid retrieval (pgvector cosine + tsvector ts_rank, fused by RRF) returns the right chunk in the top-k. Implement `rag/retrieval.py`.
- [ ] **6.4 Rerank.** `rag/rerank.py` wraps `embeddings.rerank` to take the top ~20 fused results down to top 4-6. Test that rerank improves the position of the gold chunk vs raw fusion on a fixture query.
- [ ] **6.5 Wire `search_kb` + citations.** Fill `tools.py::search_kb` to return reranked chunks with `{source, section, chunk_id, text}`. The Knowledge specialist composes an answer with inline `[n]` markers mapped to a `sources[]` list.
- [ ] **6.6 Refusal on weak retrieval.** `test_knowledge_agent.py::test_refuses_when_no_context`: a question with no supporting chunk (retrieval scores below threshold) returns an explicit refusal, not a fabricated answer.
- [ ] **6.7 Verify + commit.** `make test` green. Commit `feat: add hybrid RAG with rerank, citations, and refusal`.

**Acceptance gate:** known-fact retrieval passes; answers carry inline citations tied to real chunks; low-confidence queries refuse.

---

## Phase 7: Replay mode for CI (cassettes)

**Goal:** The whole assistant test suite runs deterministically with zero network calls under `LLM_BACKEND=replay`, so CI is fast, free, and never depends on Groq's uptime or rate limits. (The public site itself runs live via Groq - see Phase 9 - this phase is a testing concern only.)

**Dependencies:** Phases 5-6.

**Files:**
- Create: `backend/cassettes/` (hash-keyed test fixtures), `backend/cassettes/golden/*.json` (curated end-to-end scenarios), `backend/scripts/record_cassettes.py`, `backend/tests/test_replay_mode.py`
- Modify: `backend/app/agents/llm_client.py` (record hook)

**Tasks:**

- [ ] **7.1 Record hook.** Add a record mode to `GroqClient` (temp 0, fixed seed) that writes each request/response to a cassette keyed by the request hash. `scripts/record_cassettes.py` runs the test suite's prompts against live Groq once to populate the CI cassettes.
- [ ] **7.2 Cover the test scenarios.** Ensure the routing tests (Phase 5) and retrieval/knowledge tests (Phase 6) all have recorded cassettes, plus a handful of curated end-to-end "golden scenarios" (e.g. a diagnostics question and a knowledge question) recorded into `cassettes/golden/` - these are the deterministic conversations the frontend e2e (Phase 8) and DeepEval (Phase 9) run against.
- [ ] **7.3 TDD replay mode.** `test_replay_mode.py`: with `LLM_BACKEND=replay`, each recorded scenario replays byte-for-byte and any off-script prompt raises `CassetteMiss` (proving no silent network fallback).
- [ ] **7.4 Verify + commit.** `make test` green with `LLM_BACKEND=replay`. Commit `feat: add deterministic replay mode for CI`.

**Acceptance gate:** full assistant suite passes in replay with no network; recorded scenarios reproduce exactly; cache miss raises.

---

## Phase 8: Assistant UI (SSE streaming, citations, trace panel)

**Goal:** The Midnight Indigo assistant screen: streaming chat with inline citations and a live agent-activity trace.

**Dependencies:** Phases 4, 5-7.

**Files:**
- Create: `frontend/app/assistant/page.tsx`, `frontend/components/{Chat,Sources,AgentTrace}.tsx`, `frontend/app/api/assistant/route.ts` (SSE proxy), `frontend/e2e/assistant.spec.ts`
- Modify: `backend/app/routers/assistant.py` (add SSE streaming endpoint)

**Tasks:**

- [ ] **8.1 Backend SSE.** Add `POST /assistant/stream` returning `StreamingResponse` (text/event-stream) that emits tokens + trajectory events + a final sources payload, tagged with run_id.
- [ ] **8.2 BFF SSE proxy.** `app/api/assistant/route.ts`: a Route Handler returning a `ReadableStream` that forwards the backend SSE (attaching the auth cookie). Client reads via `fetch` + `getReader` (NOT EventSource).
- [ ] **8.3 Chat UI.** Build `Chat.tsx` (thread, streaming bubbles), `Sources.tsx` (inline `[n]` -> source cards), `AgentTrace.tsx` (supervisor -> specialist steps with timings, matching the preview). Use the ported tokens.
- [ ] **8.4 Playwright e2e.** `assistant.spec.ts` (backend in replay mode): ask a golden question -> answer streams in, citations render, trace shows Supervisor -> specialist steps.
- [ ] **8.5 Verify + commit.** Build clean; Playwright green. Commit `feat: add streaming assistant UI with citations and agent trace`.

**Acceptance gate:** a golden question streams a cited answer with a visible agent trace; frontend uses fetch+getReader streaming; e2e passes against a production build in replay mode.

---

## Phase 9: CI/CD, deploy, and evals-in-CI

**Goal:** Public deploy (Neon + Render replay + Vercel), GitHub Actions running tests + lint + `make eval` as a gate, live URL.

**Dependencies:** Phases 1-8.

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`, `backend/app/evals/{ragas_suite,deepeval_suite}.py`, `render.yaml`, `frontend/vercel.json`, `backend/app/observability/langfuse.py`
- Modify: `Makefile` (`eval` target)

**Tasks:**

- [ ] **9.1 Ragas suite.** `evals/ragas_suite.py`: over a fixed eval set of KB questions, compute faithfulness, answer relevancy, context precision/recall using `GroqClient` as the judge (free tier). Print + write scores to `eval_runs`.
- [ ] **9.2 DeepEval suite.** `evals/deepeval_suite.py`: trajectory/tool-selection tests over the golden scenarios (assert the supervisor picks the right specialist and tool). `make eval` runs both.
- [ ] **9.3 Langfuse.** `observability/langfuse.py`: init the Langfuse Cloud client from env; decorate the graph run so each assistant call emits a trace tagged with run_id. Confirm a trace appears in the Langfuse dashboard; capture the screenshot for the README.
- [ ] **9.4 CI workflow.** `ci.yml`: on PR - set up Postgres+pgvector service, run `ruff`, `pytest` (backend, replay mode), `npm run build` + Playwright (frontend), then `make eval` (replay + local judge) as a required gate. Fail the build if eval scores drop below thresholds.
- [ ] **9.5 Deploy.** Provision Neon (run migrations + seed + ingest KB against it). `render.yaml` deploys the backend with `LLM_BACKEND=groq`, `GROQ_API_KEY` (Render secret), and Langfuse env, so the public demo runs the assistant live for real. Deploy the frontend to Vercel pointing at the Render API. Add a scheduled keep-warm ping to a Render endpoint (targets Render cold start, not Neon).
- [ ] **9.6 Verify + commit.** CI green on a PR; live URL loads the dashboard and answers a live assistant question. Commit `feat: add CI with eval gate and deploy config`.

**Acceptance gate:** PR CI runs tests + build + e2e + eval gate (all in replay, no network); public URL serves the dashboard and a live, real assistant conversation via Groq; a Langfuse trace is captured.

---

## Phase 10: Docs, ADRs, and case study

**Goal:** The repo reads as senior work on open: README, architecture diagram, ADRs, eval scores, trace screenshot, case study.

**Dependencies:** Phases 0-9.

**Files:**
- Create/Modify: `README.md`, `docs/architecture.md` (+ diagram), `docs/adr/000{1..5}-*.md`, `docs/case-study.md`
- Modify: retire the old "changes"/"Delete" commit hygiene going forward (already handled by Conventional Commits).

**Tasks:**

- [ ] **10.1 README.** Overview, architecture diagram, live link, eval scores table, annotated Langfuse trace screenshot, local-dev quickstart (docker-compose + a free Groq API key, no GPU needed), and the no-paid-API note.
- [ ] **10.2 ADRs.** One each for: Argon2id + rotating refresh auth; LangGraph + PydanticAI agent choice (with the tradeoff from the spec); hybrid RAG design; deploy stack (Neon/Render/Vercel); free-tier Groq + local embeddings/rerank strategy (with the rate-limit tradeoff). Use a short standard ADR template (context, decision, consequences).
- [ ] **10.3 Architecture doc + diagram.** `docs/architecture.md` with the data-flow diagram (mermaid) from the spec.
- [ ] **10.4 Case study.** `docs/case-study.md`: problem, design, tradeoffs, what you'd do next.
- [ ] **10.5 Verify + commit.** Links resolve, scores match the latest eval run. Commit `docs: add README, ADRs, architecture, and case study`.

**Acceptance gate:** a reviewer can understand the system, see eval scores and a trace, and reach the live demo, all from the README.

---

## Final ship

- [ ] Run the full suite once more (`make test`, `make eval`, frontend build + Playwright) and confirm green.
- [ ] Ship via `/no-mistakes` (or `git push no-mistakes`) - do not push to origin directly.
- [ ] Confirm the live URL and the CI badge are green in the README.

## Self-review notes (traceability to spec)

- Spec 2 (roles + live everywhere via Groq) -> Phase 2 (roles), Phase 5 (GroqClient live), Phase 7 (ReplayClient for CI only), Phase 9 (hosted live via Groq). No GPU anywhere: enforced by dropping Ollama in Phase 0 and deploying `LLM_BACKEND=groq` in 9.5.
- Spec 4.2 (auth) -> Phase 2. 4.3 (registry + bias) -> Phase 3. 4.4 (LangGraph+PydanticAI+guardrails incl. rate-limit handling) -> Phase 5. 4.5 (LLMClient: GroqClient+ReplayClient) -> Phase 5. 4.6 (RAG corpus + local embed/rerank + hybrid + refusal) -> Phase 6. 4.7 (Ragas + DeepEval) -> Phase 9. 4.8 (Langfuse Cloud) -> Phase 9. 4.9 (SSE) -> Phase 8. 4.10 (pytest/httpx + Playwright) -> every phase's tests.
- Spec 5 (Midnight Indigo frontend, DAL, CVE) -> Phases 4, 8. Spec 6 (deploy) -> Phase 9. Spec 7 (docs) -> Phase 10. Spec 8 (non-goals) -> honored throughout (no k8s/self-host observability/GPU).
