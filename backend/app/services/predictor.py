"""
Model-vs-rules dispatcher.

Priority on every call: v2 model (if optional fields provided) → v1 model → rules.
All three paths return the same ServicePredictionResponse schema.
"""

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd

from app.schemas.service import ServicePredictionResponse
from app.services.rules import predict_rules

logger = logging.getLogger(__name__)

MODEL_V1_PATH = Path("models/service_predictor.pkl")
MODEL_V2_PATH = Path("models/service_predictor_v2.pkl")

V2_NUMERIC_FEATURES     = ["months_driven", "total_kms_driven", "year"]
V2_CATEGORICAL_FEATURES = ["make", "fuel_type", "last_service_type"]
V2_ALL_FEATURES         = V2_NUMERIC_FEATURES + V2_CATEGORICAL_FEATURES


def load_model(path: Path):
    if not path.exists():
        logger.warning("Model file not found at %s", path)
        return None
    try:
        model = joblib.load(path)
        logger.info("Loaded model from %s", path)
        return model
    except Exception as exc:
        logger.error("Failed to load model %s: %s", path, exc)
        return None


def _build_response(
    days_until: int,
    kms_until: float,
    km_per_month: float,
    source: str,
) -> ServicePredictionResponse:
    if km_per_month > 0:
        days_to_km = (kms_until / km_per_month) * 30.44
    else:
        days_to_km = float("inf")

    earlier_trigger = "time" if days_until <= days_to_km else "km"
    next_service_date = date.today() + timedelta(days=days_until)

    return ServicePredictionResponse(
        predicted_days_until_service=days_until,
        predicted_kms_until_service=kms_until,
        earlier_trigger=earlier_trigger,  # type: ignore[arg-type]
        next_service_date=next_service_date,
        next_service_km=None,
        source=source,  # type: ignore[arg-type]
    )


def _predict_v1(model_v1, months_driven: float, kms_driven: float) -> ServicePredictionResponse:
    X = pd.DataFrame([{"months_driven": months_driven, "total_kms_driven": kms_driven}])
    preds = model_v1.predict(X)[0]
    km_per_month = kms_driven / months_driven if months_driven > 0 else 0.0
    return _build_response(
        days_until=max(0, int(round(float(preds[0])))),
        kms_until=max(0.0, round(float(preds[1]), 1)),
        km_per_month=km_per_month,
        source="model_v1",
    )


def _predict_v2(
    model_v2,
    months_driven: float,
    kms_driven: float,
    make: str,
    year: int,
    fuel_type: str,
    last_service_type: str,
) -> ServicePredictionResponse:
    X = pd.DataFrame([{
        "months_driven":      months_driven,
        "total_kms_driven":   kms_driven,
        "year":               year,
        "make":               make,
        "fuel_type":          fuel_type,
        "last_service_type":  last_service_type,
    }])
    preds = model_v2.predict(X)[0]
    km_per_month = kms_driven / months_driven if months_driven > 0 else 0.0
    return _build_response(
        days_until=max(0, int(round(float(preds[0])))),
        kms_until=max(0.0, round(float(preds[1]), 1)),
        km_per_month=km_per_month,
        source="model_v2",
    )


def predict(
    months_driven: float,
    kms_driven: float,
    model_v1=None,
    model_v2=None,
    force_rules: bool = False,
    # v2 optional fields
    make: Optional[str] = None,
    vehicle_model: Optional[str] = None,
    year: Optional[int] = None,
    fuel_type: Optional[str] = None,
    last_service_type: Optional[str] = None,
) -> ServicePredictionResponse:
    if force_rules:
        return predict_rules(months_driven, kms_driven)

    v2_fields_complete = all(
        f is not None for f in [make, year, fuel_type, last_service_type]
    )
    if model_v2 is not None and v2_fields_complete:
        return _predict_v2(model_v2, months_driven, kms_driven, make, year, fuel_type, last_service_type)

    if model_v1 is not None:
        return _predict_v1(model_v1, months_driven, kms_driven)

    return predict_rules(months_driven, kms_driven)
