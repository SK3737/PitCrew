"""
Model-vs-rules dispatcher.

Priority on every call: v2 model (if optional fields provided) -> v1 model
-> rules. All three paths return the same ServicePredictionResponse schema.

Tier selection and MAE reporting live in app.services.model_registry; this
module is only responsible for (a) deciding which tier a given request has
enough fields to use, and (b) shaping a tier's raw (days, kms) output into
the response schema (clamping, rounding, earlier_trigger, next_service_date).
"""

import logging
from datetime import date, timedelta
from typing import Optional

import joblib

from app.schemas.service import ServicePredictionResponse
# Re-exported for app.main's startup wiring, which still imports these paths
# from this module.
from app.services.model_registry import (  # noqa: F401
    MODEL_V1_PATH,
    MODEL_V2_PATH,
    ModelRegistry,
    registry,
)

logger = logging.getLogger(__name__)

V2_NUMERIC_FEATURES     = ["months_driven", "total_kms_driven", "year"]
V2_CATEGORICAL_FEATURES = ["make", "fuel_type", "last_service_type"]
V2_ALL_FEATURES         = V2_NUMERIC_FEATURES + V2_CATEGORICAL_FEATURES


def load_model(path):
    """Kept for app.main's startup wiring / test patching; the registry does
    its own loading for the actual prediction dispatch below."""
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
    days_until: float,
    kms_until: float,
    km_per_month: float,
    source: str,
) -> ServicePredictionResponse:
    days_until = max(0, int(round(days_until)))
    kms_until = max(0.0, round(kms_until, 1))

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
    registry_: Optional[ModelRegistry] = None,
) -> ServicePredictionResponse:
    """
    model_v1/model_v2 are accepted for backward compatibility with callers
    that preload models onto app.state (see app.main's lifespan), but tier
    selection and loading is delegated to the model registry, which is the
    single source of truth for "what's active and how good is it".
    Passing model_v1=None/model_v2=None here does NOT disable a tier - the
    registry loads independently from disk. Use `registry_` (test-only) to
    inject a registry pointed at different paths.
    """
    reg = registry_ or registry

    km_per_month = kms_driven / months_driven if months_driven > 0 else 0.0

    if force_rules:
        tier = reg.get("rules")
    else:
        v2_fields_complete = all(
            f is not None for f in [make, year, fuel_type, last_service_type]
        )
        start_tier = "model_v2" if v2_fields_complete else "model_v1"
        tier = reg.get(start_tier)

    days_until, kms_until = tier.predict_fn(
        months_driven=months_driven,
        kms_driven=kms_driven,
        make=make,
        vehicle_model=vehicle_model,
        year=year,
        fuel_type=fuel_type,
        last_service_type=last_service_type,
    )

    return _build_response(days_until, kms_until, km_per_month, source=tier.name)
