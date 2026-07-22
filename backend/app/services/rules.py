from datetime import date, timedelta

from app.schemas.service import ServicePredictionResponse

TIME_THRESHOLD_MONTHS = 6.0
KM_THRESHOLD = 10_000.0
DAYS_PER_MONTH = 30.44


def predict_rules(months_driven: float, kms_driven: float) -> ServicePredictionResponse:
    months_remaining = max(0.0, TIME_THRESHOLD_MONTHS - months_driven)
    kms_remaining = max(0.0, KM_THRESHOLD - kms_driven)

    days_to_time_trigger = months_remaining * DAYS_PER_MONTH

    km_per_month = kms_driven / months_driven if months_driven > 0 else 0.0

    if km_per_month > 0:
        days_to_km_trigger = (kms_remaining / km_per_month) * DAYS_PER_MONTH
    else:
        days_to_km_trigger = float("inf")

    if days_to_time_trigger <= days_to_km_trigger:
        earlier_trigger: str = "time"
        days_until = days_to_time_trigger
        kms_until = km_per_month * months_remaining
    else:
        earlier_trigger = "km"
        days_until = days_to_km_trigger
        kms_until = kms_remaining

    days_until_int = int(round(days_until))
    next_service_date = date.today() + timedelta(days=days_until_int)

    return ServicePredictionResponse(
        predicted_days_until_service=days_until_int,
        predicted_kms_until_service=round(kms_until, 1),
        earlier_trigger=earlier_trigger,  # type: ignore[arg-type]
        next_service_date=next_service_date,
        next_service_km=None,
        source="rules",
    )
