import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.types import GUID

SHIPMENT_STATUS_CHOICES = ("loading", "in-transit", "delayed", "delivered")
# Shipments in these states occupy their vehicle/driver.
ACTIVE_SHIPMENT_STATUSES = ("loading", "in-transit", "delayed")

VEHICLE_TYPE_CHOICES = ("truck", "pickup", "trailer", "van", "other")
# "on trip" isn't stored — it's derived from whether an active shipment
# references the vehicle, so it can never drift from reality.
VEHICLE_STATUS_CHOICES = ("available", "maintenance", "retired")
DRIVER_STATUS_CHOICES = ("active", "inactive")

PING_SOURCE_CHOICES = ("device", "manual")
SHIPMENT_EVENT_CHOICES = ("created", "departed", "delayed", "resumed", "delivered", "note")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    plate: Mapped[str] = mapped_column(String(20))
    vehicle_type: Mapped[str] = mapped_column(String(12), default="truck")
    capacity_kg: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    status: Mapped[str] = mapped_column(String(12), default="available")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(32), default="")
    license_no: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(12), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Shipment(Base):
    """SRS Section 4.10 (Transportation Tracking) / REQ-TRANS-001."""

    __tablename__ = "shipments"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    # SHP-{YYYYMMDD}-{SEQUENCE}; nullable only for rows that predate it.
    reference: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("mineral_batches.id", ondelete="SET NULL"), nullable=True)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True)

    mineral_type: Mapped[str] = mapped_column(String(20), default="")

    origin_name: Mapped[str] = mapped_column(String(255))
    origin_lat: Mapped[float] = mapped_column(Numeric(9, 6))
    origin_lng: Mapped[float] = mapped_column(Numeric(9, 6))
    destination_name: Mapped[str] = mapped_column(String(255))
    destination_lat: Mapped[float] = mapped_column(Numeric(9, 6))
    destination_lng: Mapped[float] = mapped_column(Numeric(9, 6))

    # Display snapshots of the assigned vehicle/driver names, so a shipment
    # still reads correctly if the vehicle/driver record is later removed
    # (and for rows that predate the vehicle/driver registry).
    driver: Mapped[str] = mapped_column(String(255), default="")
    vehicle: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(12), default="loading")
    progress_pct: Mapped[int] = mapped_column(default=0)
    eta_hours: Mapped[float] = mapped_column(Numeric(6, 1), default=0)
    weight_kg: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    # Manually-set flag. Once a shipment reports positions, GPS integrity
    # is instead derived from how long ago the last ping arrived.
    gps_integrity: Mapped[bool] = mapped_column(Boolean, default=True)

    departed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ping_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    last_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ShipmentPing(Base):
    """One GPS position report for a shipment — the tracking trail."""

    __tablename__ = "shipment_pings"
    __table_args__ = (Index("ix_shipment_pings_shipment_recorded", "shipment_id", "recorded_at"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("shipments.id", ondelete="CASCADE"))
    lat: Mapped[float] = mapped_column(Numeric(9, 6))
    lng: Mapped[float] = mapped_column(Numeric(9, 6))
    speed_kmh: Mapped[float | None] = mapped_column(Numeric(6, 1), nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="manual")
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShipmentEvent(Base):
    """Append-only status timeline for a shipment (departed, delayed, ...)."""

    __tablename__ = "shipment_events"
    __table_args__ = (Index("ix_shipment_events_shipment_created", "shipment_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("shipments.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(12))
    note: Mapped[str] = mapped_column(Text, default="")
    actor_name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
