"""
API-level guard for the original bug: a brand-new, freshly-serviced vehicle
must NOT be predicted as already (near) due for service, on any tier.
"""

from app.services.predictor import predict

FRESH_MONTHS_DRIVEN = 0.0
FRESH_KMS_DRIVEN = 0.0


def test_fresh_vehicle_not_zero_on_model_v2_tier():
    """Full vehicle metadata supplied -> dispatches to model_v2."""
    result = predict(
        months_driven=FRESH_MONTHS_DRIVEN,
        kms_driven=FRESH_KMS_DRIVEN,
        make="Toyota",
        vehicle_model="Corolla",
        year=2024,
        fuel_type="petrol",
        last_service_type="oil_change",
    )

    assert result.source == "model_v2"
    assert result.predicted_days_until_service > 30
    assert result.predicted_kms_until_service > 1000


def test_fresh_vehicle_not_zero_without_v2_fields():
    """No optional vehicle metadata -> falls back past model_v2."""
    result = predict(
        months_driven=FRESH_MONTHS_DRIVEN,
        kms_driven=FRESH_KMS_DRIVEN,
    )

    assert result.source in ("model_v1", "rules")
    assert result.predicted_days_until_service > 30
    assert result.predicted_kms_until_service > 1000


def test_fresh_vehicle_not_zero_on_rules_tier():
    """Forcing the deterministic fallback must not zero out either target."""
    result = predict(
        months_driven=FRESH_MONTHS_DRIVEN,
        kms_driven=FRESH_KMS_DRIVEN,
        force_rules=True,
    )

    assert result.source == "rules"
    assert result.predicted_days_until_service > 30
    assert result.predicted_kms_until_service > 1000
