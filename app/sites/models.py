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
    last_scan_method: Mapped[str] = mapped_column(String(50), default="")
    depth_meters: Mapped[int] = mapped_column(default=0)
    # Attribution for sites imported from outside data (e.g. "IPIS open data
    # (ODC-BY 1.0)"). Licences like ODC-BY require the credit wherever the
    # site is shown, so the frontend displays it. Empty for MDMIS's own sites.
    data_source: Mapped[str] = mapped_column(String(200), default="", server_default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SiteTerrain(Base):
    """The 3D block's ground surface for one site, in the frontend's DemGrid
    shape (row 0 = south, col 0 = west; see the frontend's lib/dem-fetcher.ts).

    Produced by mdmis-ml-service (scripts/ingest_terrain.py: Copernicus DEM
    or a drone survey) and stored here, so serving the 3D block needs only
    the backend and its database. Before this table the backend proxied
    every request to the ML service, which the deployed app can't reach.
    Load with: python -m app.import_terrain --dir <mdmis-ml-service>/data/terrain
    """

    __tablename__ = "site_terrains"

    site_id: Mapped[str] = mapped_column(String(32), ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True)
    grid: Mapped[dict] = mapped_column(JSON)
    # e.g. "Copernicus GLO-30 DSM" — shown under the block so viewers know
    # what the surface is (a DSM measures canopy height over forest).
    source: Mapped[str] = mapped_column(String(200), default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
