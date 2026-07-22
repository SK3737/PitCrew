"""
JSON-backed per-vehicle service history store.

Schema (data/service_history.json):
{
  "V001": {
    "metadata": {
      "make": "Toyota", "vehicle_model": "Corolla",
      "year": 2020, "fuel_type": "petrol"
    },
    "events": [
      {"event_id": "...", "service_date": "2025-11-01",
       "odometer_km": 45000.0, "service_type": "oil_change"}
    ]
  }
}
"""

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

STORE_PATH = Path("data/service_history.json")


def _load() -> dict:
    if not STORE_PATH.exists():
        return {}
    with open(STORE_PATH, "r") as f:
        return json.load(f)


def _save(data: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STORE_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)


def get_history(vehicle_id: str) -> Optional[dict]:
    return _load().get(vehicle_id)


def upsert_metadata(vehicle_id: str, metadata: dict) -> None:
    data = _load()
    if vehicle_id not in data:
        data[vehicle_id] = {"metadata": {}, "events": []}
    data[vehicle_id]["metadata"].update(metadata)
    _save(data)


def add_event(
    vehicle_id: str,
    service_date: date,
    odometer_km: float,
    service_type: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    data = _load()
    if vehicle_id not in data:
        data[vehicle_id] = {"metadata": {}, "events": []}

    if metadata:
        data[vehicle_id]["metadata"].update(metadata)

    event = {
        "event_id":    str(uuid.uuid4())[:8],
        "service_date": str(service_date),
        "odometer_km": odometer_km,
        "service_type": service_type,
    }
    data[vehicle_id]["events"].append(event)
    _save(data)
    return event


def get_last_event(vehicle_id: str) -> Optional[dict]:
    history = get_history(vehicle_id)
    if not history or not history["events"]:
        return None
    return history["events"][-1]


def get_metadata(vehicle_id: str) -> dict:
    history = get_history(vehicle_id)
    if not history:
        return {}
    return history.get("metadata", {})
