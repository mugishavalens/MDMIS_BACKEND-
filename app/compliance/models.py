import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.types import GUID

FRAMEWORK_CHOICES = ("oecd", "itsci", "rmb", "eu")
REPORT_STATUS_CHOICES = ("draft", "submitted", "approved", "overdue")


class ComplianceReport(Base):
    """SRS Section 4.12 (Reporting & Export) / REQ-RPT-001..004."""

    __tablename__ = "compliance_reports"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("organisations.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    framework: Mapped[str] = mapped_column(String(10))
    period: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(12), default="draft")
    coverage_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    flagged_lots: Mapped[int] = mapped_column(default=0)
    submitted_to: Mapped[str] = mapped_column(String(255), default="")
    generated_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
