from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

VALID_FUEL_TYPES    = ["petrol", "diesel", "hybrid", "electric"]
VALID_SERVICE_TYPES = ["oil_change", "full_service", "inspection", "brake_service"]


class ServicePredictionRequest(BaseModel):
    # v1 features (required)
    months_driven: float = Field(
        ..., ge=0, description="Months since the last service", examples=[5]
    )
    total_kms_driven: float = Field(
        ..., ge=0, description="Kilometres driven since the last service", examples=[7200]
    )
    # v2 features (optional — if provided, the expanded model is used)
    make: Optional[str] = Field(None, description="Vehicle make (e.g. Toyota, Honda)", examples=["Toyota"])
    vehicle_model: Optional[str] = Field(None, description="Vehicle model name", examples=["Corolla"])
    year: Optional[int] = Field(None, ge=1990, le=2030, description="Vehicle manufacture year", examples=[2020])
    fuel_type: Optional[Literal["petrol", "diesel", "hybrid", "electric"]] = Field(
        None, description="Fuel type"
    )
    last_service_type: Optional[Literal["oil_change", "full_service", "inspection", "brake_service"]] = Field(
        None, description="Type of the last service performed"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "months_driven": 5,
                    "total_kms_driven": 7200,
                    "make": "Toyota",
                    "vehicle_model": "Corolla",
                    "year": 2020,
                    "fuel_type": "petrol",
                    "last_service_type": "oil_change",
                }
            ]
        }
    }


class ServicePredictionResponse(BaseModel):
    predicted_days_until_service: int = Field(
        ..., description="Days from today until the next service is due"
    )
    predicted_kms_until_service: float = Field(
        ..., description="Kilometres until the next service is due"
    )
    earlier_trigger: Literal["time", "km"] = Field(
        ..., description="Which threshold will be hit first"
    )
    next_service_date: date = Field(
        ..., description="Today + predicted_days_until_service"
    )
    next_service_km: Optional[float] = Field(
        None,
        description=(
            "Current odometer + predicted_kms_until_service. "
            "Populated when called via /vehicles/{id}/predict."
        ),
    )
    source: Literal["model_v2", "model_v1", "rules"] = Field(
        ..., description="Which predictor was used"
    )
