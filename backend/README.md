# PitCrew Backend

FastAPI service for the PitCrew vehicle service prediction platform.

This directory currently holds the original Vehicle Service Prediction API, moved here unchanged as part of the Phase 0 monorepo restructure.
Later phases will grow `app/` into the full PitCrew backend (Postgres persistence, auth, agents, RAG, evals, observability) per `plan.md` at the repo root.

## Layout

```
app/
  main.py            FastAPI app, lifespan model loading
  routers/            predict.py, vehicles.py
  schemas/             pydantic request/response models
  services/            predictor.py (model inference), rules.py (fallback)
models/               trained model artifacts (joblib)
storage/              JSON-file-backed vehicle history persistence
training/             model training scripts
data/                 training/synthetic datasets
tests/                test suite
```

## Setup

```bash
python -m venv myenv
myenv\Scripts\activate        # Windows
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

API available at `http://127.0.0.1:8000`, docs at `http://127.0.0.1:8000/docs`.

## Test

```bash
pytest
```

## Docker

Build context for this service is this `backend/` directory - see the root `docker-compose.yml`.

```bash
docker build -t pitcrew-backend .
docker run -p 8000:8000 pitcrew-backend
```

## Notes

- No auth yet - auth lands in a later phase.
- History is currently persisted to JSON files under `storage/`; Postgres+pgvector (via the root `docker-compose.yml`) replaces this in a later phase.
- v2 model requires vehicle metadata (make, year, fuel_type, last_service_type); omit these fields to fall back to v1.
