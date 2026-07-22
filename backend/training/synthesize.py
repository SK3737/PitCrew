"""
Synthetic service-history dataset generator.

v2: adds make, vehicle_model, year, fuel_type, last_service_type columns with
fuel-type-specific and age-specific service thresholds so the new features
are genuinely predictive (not cosmetic).

Usage:
    python -m training.synthesize
"""

import argparse
import random
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
OUTPUT_PATH = Path("data/processed/service_history.csv")

# Per-fuel-type manufacturer thresholds
FUEL_THRESHOLDS = {
    "petrol":   {"km": 10_000, "months": 6},
    "diesel":   {"km": 15_000, "months": 6},
    "hybrid":   {"km": 12_000, "months": 6},
    "electric": {"km": 999_999, "months": 12},   # effectively time-only
}

FUEL_WEIGHTS = [0.50, 0.25, 0.15, 0.10]   # petrol / diesel / hybrid / electric

# Driver profiles: (mean_km_per_month, std_km_per_month)
PROFILES = {
    "light":   (800,  150),
    "average": (1_600, 300),
    "heavy":   (3_000, 500),
}
PROFILE_WEIGHTS = [0.25, 0.50, 0.25]

MAKES = ["Toyota", "Honda", "Ford", "Hyundai", "BMW", "Volkswagen", "Maruti"]
MODELS_BY_MAKE = {
    "Toyota": ["Corolla", "Camry", "RAV4"],
    "Honda":  ["Civic", "Accord", "CR-V"],
    "Ford":   ["Focus", "Fiesta", "Escape"],
    "Hyundai":["i20", "Creta", "Tucson"],
    "BMW":    ["3 Series", "5 Series", "X3"],
    "Volkswagen": ["Polo", "Golf", "Tiguan"],
    "Maruti": ["Swift", "Baleno", "Vitara"],
}
SERVICE_TYPES = ["oil_change", "full_service", "inspection", "brake_service"]
SERVICE_TYPE_WEIGHTS = [0.45, 0.30, 0.15, 0.10]


def _year_km_factor(year: int) -> float:
    """Older cars need more frequent service → lower effective km threshold."""
    if year <= 2015:
        return 0.80
    if year <= 2020:
        return 1.00
    return 1.10


def generate(n_samples: int = 3_000, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    random.seed(seed)

    fuel_types = list(FUEL_THRESHOLDS.keys())
    profiles   = list(PROFILES.keys())
    records    = []

    for _ in range(n_samples):
        profile    = rng.choice(profiles, p=PROFILE_WEIGHTS)
        fuel_type  = rng.choice(fuel_types, p=FUEL_WEIGHTS)
        make       = rng.choice(MAKES)
        model_name = rng.choice(MODELS_BY_MAKE[make])
        year       = int(rng.integers(2010, 2025))
        svc_type   = rng.choice(SERVICE_TYPES, p=SERVICE_TYPE_WEIGHTS)

        base_thresholds = FUEL_THRESHOLDS[fuel_type]
        km_threshold    = base_thresholds["km"] * _year_km_factor(year)
        month_threshold = float(base_thresholds["months"])

        mean_km, std_km = PROFILES[profile]
        km_per_month    = max(100.0, float(rng.normal(mean_km, std_km)))

        delay_factor = max(0.5, min(1.5, float(rng.normal(1.0, 0.1))))

        months_to_time = month_threshold * delay_factor
        months_to_km   = km_threshold / km_per_month

        if months_to_time <= months_to_km:
            trigger        = "time"
            actual_months  = months_to_time
        else:
            trigger        = "km"
            actual_months  = months_to_km

        # Sample snapshot at a random point in [0, trigger_point] so the dataset
        # covers the whole driving cycle, not just the moment service fires.
        months_driven = float(rng.uniform(0.1, actual_months))
        kms_driven    = max(0.0, km_per_month * months_driven + float(rng.normal(0, 50)))

        if trigger == "time":
            months_remaining = max(0.0, months_to_time - months_driven)
            days_until_service = max(0, int(round(months_remaining * 30.44)))
            kms_until_service  = max(0.0, round(km_per_month * months_remaining, 1))
        else:
            kms_until_service  = max(0.0, round(km_threshold - kms_driven, 1))
            months_remaining   = max(0.0, months_to_km - months_driven)
            days_until_service = max(0, int(round(months_remaining * 30.44)))

        records.append({
            "months_driven":      round(months_driven, 2),
            "total_kms_driven":   round(kms_driven, 1),
            "make":               make,
            "vehicle_model":      model_name,
            "year":               year,
            "fuel_type":          fuel_type,
            "last_service_type":  svc_type,
            "days_until_service": days_until_service,
            "kms_until_service":  kms_until_service,
            "driver_profile":     profile,
            "trigger":            trigger,
        })

    return pd.DataFrame(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic service-history data")
    parser.add_argument("--n",    type=int, default=3_000, help="Number of samples (default 3000)")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out",  type=str, default=str(OUTPUT_PATH))
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    df = generate(n_samples=args.n, seed=args.seed)
    df.to_csv(out, index=False)

    print(f"Generated {len(df)} rows -> {out}")
    print(df[["months_driven","total_kms_driven","days_until_service","kms_until_service"]].describe().to_string())


if __name__ == "__main__":
    main()
