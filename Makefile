.PHONY: dev test eval migrate seed lint fmt

# Bring up local infra + backend for development.
# Filled in fully once backend/app grows a real entrypoint (later phases).
dev:
	docker compose up -d db
	@echo "TODO: start backend/frontend dev servers (later phase)"

# Run the backend test suite.
test:
	cd backend && python -m pytest

# Run evaluation suite (Ragas/DeepEval + local judge). Wired up in a later phase.
eval:
	@echo "TODO: wire eval suite (later phase)"

# Run Alembic migrations against the compose DB. Wired up in a later phase.
migrate:
	@echo "TODO: wire Alembic migrations (later phase)"

# Seed local Postgres with demo data. Wired up in a later phase.
seed:
	@echo "TODO: wire DB seeding (later phase)"

# Lint the backend with ruff.
lint:
	ruff check backend

# Auto-format the backend with ruff.
fmt:
	ruff format backend
