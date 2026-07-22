from datetime import date

from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Vehicle(Base):
    """
    A vehicle.

    ``id`` is the external identifier already used throughout the API and
    existing demo data (e.g. "V001") - kept as the primary key so routes and
    the legacy JSON import can address rows without an extra lookup table.
    """

    __tablename__ = "vehicles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    make: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String, nullable=True)
    registered_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    service_history: Mapped[list["ServiceHistory"]] = relationship(  # noqa: F821
        "ServiceHistory", back_populates="vehicle", cascade="all, delete-orphan"
    )
    predictions: Mapped[list["Prediction"]] = relationship(  # noqa: F821
        "Prediction", back_populates="vehicle", cascade="all, delete-orphan"
    )
