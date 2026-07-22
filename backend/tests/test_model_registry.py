"""
TDD for the model registry: it must report which tier is active (model_v2 ->
model_v1 -> rules) and that tier's MAE, and must gracefully cascade down
when a model file is missing.
"""

from pathlib import Path

import pytest

from app.services.model_registry import ModelRegistry

REAL_V1_PATH = Path("models/service_predictor.pkl")
REAL_V2_PATH = Path("models/service_predictor_v2.pkl")
REAL_METRICS_V1_PATH = Path("models/metrics.json")
REAL_METRICS_V2_PATH = Path("models/metrics_v2.json")

MISSING_PATH = Path("models/does_not_exist.pkl")


def _real_registry() -> ModelRegistry:
    return ModelRegistry(
        v1_path=REAL_V1_PATH,
        v2_path=REAL_V2_PATH,
        v1_metrics_path=REAL_METRICS_V1_PATH,
        v2_metrics_path=REAL_METRICS_V2_PATH,
    )


def test_active_returns_model_v2_when_available():
    registry = _real_registry()
    tier = registry.active()

    assert tier.name == "model_v2"
    assert tier.version == "v2"
    assert isinstance(tier.mae, float)
    assert tier.mae > 0
    assert callable(tier.predict_fn)


def test_active_mae_matches_metrics_file():
    import json

    registry = _real_registry()
    tier = registry.active()

    metrics = json.loads(REAL_METRICS_V2_PATH.read_text())
    winner = metrics["winner"]
    expected_mae = metrics["candidates"][winner]["metrics"]["mean_mae"]

    assert tier.mae == pytest.approx(expected_mae)


def test_active_falls_back_to_model_v1_when_v2_file_missing():
    registry = ModelRegistry(
        v1_path=REAL_V1_PATH,
        v2_path=MISSING_PATH,
        v1_metrics_path=REAL_METRICS_V1_PATH,
        v2_metrics_path=REAL_METRICS_V2_PATH,
    )
    tier = registry.active()

    assert tier.name == "model_v1"
    assert tier.version == "v1"
    assert callable(tier.predict_fn)


def test_active_falls_back_to_rules_when_both_files_missing():
    registry = ModelRegistry(
        v1_path=MISSING_PATH,
        v2_path=MISSING_PATH,
        v1_metrics_path=REAL_METRICS_V1_PATH,
        v2_metrics_path=REAL_METRICS_V2_PATH,
    )
    tier = registry.active()

    assert tier.name == "rules"
    assert tier.version == "rules"
    assert tier.mae is None
    assert callable(tier.predict_fn)


def test_get_specific_tier_by_name():
    registry = _real_registry()

    tier = registry.get("model_v1")

    assert tier.name == "model_v1"


def test_get_cascades_down_when_requested_tier_missing():
    registry = ModelRegistry(
        v1_path=MISSING_PATH,
        v2_path=REAL_V2_PATH,
        v1_metrics_path=REAL_METRICS_V1_PATH,
        v2_metrics_path=REAL_METRICS_V2_PATH,
    )

    tier = registry.get("model_v1")

    assert tier.name == "rules"


def test_predict_fn_returns_two_numeric_values():
    registry = _real_registry()
    tier = registry.active()

    days, kms = tier.predict_fn(
        months_driven=0.0,
        kms_driven=0.0,
        make="Toyota",
        year=2024,
        fuel_type="petrol",
        last_service_type="oil_change",
    )

    assert isinstance(days, float)
    assert isinstance(kms, float)
