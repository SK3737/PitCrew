"""
Data access for Prediction rows.

Not explicitly named in the phase's file list, but routers must stay thin
(no ORM construction in routers) and a `Prediction` model with nowhere to
persist it would leave 1.9's audit-trail requirement with no home.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prediction import Prediction


class PredictionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        vehicle_id: str,
        model_version: str,
        days_left: int,
        km_left: float,
    ) -> Prediction:
        prediction = Prediction(
            vehicle_id=vehicle_id,
            model_version=model_version,
            days_left=days_left,
            km_left=km_left,
        )
        self.session.add(prediction)
        await self.session.flush()
        return prediction
