import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.db.session import engine
from app.routers import assistant, auth, predict, vehicles
from app.services.predictor import MODEL_V1_PATH, MODEL_V2_PATH, load_model

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


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

app.include_router(auth.router)
app.include_router(predict.router)
app.include_router(vehicles.router)
app.include_router(assistant.router)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    db_ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "model_v1_loaded": getattr(app.state, "model_v1", None) is not None,
        "model_v2_loaded": getattr(app.state, "model_v2", None) is not None,
        "db_ok": db_ok,
    }


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "message": "Predictive Vehicle Service Recommendation API",
        "docs": "/docs",
    }
