import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.types import GUID

INCIDENT_TYPE_CHOICES = (
    "gas_threshold", "structural_instability", "slope_failure", "equipment", "proximity_breach", "environmental", "other",
)
INCIDENT_STATUS_CHOICES = ("open", "acknowledged", "resolved", "escalated")


class SafetyIncident(Base):
    """SRS Section 7.5 / REQ-SAFE-004."""

    __tablename__ = "safety_incidents"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"))
    site_id: Mapped[str] = mapped_column(String(32), ForeignKey("sites.id", ondelete="CASCADE"))
    zone_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("mineral_zones.id", ondelete="SET NULL"), nullable=True)

    incident_type: Mapped[str] = mapped_column(String(30))
    risk_score: Mapped[int] = mapped_column(default=0)
    sensor_readings: Mapped[dict] = mapped_column(JSON, default=dict)
    gps_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    gps_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)

    reported_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
