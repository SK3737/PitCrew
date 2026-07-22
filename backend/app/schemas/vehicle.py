from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class VehicleMetadata(BaseModel):
    make: Optional[str] = Field(None, examples=["Toyota"])
    vehicle_model: Optional[str] = Field(None, examples=["Corolla"])
    year: Optional[int] = Field(None, ge=1990, le=2030, examples=[2020])
    fuel_type: Optional[Literal["petrol", "diesel", "hybrid", "electric"]] = None


class ServiceEventRequest(BaseModel):
    service_date: date = Field(..., description="Date the service was performed", examples=["2025-11-01"])
    odometer_km: float = Field(
        ..., ge=0, description="Total odometer reading at time of service (km)", examples=[45000]
    )
    service_type: Optional[Literal["oil_change", "full_service", "inspection", "brake_service"]] = Field(
        None, description="Type of service performed (used by v2 model for next prediction)"
    )
    # Optional: update or set vehicle metadata at the same time
    vehicle_metadata: Optional[VehicleMetadata] = Field(
        None, description="Set or update vehicle make/model/year/fuel_type. Stored and reused on subsequent predictions."
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "service_date": "2025-11-01",
                "odometer_km": 45000,
                "service_type": "oil_change",
                "vehicle_metadata": {
                    "make": "Toyota",
                    "vehicle_model": "Corolla",
                    "year": 2020,
                    "fuel_type": "petrol",
                },
            }]
        }
    }


class ServiceEventRecord(BaseModel):
    event_id: str
    service_date: date
    odometer_km: float
    service_type: Optional[str]


class VehicleHistoryResponse(BaseModel):
    vehicle_id: str
    metadata: VehicleMetadata
    events: list[ServiceEventRecord]
    last_service_date: Optional[date]
    last_service_km: Optional[float]
    empirical_km_per_month: Optional[float] = Field(
        None,
        description="Average km/month from service history. Used to personalise predictions.",
    )


class VehiclePredictRequest(BaseModel):
    current_odometer_km: float = Field(
        ..., ge=0, description="Current total odometer reading (km)", examples=[47200]
    )
    as_of_date: Optional[date] = Field(
        None, description="Date to compute months_driven from. Defaults to today."
    )

    model_config = {
        "json_schema_extra": {"examples": [{"current_odometer_km": 47200}]}
    }
