"""
Train v2 service-prediction model with expanded feature set.

New features vs v1: make, vehicle_model, year, fuel_type, last_service_type.
Uses a ColumnTransformer (StandardScaler for numeric, OneHotEncoder for
categorical) so sklearn handles the mixed types cleanly.

Persists:
  - models/service_predictor_v2.pkl
  - models/metrics_v2.json

Usage:
    python -m training.train_v2
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split
from sklearn.multioutput import MultiOutputRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeRegressor
from sklearn.ensemble import RandomForestRegressor

DATA_PATH    = Path("data/processed/service_history.csv")
MODELS_DIR   = Path("models")
MODEL_PATH   = MODELS_DIR / "service_predictor_v2.pkl"
METRICS_PATH = MODELS_DIR / "metrics_v2.json"

NUMERIC_FEATURES     = ["months_driven", "total_kms_driven", "year"]
CATEGORICAL_FEATURES = ["make", "fuel_type", "last_service_type"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGETS  = ["days_until_service", "kms_until_service"]

SEED = 42


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(DATA_PATH)
    X = df[FEATURES]
    y = df[TARGETS]
    return X, y


def build_preprocessor() -> ColumnTransformer:
    return ColumnTransformer([
        ("num", StandardScaler(),                        NUMERIC_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore"),  CATEGORICAL_FEATURES),
    ])


def build_pipeline(estimator) -> Pipeline:
    return Pipeline([
        ("preprocessor", build_preprocessor()),
        ("model",        MultiOutputRegressor(estimator)),
    ])


def evaluate(pipeline: Pipeline, X_test: pd.DataFrame, y_test: pd.DataFrame) -> dict:
    y_pred = pipeline.predict(X_test)
    maes = {}
    for i, target in enumerate(TARGETS):
        mae = float(mean_absolute_error(y_test.iloc[:, i], y_pred[:, i]))
        maes[target] = round(mae, 2)
    maes["mean_mae"] = round(float(np.mean(list(maes.values()))), 2)
    return maes


def train() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    X, y = load_data()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=SEED
    )

    candidates = {
        "DecisionTreeRegressor": build_pipeline(
            DecisionTreeRegressor(max_depth=8, random_state=SEED)
        ),
        "RandomForestRegressor": build_pipeline(
            RandomForestRegressor(n_estimators=100, max_depth=10, random_state=SEED, n_jobs=-1)
        ),
    }

    results = {}
    for name, pipeline in candidates.items():
        pipeline.fit(X_train, y_train)
        metrics = evaluate(pipeline, X_test, y_test)
        results[name] = {"metrics": metrics}
        print(f"{name}: MAE days={metrics['days_until_service']}, "
              f"MAE kms={metrics['kms_until_service']}, "
              f"mean_MAE={metrics['mean_mae']}")

    winner_name = min(results, key=lambda n: results[n]["metrics"]["mean_mae"])
    winner_pipeline = candidates[winner_name]
    winner_pipeline.fit(X, y)   # retrain on full data

    joblib.dump(winner_pipeline, MODEL_PATH)
    print(f"\nWinner: {winner_name} -> {MODEL_PATH}")

    output = {
        "version": "v2",
        "numeric_features":     NUMERIC_FEATURES,
        "categorical_features":  CATEGORICAL_FEATURES,
        "targets":   TARGETS,
        "winner":    winner_name,
        "test_size": 0.2,
        "candidates": results,
    }
    METRICS_PATH.write_text(json.dumps(output, indent=2))
    print(f"Metrics  -> {METRICS_PATH}")


if __name__ == "__main__":
    train()
