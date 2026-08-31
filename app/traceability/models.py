import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.types import GUID

BATCH_STATUS_CHOICES = (
    "scanned", "weighed", "graded", "in_storage", "in_transit", "at_processing", "exported", "rejected",
)
CUSTODY_EVENT_CHOICES = (
    "extraction", "weigh_in", "storage_in", "dispatch", "waypoint", "receipt", "processing", "export", "rejection",
)


class MineralBatch(Base):
    """SRS Section 7.3 / REQ-TRACE-001. coc_id format:
    COC-{SITE_CODE}-{YYYYMMDD}-{SEQUENCE}, immutable once assigned."""

    __tablename__ = "mineral_batches"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    coc_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"))
    site_id: Mapped[str] = mapped_column(String(32), ForeignKey("sites.id", ondelete="CASCADE"))
    mineral_type: Mapped[str] = mapped_column(String(20))

    origin_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    origin_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    extraction_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    weight_kg: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    grade_detected: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    grade_confirmed: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="scanned")
    qr_code_url: Mapped[str] = mapped_column(String(500), default="")

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    events: Mapped[list["CustodyEvent"]] = relationship(back_populates="batch", lazy="selectin")


class CustodyEvent(Base):
    """SRS Section 7.4 / REQ-TRACE-003: immutable once created — no update
    or delete endpoint is exposed; corrections must be new events."""

    __tablename__ = "custody_events"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("mineral_batches.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(20))
    from_party: Mapped[str] = mapped_column(String(255), default="")
    to_party: Mapped[str] = mapped_column(String(255), default="")
    gps_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    gps_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    quantity_kg: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    authorised_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    notes: Mapped[str] = mapped_column(Text, default="")

    batch: Mapped["MineralBatch"] = relationship(back_populates="events")
