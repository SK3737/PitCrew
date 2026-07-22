"""
Characterizes the training-data bias described in project memory: a synthetic
generator that only samples vehicles AT the service threshold (already due or
overdue) trains models that predict near-zero remaining days/km even for a
brand-new, freshly-serviced vehicle.

The thresholds below translate "not clustered near zero" into concrete,
range-relative numbers, chosen against this domain's known scale (typical
full interval ~6 months / 10,000 km, so a healthy dataset's targets should
routinely reach well above a small fraction of that):

- mean(days_until_service)  >= 45   (>= ~25% of a 182-day/6-month interval)
- mean(kms_until_service)   >= 2500 (>= 25% of the 10,000 km interval)
- P75 - P25 spread (days)   >= 50   (targets aren't all bunched together)
- P75 - P25 spread (kms)    >= 2500
- fraction of rows with days_until_service <= 5   < 0.10 (guards the specific
  "clustered at the threshold" failure mode: most rows already due)

`_generate_naive_biased_dataset` reconstructs the bug exactly as described:
every snapshot is sampled within a hair of the trigger point (already due or
overdue), never earlier in the interval life. It exists purely to prove this
test discriminates a biased generator from a corrected one, and doubles as a
regression guard: if a future change to `scripts/generate_dataset.py`
reintroduces threshold-only sampling, this file documents exactly what that
looks like and why it fails.
"""

from pathlib import Path

import numpy as np
import pandas as pd

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "service_history.csv"

MEAN_DAYS_FLOOR = 45
MEAN_KMS_FLOOR = 2500
SPREAD_DAYS_FLOOR = 50
SPREAD_KMS_FLOOR = 2500
NEAR_ZERO_DAYS = 5
NEAR_ZERO_FRACTION_CEILING = 0.10


def _assert_spans_interval(df: pd.DataFrame) -> None:
    days = df["days_until_service"]
    kms = df["kms_until_service"]

    days_spread = days.quantile(0.75) - days.quantile(0.25)
    kms_spread = kms.quantile(0.75) - kms.quantile(0.25)
    near_zero_fraction = (days <= NEAR_ZERO_DAYS).mean()

    assert days.mean() >= MEAN_DAYS_FLOOR, (
        f"mean days_until_service={days.mean():.1f} is clustered near zero "
        f"(expected >= {MEAN_DAYS_FLOOR})"
    )
    assert kms.mean() >= MEAN_KMS_FLOOR, (
        f"mean kms_until_service={kms.mean():.1f} is clustered near zero "
        f"(expected >= {MEAN_KMS_FLOOR})"
    )
    assert days_spread >= SPREAD_DAYS_FLOOR, (
        f"days_until_service P75-P25 spread={days_spread:.1f} is too narrow "
        f"(expected >= {SPREAD_DAYS_FLOOR})"
    )
    assert kms_spread >= SPREAD_KMS_FLOOR, (
        f"kms_until_service P75-P25 spread={kms_spread:.1f} is too narrow "
        f"(expected >= {SPREAD_KMS_FLOOR})"
    )
    assert near_zero_fraction < NEAR_ZERO_FRACTION_CEILING, (
        f"{near_zero_fraction:.0%} of rows have days_until_service <= "
        f"{NEAR_ZERO_DAYS} (expected < {NEAR_ZERO_FRACTION_CEILING:.0%}) - "
        "dataset looks sampled only at/near the service threshold"
    )


def _generate_naive_biased_dataset(n_samples: int = 3_000, seed: int = 42) -> pd.DataFrame:
    """Reproduces the described bug: snapshots taken only near the trigger
    point (elapsed_fraction ~ Uniform(0.9, 1.0)) instead of across the full
    0..1 interval life. Time threshold 6 months, km threshold 10,000."""
    rng = np.random.default_rng(seed)
    month_threshold = 6.0
    km_threshold = 10_000.0

    records = []
    for _ in range(n_samples):
        km_per_month = max(100.0, float(rng.normal(1_600, 400)))
        months_to_km = km_threshold / km_per_month
        actual_months = min(month_threshold, months_to_km)

        # BUG: only sample the last 10% of the interval life - already due
        # or overdue, never "just serviced".
        elapsed_fraction = float(rng.uniform(0.9, 1.0))
        months_driven = elapsed_fraction * actual_months
        kms_driven = km_per_month * months_driven

        months_remaining = max(0.0, actual_months - months_driven)
        days_until_service = max(0, round(months_remaining * 30.44))
        kms_until_service = max(0.0, round(km_threshold - kms_driven, 1))

        records.append({
            "months_driven": round(months_driven, 2),
            "total_kms_driven": round(kms_driven, 1),
            "days_until_service": days_until_service,
            "kms_until_service": kms_until_service,
        })

    return pd.DataFrame(records)


def test_naive_biased_dataset_fails_the_spread_check():
    """Proves the assertion helper actually discriminates: a generator that
    only samples near the threshold must fail these checks."""
    biased = _generate_naive_biased_dataset()

    assert biased["days_until_service"].mean() < MEAN_DAYS_FLOOR
    assert (biased["days_until_service"] <= NEAR_ZERO_DAYS).mean() >= NEAR_ZERO_FRACTION_CEILING


def test_targets_span_interval():
    """The real, corrected training set (written by scripts/generate_dataset.py)
    must NOT be clustered near zero: targets should range from "just serviced"
    to "at the threshold", not sit permanently at the due/overdue end."""
    assert DATA_PATH.exists(), f"training set not found at {DATA_PATH}"
    df = pd.read_csv(DATA_PATH)

    assert "days_until_service" in df.columns
    assert "kms_until_service" in df.columns

    _assert_spans_interval(df)
