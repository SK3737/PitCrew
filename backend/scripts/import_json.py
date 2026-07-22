"""
One-time migration: import the legacy JSON service-history store into Postgres.

Reads ``backend/data/service_history.json`` (see storage/history.py's original
docstring for its shape: {vehicle_id: {"metadata": {...}, "events": [...]}})
and inserts one Vehicle row per key plus one ServiceHistory row per event.

Usage (from backend/):
    python -m scripts.import_json
    python -m scripts.import_json --data-path path/to/other.json
    python -m scripts.import_json --force   # import even if vehicles already exist
"""

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

from app.db.session import async_session_factory
from app.repositories.service_history import ServiceHistoryRepository
from app.repositories.vehicles import VehicleRepository

DEFAULT_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "service_history.json"


async def import_data(data_path: Path = DEFAULT_DATA_PATH, force: bool = False) -> tuple[int, int]:
    """Import vehicles + service history from `data_path`. Returns (vehicle_count, event_count)."""
    with open(data_path) as f:
        data: dict = json.load(f)

    async with async_session_factory() as session:
        vehicle_repo = VehicleRepository(session)
        history_repo = ServiceHistoryRepository(session)

        existing = await vehicle_repo.list()
        if existing and not force:
            raise RuntimeError(
                f"{len(existing)} vehicle(s) already present in the target database - "
                "refusing to import to avoid duplicate service_history rows. "
                "Pass --force to import anyway."
            )

        vehicle_count = 0
        event_count = 0
        for vehicle_id, record in data.items():
            metadata = record.get("metadata", {}) or {}
            await vehicle_repo.upsert_metadata(
                vehicle_id,
                make=metadata.get("make"),
                model=metadata.get("vehicle_model"),
                year=metadata.get("year"),
                fuel_type=metadata.get("fuel_type"),
            )
            vehicle_count += 1

            for event in record.get("events", []):
                await history_repo.add_event(
                    vehicle_id,
                    service_date=date.fromisoformat(str(event["service_date"])),
                    odometer_km=event["odometer_km"],
                    service_type=event.get("service_type"),
                )
                event_count += 1

        await session.commit()

    return vehicle_count, event_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Import even if vehicles already exist in the target database.",
    )
    args = parser.parse_args()

    vehicle_count, event_count = asyncio.run(import_data(args.data_path, force=args.force))
    print(f"Imported {vehicle_count} vehicle(s) and {event_count} service history event(s).")


if __name__ == "__main__":
    main()
