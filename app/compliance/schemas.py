from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ComplianceReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    framework: str
    period: str
    status: str
    coverage_pct: Decimal
    flagged_lots: int
    submitted_to: str
    generated_by_id: Optional[UUID] = None
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
