from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MineralZoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scan_session_id: UUID
    mineral_type: str
    confidence_score: int
    estimated_depth_m: Optional[Decimal] = None
    estimated_tonnage: Optional[Decimal] = None
    status: str
    flagged_anomaly: bool
    created_at: datetime


class MineralZoneCreate(BaseModel):
    scan_session_id: UUID
    mineral_type: str
    confidence_score: int = 0
    estimated_depth_m: Optional[Decimal] = None
    estimated_tonnage: Optional[Decimal] = None
    status: str = "unconfirmed"
    flagged_anomaly: bool = False


class MineralZoneUpdate(BaseModel):
    confidence_score: Optional[int] = None
    estimated_depth_m: Optional[Decimal] = None
    estimated_tonnage: Optional[Decimal] = None
    status: Optional[str] = None
    flagged_anomaly: Optional[bool] = None


class ScanSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    site_id: str
    operator_id: Optional[UUID] = None
    sensor_types: list
    status: str
    uploaded_at: datetime
    processed_at: Optional[datetime] = None
    zones: list[MineralZoneOut] = []


class ScanSessionCreate(BaseModel):
    site_id: str
    sensor_types: list = []
    status: str = "uploaded"


class ScanSessionUpdate(BaseModel):
    status: Optional[str] = None
    processed_at: Optional[datetime] = None
