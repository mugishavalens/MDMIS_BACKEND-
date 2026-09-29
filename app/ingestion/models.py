import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.types import GUID

# Survey sensors (SRS 4.1.1) plus the live-telemetry kinds the safety rules
# need (REQ-SAFE-001: gas, slope/instability).
DEVICE_SENSOR_CHOICES = (
    "hyperspectral", "gpr", "em", "magnetometer", "gamma", "satellite", "lab", "gas", "geotechnical",
)
UPLOAD_METHOD_CHOICES = ("manual", "api")
FILE_STATUS_CHOICES = ("validated", "rejected")


class SensorDevice(Base):
    """A physical sensor/gateway allowed to push data straight into MDMIS
    with its own API key — no human login involved."""

    __tablename__ = "sensor_devices"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[str] = mapped_column(String(32), ForeignKey("sites.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    sensor_type: Mapped[str] = mapped_column(String(20))
    # sha256 of the key; the key itself is shown once at creation/rotation.
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    api_key_prefix: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_values: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SensorFile(Base):
    """One uploaded sensor file — and the immutable ingestion log entry
    (REQ-ING-004) for it, including rejected uploads."""

    __tablename__ = "sensor_files"
    __table_args__ = (Index("ix_sensor_files_org_created", "organisation_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"))
    site_id: Mapped[str] = mapped_column(String(32), ForeignKey("sites.id", ondelete="CASCADE"))
    scan_session_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("scan_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sensor_type: Mapped[str] = mapped_column(String(20))
    original_filename: Mapped[str] = mapped_column(String(255))
    file_kind: Mapped[str | None] = mapped_column(String(12), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)  # null when rejected
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [min_lng, min_lat, max_lng, max_lat]
    file_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12))
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    validation_warnings: Mapped[list] = mapped_column(JSON, default=list)
    upload_method: Mapped[str] = mapped_column(String(8))
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("sensor_devices.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SensorReading(Base):
    """One timestamped measurement set pushed by a device, e.g.
    {"co_ppm": 12, "ch4_pct_lel": 2.1}. Append-only time series."""

    __tablename__ = "sensor_readings"
    __table_args__ = (
        Index("ix_sensor_readings_device_recorded", "device_id", "recorded_at"),
        Index("ix_sensor_readings_site_recorded", "site_id", "recorded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("sensor_devices.id", ondelete="CASCADE"))
    site_id: Mapped[str] = mapped_column(String(32), ForeignKey("sites.id", ondelete="CASCADE"))
    sensor_type: Mapped[str] = mapped_column(String(20))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    values: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
