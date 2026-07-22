"""Integration tests for the FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    # Context-manager form triggers the lifespan so models are loaded
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "docs" in r.json()


class TestPredict:
    def test_stateless_predict_returns_correct_shape(self, client):
        r = client.post("/predict", json={"months_driven": 5, "total_kms_driven": 7200})
        assert r.status_code == 200
        body = r.json()
        assert "predicted_days_until_service" in body
        assert "predicted_kms_until_service" in body
        assert body["earlier_trigger"] in ("time", "km")
        assert body["source"] in ("model_v1", "model_v2", "rules")

    def test_rules_mode_returns_rules_source(self, client):
        r = client.post("/predict?mode=rules", json={"months_driven": 5, "total_kms_driven": 7200})
        assert r.status_code == 200
        assert r.json()["source"] == "rules"

    def test_v2_fields_trigger_model_v2(self, client):
        r = client.post("/predict", json={
            "months_driven": 5,
            "total_kms_driven": 7200,
            "make": "Toyota",
            "vehicle_model": "Corolla",
            "year": 2020,
            "fuel_type": "petrol",
            "last_service_type": "oil_change",
        })
        assert r.status_code == 200
        assert r.json()["source"] == "model_v2"

    def test_validation_rejects_negative_months(self, client):
        r = client.post("/predict", json={"months_driven": -1, "total_kms_driven": 5000})
        assert r.status_code == 422

    def test_validation_rejects_negative_km(self, client):
        r = client.post("/predict", json={"months_driven": 3, "total_kms_driven": -100})
        assert r.status_code == 422

    def test_invalid_fuel_type_rejected(self, client):
        r = client.post("/predict", json={
            "months_driven": 3,
            "total_kms_driven": 4000,
            "fuel_type": "nuclear",
        })
        assert r.status_code == 422


class TestVehicles:
    VEHICLE_ID = "TEST_V001"

    def _record_service(self, client, service_date: str, odometer: float, service_type: str = "oil_change"):
        return client.post(f"/vehicles/{self.VEHICLE_ID}/service", json={
            "service_date": service_date,
            "odometer_km": odometer,
            "service_type": service_type,
            "vehicle_metadata": {
                "make": "Honda", "vehicle_model": "Civic",
                "year": 2021, "fuel_type": "petrol",
            },
        })

    def test_record_service_returns_event(self, client):
        r = self._record_service(client, "2025-11-01", 45000)
        assert r.status_code == 200
        body = r.json()
        assert body["odometer_km"] == 45000.0
        assert "event_id" in body

    def test_get_history_returns_events(self, client):
        self._record_service(client, "2025-11-01", 45000)
        r = client.get(f"/vehicles/{self.VEHICLE_ID}/history")
        assert r.status_code == 200
        body = r.json()
        assert len(body["events"]) >= 1
        assert body["metadata"]["make"] == "Honda"

    def test_personalised_predict_populates_next_service_km(self, client):
        self._record_service(client, "2026-04-01", 50000)
        r = client.post(f"/vehicles/{self.VEHICLE_ID}/predict", json={"current_odometer_km": 51500})
        assert r.status_code == 200
        body = r.json()
        assert body["next_service_km"] is not None
        assert body["next_service_km"] > 51500

    def test_unknown_vehicle_predict_returns_404(self, client):
        r = client.post("/vehicles/UNKNOWN_XYZ/predict", json={"current_odometer_km": 50000})
        assert r.status_code == 404

    def test_odometer_regression_returns_422(self, client):
        self._record_service(client, "2026-04-01", 50000)
        r = client.post(f"/vehicles/{self.VEHICLE_ID}/predict", json={"current_odometer_km": 100})
        assert r.status_code == 422

    def test_unknown_vehicle_history_returns_404(self, client):
        r = client.get("/vehicles/DOES_NOT_EXIST/history")
        assert r.status_code == 404
