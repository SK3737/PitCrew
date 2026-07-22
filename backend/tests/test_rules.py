"""Unit tests for the deterministic rules predictor."""

from datetime import date, timedelta

import pytest

from app.services.rules import TIME_THRESHOLD_MONTHS, KM_THRESHOLD, predict_rules


def test_time_triggers_for_light_driver():
    # 5 months, only 500 km → time fires first (at 6 months)
    result = predict_rules(months_driven=5.0, kms_driven=500.0)
    assert result.earlier_trigger == "time"
    assert result.source == "rules"
    assert result.predicted_days_until_service > 0


def test_km_triggers_for_heavy_driver():
    # 2 months, 9500 km → km fires first (only 500 km left)
    result = predict_rules(months_driven=2.0, kms_driven=9500.0)
    assert result.earlier_trigger == "km"
    assert result.predicted_kms_until_service <= 500.0


def test_overdue_vehicle_returns_zeros():
    # Both thresholds exceeded → 0 days and 0 km remaining
    result = predict_rules(months_driven=8.0, kms_driven=12_000.0)
    assert result.predicted_days_until_service == 0
    assert result.predicted_kms_until_service == 0.0


def test_fresh_vehicle_gets_full_time_budget():
    # 0 months, 0 km → full time threshold
    result = predict_rules(months_driven=0.0, kms_driven=0.0)
    expected_days = round(TIME_THRESHOLD_MONTHS * 30.44)
    assert abs(result.predicted_days_until_service - expected_days) <= 1


def test_response_schema_fields():
    result = predict_rules(months_driven=3.0, kms_driven=4000.0)
    assert result.next_service_date >= date.today()
    assert result.next_service_km is None   # stateless call — no odometer state
    assert result.source == "rules"
    assert result.earlier_trigger in ("time", "km")


def test_next_service_date_is_today_when_overdue():
    result = predict_rules(months_driven=10.0, kms_driven=15_000.0)
    assert result.next_service_date == date.today()
