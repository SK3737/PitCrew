from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Vehicle(Base):
    """
    A vehicle.

    ``id`` is the external identifier already used throughout the API and
    existing demo data (e.g. "V001") - kept as the primary key so routes and
    the legacy JSON import can address rows without an extra lookup table.

    ``owner_id`` is nullable: it's a Phase 2 addition for the "owner" role's
    row-level scoping and has no value for vehicles imported before auth
    existed (or for admin/mechanic-managed fleet vehicles with no single
    owner). ``ondelete="SET NULL"`` so deleting a user account never cascades
    into deleting vehicle/service-history data.
    """

    __tablename__ = "vehicles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    make: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String, nullable=True)
    registered_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    service_history: Mapped[list["ServiceHistory"]] = relationship(  # noqa: F821
        "ServiceHistory", back_populates="vehicle", cascade="all, delete-orphan"
    )
    predictions: Mapped[list["Prediction"]] = relationship(  # noqa: F821
        "Prediction", back_populates="vehicle", cascade="all, delete-orphan"
    )
