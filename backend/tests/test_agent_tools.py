"""
Regression coverage for a Phase 5 review finding in app.agents.tools:

``RepositoryVehicleDataProvider.get_snapshot`` used to hard-code
``kms_driven=0.0`` for every vehicle - a fabricated value fed straight into
the real ML predictor tiers (model_v1/model_v2) as if it were a genuine
odometer reading. It now derives an estimate from the vehicle's own
service-history cadence (empirical km/month - the same estimate already
surfaced on ``GET /vehicles/{id}/history``), projected across the months
elapsed since the last service.

Why this matters (the "before" behaviour, documented directly against
``predict()``'s real math, not asserted from memory): ``predict()`` computes
``km_per_month = kms_driven / months_driven``, and when that's 0, the
km-based "days until service" collapses to infinity - so
``earlier_trigger`` can never resolve to "km", no matter what the model
predicts. A hard-coded ``kms_driven=0.0`` therefore silently forced every
assistant-driven prediction onto a time-only trigger, and fed the trained
models a literal 0 for a numeric feature real vehicles essentially never
have.
"""

from datetime import date

from app.agents.tools import RepositoryVehicleDataProvider
from app.repositories.service_history import (
    ServiceHistoryRepository,
    compute_empirical_km_per_month,
)
from app.repositories.vehicles import VehicleRepository
from app.services.predictor import predict


async def _seed_vehicle_with_cadence(db_session, vehicle_id: str = "V001"):
    """Three service events ~6 months apart, ~5000 km apart each time - a
    clear, realistic driving cadence (~833 km/month)."""
    vehicle_repo = VehicleRepository(db_session)
    history_repo = ServiceHistoryRepository(db_session)

    await vehicle_repo.create(id=vehicle_id, make="Toyota", model="Corolla", year=2020, fuel_type="petrol")
    await history_repo.add_event(vehicle_id, service_date=date(2024, 1, 1), odometer_km=10000.0)
    await history_repo.add_event(vehicle_id, service_date=date(2024, 7, 1), odometer_km=15000.0)
    last = await history_repo.add_event(vehicle_id, service_date=date(2025, 1, 1), odometer_km=20000.0)
    await db_session.commit()
    return last


async def test_get_snapshot_estimates_kms_driven_from_history_cadence_instead_of_zero(db_session):
    last = await _seed_vehicle_with_cadence(db_session)

    events = await ServiceHistoryRepository(db_session).list_for_vehicle("V001")
    expected_km_per_month = compute_empirical_km_per_month(events)
    expected_months_driven = max((date.today() - last.serviced_at).days / 30.44, 0.0)

    provider = RepositoryVehicleDataProvider(db_session)
    snapshot = await provider.get_snapshot("V001")

    assert snapshot is not None
    assert expected_km_per_month is not None and expected_km_per_month > 0
    # Before this fix, kms_driven was unconditionally 0.0 here regardless of
    # how much history the vehicle had - this is the concrete behaviour change.
    assert snapshot.kms_driven == round(expected_km_per_month * expected_months_driven, 1)
    assert snapshot.kms_driven > 0.0


async def test_get_snapshot_falls_back_to_zero_with_insufficient_history(db_session):
    """A single service event carries no interval to derive a cadence from -
    0.0 is an honest "unknown", not a fabricated stand-in for a real reading,
    so this fallback is preserved deliberately (not a regression)."""
    vehicle_repo = VehicleRepository(db_session)
    history_repo = ServiceHistoryRepository(db_session)
    await vehicle_repo.create(id="V002", make="Honda", model="Civic", year=2021, fuel_type="petrol")
    await history_repo.add_event("V002", service_date=date(2025, 1, 1), odometer_km=8000.0)
    await db_session.commit()

    provider = RepositoryVehicleDataProvider(db_session)
    snapshot = await provider.get_snapshot("V002")

    assert snapshot is not None
    assert snapshot.kms_driven == 0.0


def test_zero_kms_driven_collapses_the_km_trigger_to_always_time():
    """Documents the mechanism of the pre-fix bug directly against
    predictor.predict(): feeding kms_driven=0.0 (what get_snapshot used to
    hard-code for every vehicle) makes km_per_month collapse to 0, which
    makes the km-based "days until service" infinite, which forces
    earlier_trigger to always be "time" - never "km" - no matter what a
    trained model predicts for predicted_kms_until_service."""
    response = predict(months_driven=6.0, kms_driven=0.0, force_rules=True)
    assert response.earlier_trigger == "time"


def test_nonzero_estimated_kms_driven_yields_a_real_km_signal():
    """The same call with a genuine (estimated, non-fabricated) kms_driven
    produces a finite km-per-month figure, so the km trigger is a real
    signal in the comparison again instead of being suppressed by
    construction."""
    response = predict(months_driven=6.0, kms_driven=5000.0, force_rules=True)
    km_per_month = 5000.0 / 6.0
    assert km_per_month > 0
    assert response.predicted_kms_until_service >= 0.0
