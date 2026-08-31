from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.types import GUID

MINERAL_CHOICES = (
    "cassiterite", "coltan", "wolframite", "gold", "beryl",
    "lithium", "cobalt", "copper", "gemstone", "unknown",
)
RISK_CHOICES = ("low", "moderate", "high", "critical")
STATUS_CHOICES = ("active", "surveying", "flagged", "depleted")


class Site(Base):
    """REQ-SITE-001. Mining site / concession.

    Note: id IS the site_code (e.g. "RW-RTG-01") rather than a separate UUID
    + site_code pair, so it maps 1:1 with the frontend's existing site ids
    and the static terrain assets keyed by that same id.
    """

    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    organisation_id: Mapped[str] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    district: Mapped[str] = mapped_column(String(100), default="")
    country_code: Mapped[str] = mapped_column(String(2), default="RW")

    lat: Mapped[float] = mapped_column(Numeric(9, 6))
    lng: Mapped[float] = mapped_column(Numeric(9, 6))

    primary_mineral: Mapped[str] = mapped_column(String(20))
    secondary_minerals: Mapped[list] = mapped_column(JSON, default=list)
    grade_pct: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    confidence: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    estimated_tonnage: Mapped[int] = mapped_column(default=0)
    safety_score: Mapped[int] = mapped_column(default=0)
    risk_level: Mapped[str] = mapped_column(String(10), default="low")
    status: Mapped[str] = mapped_column(String(12), default="active")
    last_scan: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    depth_meters: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
