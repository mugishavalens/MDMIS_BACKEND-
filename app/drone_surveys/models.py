import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.types import GUID

SURVEY_STATES = ("queued", "running", "done", "failed")


class DroneSurvey(Base):
    """One drone flight's photos, turned into a 3D block by mdmis-ml-service
    (app/reconstruction there). The backend forwards the upload, follows the
    job, and when it is done keeps the result here and makes it the site's
    terrain (site_terrains), so the 3D block shows the drone survey."""

    __tablename__ = "drone_surveys"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"))
    site_id: Mapped[str] = mapped_column(String(32), ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    photo_count: Mapped[int] = mapped_column(default=0)

    ml_job_id: Mapped[str] = mapped_column(String(32), default="")
    state: Mapped[str] = mapped_column(String(10), default="queued")
    stage: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(String(300), default="")
    error: Mapped[str] = mapped_column(String(500), default="")

    # results (set once, when the job is done)
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ground: Mapped[dict | None] = mapped_column(JSON, nullable=True)   # DemGrid, bare ground
    surface: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # DemGrid, with trees/boulders
    cloud: Mapped[dict | None] = mapped_column(JSON, nullable=True)    # point sample + camera positions
    ortho: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
