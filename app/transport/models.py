import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.types import GUID

SHIPMENT_STATUS_CHOICES = ("loading", "in-transit", "delayed", "delivered")


class Shipment(Base):
    """SRS Section 4.10 (Transportation Tracking) / REQ-TRANS-001."""

    __tablename__ = "shipments"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("mineral_batches.id", ondelete="SET NULL"), nullable=True)

    origin_name: Mapped[str] = mapped_column(String(255))
    origin_lat: Mapped[float] = mapped_column(Numeric(9, 6))
    origin_lng: Mapped[float] = mapped_column(Numeric(9, 6))
    destination_name: Mapped[str] = mapped_column(String(255))
    destination_lat: Mapped[float] = mapped_column(Numeric(9, 6))
    destination_lng: Mapped[float] = mapped_column(Numeric(9, 6))

    driver: Mapped[str] = mapped_column(String(255), default="")
    vehicle: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(12), default="loading")
    progress_pct: Mapped[int] = mapped_column(default=0)
    eta_hours: Mapped[float] = mapped_column(Numeric(6, 1), default=0)
    weight_kg: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    gps_integrity: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
