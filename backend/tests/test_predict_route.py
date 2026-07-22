"""Integration test: /vehicles/{id}/predict against Postgres end-to-end."""

import uuid
from datetime import date

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.prediction import Prediction
from app.repositories.service_history import ServiceHistoryRepository
from app.repositories.vehicles import VehicleRepository
from tests.conftest import create_user_directly

PASSWORD = "correct horse battery staple"


async def _seed_known_vehicle():
    async with async_session_factory() as session:
        vehicle_repo = VehicleRepository(session)
        history_repo = ServiceHistoryRepository(session)
        await vehicle_repo.create(
            id="V001", make="Toyota", model="Corolla", year=2020, fuel_type="petrol"
        )
        await history_repo.add_event(
            "V001",
            service_date=date(2025, 11, 1),
            odometer_km=45000.0,
            service_type="oil_change",
        )
        await session.commit()


async def _mechanic_headers(async_client) -> dict:
    email = f"mechanic-{uuid.uuid4()}@example.com"
    await create_user_directly(email, PASSWORD, role="mechanic")
    r = await async_client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_predict_for_known_vehicle_writes_prediction_row(async_client):
    await _seed_known_vehicle()
    headers = await _mechanic_headers(async_client)

    response = await async_client.post(
        "/vehicles/V001/predict", json={"current_odometer_km": 47200}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] in ("model_v2", "model_v1", "rules")
    assert body["next_service_km"] is not None

    async with async_session_factory() as session:
        result = await session.execute(select(Prediction).where(Prediction.vehicle_id == "V001"))
        predictions = result.scalars().all()

    assert len(predictions) == 1
    assert predictions[0].model_version == body["source"]
    assert predictions[0].days_left == body["predicted_days_until_service"]
    assert predictions[0].km_left == body["predicted_kms_until_service"]


async def test_predict_for_unknown_vehicle_returns_404_and_writes_nothing(async_client):
    headers = await _mechanic_headers(async_client)

    response = await async_client.post(
        "/vehicles/UNKNOWN_XYZ/predict", json={"current_odometer_km": 50000}, headers=headers
    )

    assert response.status_code == 404

    async with async_session_factory() as session:
        result = await session.execute(select(Prediction))
        assert result.scalars().all() == []
