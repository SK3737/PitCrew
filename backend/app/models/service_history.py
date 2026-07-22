from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ServiceHistory(Base):
    """A single recorded service event for a vehicle."""

    __tablename__ = "service_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[str] = mapped_column(
        String, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_type: Mapped[str | None] = mapped_column(String, nullable=True)
    serviced_at: Mapped[date] = mapped_column(Date, nullable=False)
    odo_km: Mapped[float] = mapped_column(Float, nullable=False)

    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="service_history")  # noqa: F821
