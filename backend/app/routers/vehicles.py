from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import require_permission
from app.db.session import get_session
from app.models.service_history import ServiceHistory
from app.models.user import User
from app.repositories.predictions import PredictionRepository
from app.repositories.service_history import ServiceHistoryRepository
from app.repositories.vehicles import VehicleRepository
from app.schemas.service import ServicePredictionResponse
from app.schemas.vehicle import (
    ServiceEventRequest,
    ServiceEventRecord,
    VehicleHistoryResponse,
    VehicleMetadata,
    VehiclePredictRequest,
)
from app.services.predictor import predict

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def _compute_empirical_km_per_month(events: list[ServiceHistory]) -> float | None:
    if len(events) < 2:
        return None
    total_km, total_months = 0.0, 0.0
    for i in range(1, len(events)):
        prev, curr = events[i - 1], events[i]
        km_diff = curr.odo_km - prev.odo_km
        months_diff = (curr.serviced_at - prev.serviced_at).days / 30.44
        if months_diff > 0 and km_diff >= 0:
            total_km     += km_diff
            total_months += months_diff
    return round(total_km / total_months, 1) if total_months else None


def _to_event_record(event: ServiceHistory) -> ServiceEventRecord:
    return ServiceEventRecord(
        event_id=str(event.id),
        service_date=event.serviced_at,
        odometer_km=event.odo_km,
        service_type=event.service_type,
    )


@router.post(
    "/{vehicle_id}/service",
    response_model=ServiceEventRecord,
    summary="Record a completed service event",
)
async def record_service(
    vehicle_id: str = Path(..., description="Vehicle identifier", examples=["V001"]),
    payload: ServiceEventRequest = ...,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permission("write_service")),
) -> ServiceEventRecord:
    vehicle_repo = VehicleRepository(session)
    history_repo = ServiceHistoryRepository(session)

    if payload.vehicle_metadata:
        meta = payload.vehicle_metadata.model_dump(exclude_none=True)
        await vehicle_repo.upsert_metadata(
            vehicle_id,
            make=meta.get("make"),
            model=meta.get("vehicle_model"),
            year=meta.get("year"),
            fuel_type=meta.get("fuel_type"),
        )
    elif await vehicle_repo.get(vehicle_id) is None:
        # Ensure the FK target exists even if no metadata was supplied.
        await vehicle_repo.upsert_metadata(vehicle_id)

    event = await history_repo.add_event(
        vehicle_id,
        service_date=payload.service_date,
        odometer_km=payload.odometer_km,
        service_type=payload.service_type,
    )
    await session.commit()
    return _to_event_record(event)


@router.get(
    "/{vehicle_id}/history",
    response_model=VehicleHistoryResponse,
    summary="Get service history for a vehicle",
)
async def get_history(
    vehicle_id: str = Path(..., description="Vehicle identifier", examples=["V001"]),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permission("read_vehicles", "read_own_vehicles")),
) -> VehicleHistoryResponse:
    vehicle_repo = VehicleRepository(session)
    vehicle = await vehicle_repo.get(vehicle_id)

    if current_user.role == "owner" and (vehicle is None or vehicle.owner_id != current_user.id):
        # Owners only ever see their own vehicles - a 403 (not 404) makes the
        # scoping explicit rather than indistinguishable from "not found".
        raise HTTPException(status_code=403, detail="Not permitted to view this vehicle")

    history_repo = ServiceHistoryRepository(session)
    events = await history_repo.list_for_vehicle(vehicle_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"No history found for vehicle '{vehicle_id}'")

    meta = VehicleMetadata(
        make=vehicle.make if vehicle else None,
        vehicle_model=vehicle.model if vehicle else None,
        year=vehicle.year if vehicle else None,
        fuel_type=vehicle.fuel_type if vehicle else None,
    )

    last = events[-1]
    return VehicleHistoryResponse(
        vehicle_id=vehicle_id,
        metadata=meta,
        events=[_to_event_record(e) for e in events],
        last_service_date=last.serviced_at,
        last_service_km=last.odo_km,
        empirical_km_per_month=_compute_empirical_km_per_month(events),
    )


@router.post(
    "/{vehicle_id}/predict",
    response_model=ServicePredictionResponse,
    summary="Predict next service using recorded history + vehicle metadata",
)
async def predict_for_vehicle(
    vehicle_id: str = Path(..., description="Vehicle identifier", examples=["V001"]),
    payload: VehiclePredictRequest = ...,
    request: Request = ...,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permission("run_predict")),
) -> ServicePredictionResponse:
    history_repo = ServiceHistoryRepository(session)
    last = await history_repo.get_last_for_vehicle(vehicle_id)
    if last is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No service history for vehicle '{vehicle_id}'. "
                "Record at least one event via POST /vehicles/{vehicle_id}/service first."
            ),
        )

    last_service_date = last.serviced_at
    last_odometer     = last.odo_km
    as_of             = payload.as_of_date or date.today()

    months_driven = (as_of - last_service_date).days / 30.44
    kms_driven    = payload.current_odometer_km - last_odometer

    if months_driven < 0:
        raise HTTPException(status_code=422, detail="as_of_date cannot be before the last recorded service date.")
    if kms_driven < 0:
        raise HTTPException(status_code=422, detail="current_odometer_km cannot be less than the odometer at last service.")

    vehicle_repo  = VehicleRepository(session)
    vehicle       = await vehicle_repo.get(vehicle_id)
    last_svc_type = last.service_type

    response = predict(
        months_driven=months_driven,
        kms_driven=kms_driven,
        model_v1=getattr(request.app.state, "model_v1", None),
        model_v2=getattr(request.app.state, "model_v2", None),
        make=vehicle.make if vehicle else None,
        vehicle_model=vehicle.model if vehicle else None,
        year=vehicle.year if vehicle else None,
        fuel_type=vehicle.fuel_type if vehicle else None,
        last_service_type=last_svc_type,
    )

    response.next_service_km = round(payload.current_odometer_km + response.predicted_kms_until_service, 1)

    prediction_repo = PredictionRepository(session)
    await prediction_repo.create(
        vehicle_id=vehicle_id,
        model_version=response.source,
        days_left=response.predicted_days_until_service,
        km_left=response.predicted_kms_until_service,
    )
    await session.commit()

    return response
