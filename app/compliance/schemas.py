from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    framework: str
    period: str
    status: str = "draft"
    coverage_pct: Decimal = Decimal("0")
    flagged_lots: int = 0
    submitted_to: str = ""


class ComplianceReportUpdate(BaseModel):
    status: Optional[str] = None
    coverage_pct: Optional[Decimal] = None
    flagged_lots: Optional[int] = None
    submitted_to: Optional[str] = None
