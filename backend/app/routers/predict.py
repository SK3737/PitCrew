from typing import Literal

from fastapi import APIRouter, Query, Request

from app.schemas.service import ServicePredictionRequest, ServicePredictionResponse
from app.services.predictor import predict

router = APIRouter(tags=["predict"])


@router.post("/predict", response_model=ServicePredictionResponse)
def predict_service(
    payload: ServicePredictionRequest,
    request: Request,
    mode: Literal["model", "rules"] = Query(
        "model",
        description="'model' uses the best available ML model; 'rules' uses the deterministic baseline",
    ),
) -> ServicePredictionResponse:
    return predict(
        months_driven=payload.months_driven,
        kms_driven=payload.total_kms_driven,
        model_v1=getattr(request.app.state, "model_v1", None),
        model_v2=getattr(request.app.state, "model_v2", None),
        force_rules=(mode == "rules"),
        make=payload.make,
        vehicle_model=payload.vehicle_model,
        year=payload.year,
        fuel_type=payload.fuel_type,
        last_service_type=payload.last_service_type,
    )
