.PHONY: dev test eval migrate seed lint fmt

# Bring up local infra + backend for development.
# Filled in fully once backend/app grows a real entrypoint (later phases).
dev:
	docker compose up -d db
	@echo "TODO: start backend/frontend dev servers (later phase)"

# Run the backend test suite.
test:
	cd backend && python -m pytest

# Run evaluation suite (Ragas + DeepEval, judged via app.evals.judge_adapter
# over LLMClient - LLM_BACKEND=replay by default, deterministic and offline;
# set LLM_BACKEND=groq for a real/manual judge run against a live key).
# Non-zero exit if either suite's scores/assertions fail - the CI gate.
eval:
	cd backend && python -m app.evals.ragas_suite
	cd backend && python -m app.evals.deepeval_suite

# Run Alembic migrations against the compose DB.
migrate:
	cd backend && python -m alembic upgrade head

# Seed local Postgres with the legacy JSON demo data (one-time; refuses to
# run if vehicles already exist - pass FORCE=1 to import anyway).
seed:
	cd backend && python -m scripts.import_json $(if $(FORCE),--force,)

# Lint the backend with ruff.
lint:
	ruff check backend

# Auto-format the backend with ruff.
fmt:
	ruff format backend
