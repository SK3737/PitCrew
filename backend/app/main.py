import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from app.routers import predict, vehicles
from app.services.predictor import MODEL_V1_PATH, MODEL_V2_PATH, load_model


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model_v1 = load_model(MODEL_V1_PATH)
    app.state.model_v2 = load_model(MODEL_V2_PATH)
    yield
    app.state.model_v1 = None
    app.state.model_v2 = None


app = FastAPI(
    title="Predictive Vehicle Service Recommendation API",
    description=(
        "Predicts the next vehicle service date and odometer milestone. "
        "Provide the optional vehicle fields (make, year, fuel_type, last_service_type) "
        "to use the expanded v2 model; omit them to fall back to v1."
    ),
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(predict.router)
app.include_router(vehicles.router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "model_v1_loaded": getattr(app.state, "model_v1", None) is not None,
        "model_v2_loaded": getattr(app.state, "model_v2", None) is not None,
    }


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "message": "Predictive Vehicle Service Recommendation API",
        "docs": "/docs",
    }
