from datetime import date

from fastapi import APIRouter, HTTPException, Path, Request

from app.schemas.service import ServicePredictionResponse
from app.schemas.vehicle import (
    ServiceEventRequest,
    ServiceEventRecord,
    VehicleHistoryResponse,
    VehicleMetadata,
    VehiclePredictRequest,
)
from app.services.predictor import predict
from storage import history as store

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def _compute_empirical_km_per_month(events: list[dict]) -> float | None:
    if len(events) < 2:
        return None
    total_km, total_months = 0.0, 0.0
    for i in range(1, len(events)):
        prev, curr = events[i - 1], events[i]
        km_diff = curr["odometer_km"] - prev["odometer_km"]
        months_diff = (
            date.fromisoformat(str(curr["service_date"]))
            - date.fromisoformat(str(prev["service_date"]))
        ).days / 30.44
        if months_diff > 0 and km_diff >= 0:
            total_km     += km_diff
            total_months += months_diff
    return round(total_km / total_months, 1) if total_months else None


@router.post(
    "/{vehicle_id}/service",
    response_model=ServiceEventRecord,
    summary="Record a completed service event",
)
def record_service(
    vehicle_id: str = Path(..., description="Vehicle identifier", examples=["V001"]),
    payload: ServiceEventRequest = ...,
) -> ServiceEventRecord:
    meta = payload.vehicle_metadata.model_dump(exclude_none=True) if payload.vehicle_metadata else None
    event = store.add_event(
        vehicle_id,
        payload.service_date,
        payload.odometer_km,
        service_type=payload.service_type,
        metadata=meta,
    )
    return ServiceEventRecord(**event)


@router.get(
    "/{vehicle_id}/history",
    response_model=VehicleHistoryResponse,
    summary="Get service history for a vehicle",
)
def get_history(
    vehicle_id: str = Path(..., description="Vehicle identifier", examples=["V001"]),
) -> VehicleHistoryResponse:
    raw = store.get_history(vehicle_id)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"No history found for vehicle '{vehicle_id}'")

    events = [ServiceEventRecord(**e) for e in raw["events"]]
    last   = raw["events"][-1] if raw["events"] else None
    meta   = raw.get("metadata", {})

    return VehicleHistoryResponse(
        vehicle_id=vehicle_id,
        metadata=VehicleMetadata(**meta),
        events=events,
        last_service_date=date.fromisoformat(last["service_date"]) if last else None,
        last_service_km=last["odometer_km"] if last else None,
        empirical_km_per_month=_compute_empirical_km_per_month(raw["events"]),
    )


@router.post(
    "/{vehicle_id}/predict",
    response_model=ServicePredictionResponse,
    summary="Predict next service using recorded history + vehicle metadata",
)
def predict_for_vehicle(
    vehicle_id: str = Path(..., description="Vehicle identifier", examples=["V001"]),
    payload: VehiclePredictRequest = ...,
    request: Request = ...,
) -> ServicePredictionResponse:
    last = store.get_last_event(vehicle_id)
    if last is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No service history for vehicle '{vehicle_id}'. "
                "Record at least one event via POST /vehicles/{vehicle_id}/service first."
            ),
        )

    last_service_date = date.fromisoformat(str(last["service_date"]))
    last_odometer     = last["odometer_km"]
    as_of             = payload.as_of_date or date.today()

    months_driven = (as_of - last_service_date).days / 30.44
    kms_driven    = payload.current_odometer_km - last_odometer

    if months_driven < 0:
        raise HTTPException(status_code=422, detail="as_of_date cannot be before the last recorded service date.")
    if kms_driven < 0:
        raise HTTPException(status_code=422, detail="current_odometer_km cannot be less than the odometer at last service.")

    # Pull stored metadata for v2 features
    meta           = store.get_metadata(vehicle_id)
    last_svc_type  = last.get("service_type")

    response = predict(
        months_driven=months_driven,
        kms_driven=kms_driven,
        model_v1=getattr(request.app.state, "model_v1", None),
        model_v2=getattr(request.app.state, "model_v2", None),
        make=meta.get("make"),
        vehicle_model=meta.get("vehicle_model"),
        year=meta.get("year"),
        fuel_type=meta.get("fuel_type"),
        last_service_type=last_svc_type,
    )

    response.next_service_km = round(payload.current_odometer_km + response.predicted_kms_until_service, 1)
    return response
