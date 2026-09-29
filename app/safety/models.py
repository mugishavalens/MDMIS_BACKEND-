import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.types import GUID

INCIDENT_TYPE_CHOICES = (
    "gas_threshold", "structural_instability", "slope_failure", "equipment", "proximity_breach", "environmental", "other",
)
INCIDENT_STATUS_CHOICES = ("open", "acknowledged", "resolved", "escalated")
INCIDENT_EVENT_CHOICES = ("reported", "acknowledged", "escalated", "resolved", "reopened", "note")


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
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    description: Mapped[str] = mapped_column(Text, default="")
    # Set when a sensor reading breached a SafetyRule and opened this
    # incident automatically (no human reporter).
    source_device_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("sensor_devices.id", ondelete="SET NULL"), nullable=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("safety_rules.id", ondelete="SET NULL"), nullable=True)
    source_label: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SafetyRule(Base):
    """REQ-SAFE-001: a configurable threshold on one sensor metric. site_id
    NULL applies to every site in the organisation; a site-specific rule for
    the same metric overrides it."""

    __tablename__ = "safety_rules"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("sites.id", ondelete="CASCADE"), nullable=True)
    metric: Mapped[str] = mapped_column(String(40))
    comparator: Mapped[str] = mapped_column(String(2))  # "gt" | "lt"
    threshold: Mapped[float] = mapped_column(Float)
    incident_type: Mapped[str] = mapped_column(String(30))
    risk_score: Mapped[int] = mapped_column(default=70)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IncidentEvent(Base):
    """Append-only history of an incident: every status change and note,
    with who did it and when."""

    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_incident_events_incident_created", "incident_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("safety_incidents.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(12))
    note: Mapped[str] = mapped_column(Text, default="")
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
