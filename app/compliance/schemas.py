from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .models import FRAMEWORK_CHOICES, REPORT_STATUS_CHOICES

Framework = Literal[FRAMEWORK_CHOICES]
ReportStatus = Literal[REPORT_STATUS_CHOICES]


class ComplianceReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    title: str
    framework: str
    period: str
    status: str
    coveragePct: float = Field(validation_alias="coverage_pct")
    flaggedLots: int = Field(validation_alias="flagged_lots")
    submittedTo: str = Field(validation_alias="submitted_to")
    created_at: datetime
    updated_at: datetime


class ComplianceReportCreate(BaseModel):
    title: str
    framework: Framework
    period: str
    status: ReportStatus = "draft"
    coverage_pct: Decimal = Decimal("0")
    flagged_lots: int = 0
    submitted_to: str = ""


class ComplianceReportUpdate(BaseModel):
    status: Optional[ReportStatus] = None
    coverage_pct: Optional[Decimal] = None
    flagged_lots: Optional[int] = None
    submitted_to: Optional[str] = None
