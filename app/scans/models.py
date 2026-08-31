import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.types import GUID

SENSOR_CHOICES = ("hyperspectral", "gpr", "em", "magnetometer", "gamma", "satellite", "lab")
SCAN_STATUS_CHOICES = ("uploaded", "preprocessing", "ready", "classifying", "complete", "failed")
ZONE_STATUS_CHOICES = ("unconfirmed", "geologist_reviewed", "lab_confirmed", "rejected")


class ScanSession(Base):
    """SRS Section 7.1. Created each time sensor data is uploaded for a site visit."""

    __tablename__ = "scan_sessions"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"))
    site_id: Mapped[str] = mapped_column(String(32), ForeignKey("sites.id", ondelete="CASCADE"))
    operator_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    sensor_types: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    zones: Mapped[list["MineralZone"]] = relationship(back_populates="scan_session", lazy="selectin")


class MineralZone(Base):
    """SRS Section 7.2. One record per detected mineral zone."""

    __tablename__ = "mineral_zones"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    scan_session_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("scan_sessions.id", ondelete="CASCADE"))
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"))
    mineral_type: Mapped[str] = mapped_column(String(20))
    confidence_score: Mapped[int] = mapped_column(default=0)
    estimated_depth_m: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    estimated_tonnage: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="unconfirmed")
    flagged_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    scan_session: Mapped["ScanSession"] = relationship(back_populates="zones")
