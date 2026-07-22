"""
Model registry: single source of truth for which prediction tier is active
and what its measured accuracy is.

Three tiers exist, in priority order:
  1. model_v2 - RandomForest/DecisionTree over months_driven, total_kms_driven,
     year, make, fuel_type, last_service_type. Loaded from MODEL_V2_PATH.
  2. model_v1 - DecisionTree/LinearRegression over months_driven,
     total_kms_driven only. Loaded from MODEL_V1_PATH.
  3. rules - deterministic threshold-based fallback (app.services.rules).
     Always available; has no MAE (it isn't a fitted model).

`active()` returns the highest-priority tier whose model file loads
successfully, cascading model_v2 -> model_v1 -> rules. `get(name)` fetches a
specific tier by name, cascading downward from that tier if its file is
missing, so predictor.py can start the cascade at whichever tier a given
request has enough fields for.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import joblib
import pandas as pd

from app.services.rules import predict_rules

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODEL_V1_PATH = _BACKEND_ROOT / "models" / "service_predictor.pkl"
MODEL_V2_PATH = _BACKEND_ROOT / "models" / "service_predictor_v2.pkl"
METRICS_V1_PATH = _BACKEND_ROOT / "models" / "metrics.json"
METRICS_V2_PATH = _BACKEND_ROOT / "models" / "metrics_v2.json"

V1_NUMERIC_FEATURES     = ["months_driven", "total_kms_driven"]
V2_NUMERIC_FEATURES     = ["months_driven", "total_kms_driven", "year"]
V2_CATEGORICAL_FEATURES = ["make", "fuel_type", "last_service_type"]

TIER_ORDER = ["model_v2", "model_v1", "rules"]

PredictFn = Callable[..., "tuple[float, float]"]


@dataclass(frozen=True)
class ModelTier:
    """A single dispatchable prediction tier."""

    name: str            # "model_v2" | "model_v1" | "rules"
    version: str         # "v2" | "v1" | "rules"
    mae: Optional[float]  # mean_mae from the tier's metrics file; None for rules
    predict_fn: PredictFn  # (**fields) -> (days_until: float, kms_until: float)


def _load_mean_mae(metrics_path: Path) -> Optional[float]:
    if not metrics_path.exists():
        return None
    try:
        metrics = json.loads(metrics_path.read_text())
        winner = metrics["winner"]
        return float(metrics["candidates"][winner]["metrics"]["mean_mae"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Could not parse MAE from %s: %s", metrics_path, exc)
        return None


def _load_pickle(path: Path):
    if not path.exists():
        return None
    try:
        return joblib.load(path)
    except Exception as exc:  # noqa: BLE001 - any load failure means "unavailable"
        logger.error("Failed to load model %s: %s", path, exc)
        return None


def _rules_predict_fn(*, months_driven: float, kms_driven: float, **_ignored) -> "tuple[float, float]":
    result = predict_rules(months_driven, kms_driven)
    return float(result.predicted_days_until_service), float(result.predicted_kms_until_service)


class ModelRegistry:
    def __init__(
        self,
        v1_path: Path = MODEL_V1_PATH,
        v2_path: Path = MODEL_V2_PATH,
        v1_metrics_path: Path = METRICS_V1_PATH,
        v2_metrics_path: Path = METRICS_V2_PATH,
    ) -> None:
        self._v1_path = Path(v1_path)
        self._v2_path = Path(v2_path)
        self._v1_metrics_path = Path(v1_metrics_path)
        self._v2_metrics_path = Path(v2_metrics_path)

    def _model_v2_tier(self) -> Optional[ModelTier]:
        model = _load_pickle(self._v2_path)
        if model is None:
            return None

        def predict_fn(
            *,
            months_driven: float,
            kms_driven: float,
            make: str,
            year: int,
            fuel_type: str,
            last_service_type: str,
            **_ignored,
        ) -> "tuple[float, float]":
            X = pd.DataFrame([{
                "months_driven":     months_driven,
                "total_kms_driven":  kms_driven,
                "year":              year,
                "make":              make,
                "fuel_type":         fuel_type,
                "last_service_type": last_service_type,
            }])
            preds = model.predict(X)[0]
            return float(preds[0]), float(preds[1])

        return ModelTier(
            name="model_v2",
            version="v2",
            mae=_load_mean_mae(self._v2_metrics_path),
            predict_fn=predict_fn,
        )

    def _model_v1_tier(self) -> Optional[ModelTier]:
        model = _load_pickle(self._v1_path)
        if model is None:
            return None

        def predict_fn(*, months_driven: float, kms_driven: float, **_ignored) -> "tuple[float, float]":
            X = pd.DataFrame([{"months_driven": months_driven, "total_kms_driven": kms_driven}])
            preds = model.predict(X)[0]
            return float(preds[0]), float(preds[1])

        return ModelTier(
            name="model_v1",
            version="v1",
            mae=_load_mean_mae(self._v1_metrics_path),
            predict_fn=predict_fn,
        )

    def _rules_tier(self) -> ModelTier:
        return ModelTier(name="rules", version="rules", mae=None, predict_fn=_rules_predict_fn)

    def _loader_for(self, name: str) -> Callable[[], Optional[ModelTier]]:
        return {
            "model_v2": self._model_v2_tier,
            "model_v1": self._model_v1_tier,
            "rules": lambda: self._rules_tier(),
        }[name]

    def active(self) -> ModelTier:
        """Highest-priority tier with a usable model on disk: model_v2 -> model_v1 -> rules."""
        for name in TIER_ORDER:
            tier = self._loader_for(name)()
            if tier is not None:
                return tier
        return self._rules_tier()  # unreachable in practice - rules always loads

    def get(self, name: str) -> ModelTier:
        """Fetch a specific tier by name, cascading down (model_v2 -> model_v1 ->
        rules) if that tier's model file is missing or fails to load."""
        if name not in TIER_ORDER:
            raise ValueError(f"Unknown tier '{name}'. Expected one of {TIER_ORDER}.")

        start = TIER_ORDER.index(name)
        for candidate_name in TIER_ORDER[start:]:
            tier = self._loader_for(candidate_name)()
            if tier is not None:
                return tier
        return self._rules_tier()


registry = ModelRegistry()
