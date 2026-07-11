# Predictive Vehicle Service Recommendation API

FastAPI service that predicts when a vehicle will next need service — a target date and odometer milestone — from driving history. Backed by two scikit-learn models (v1: mileage/time only, v2: adds vehicle make/model/year/fuel/last-service-type) with a deterministic rules-based fallback when no model is loaded.

## Features

- **`POST /predict`** — one-shot prediction from `months_driven` / `total_kms_driven` (+ optional vehicle fields for the v2 model). `mode=model|rules` query param picks ML vs. rules baseline.
- **`POST /vehicles/{vehicle_id}/service`** — record a completed service event (date, odometer, service type, metadata) to build up history.
- **`GET /vehicles/{vehicle_id}/history`** — full service history plus empirical km/month driving rate.
- **`POST /vehicles/{vehicle_id}/predict`** — predict next service using a vehicle's stored history instead of manually passing driven distance/time.
- **`GET /health`** — model load status.

Interactive docs at `/docs` once running.

## Project layout

```
app/
  main.py            FastAPI app, lifespan model loading
  routers/           predict.py, vehicles.py
  schemas/           pydantic request/response models
  services/          predictor.py (model inference), rules.py (fallback)
models/              trained model artifacts (joblib)
storage/             JSON-file-backed vehicle history persistence
training/            model training scripts
data/                training/synthetic datasets
tests/               test suite
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

```bash
docker build -t vehicle-service-api .
docker run -p 8000:8000 vehicle-service-api
```

## Notes

- No auth — this is an MVP/demo project.
- History is persisted to JSON files under `storage/`, not a database.
- v2 model requires vehicle metadata (make, year, fuel_type, last_service_type); omit these fields to fall back to v1.
