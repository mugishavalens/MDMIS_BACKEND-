from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CustodyEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID
    event_type: str
    from_party: str
    to_party: str
    gps_lat: Optional[Decimal] = None
    gps_lng: Optional[Decimal] = None
    quantity_kg: Decimal
    authorised_by_id: Optional[UUID] = None
    timestamp: datetime
    notes: str


class CustodyEventCreate(BaseModel):
    batch_id: UUID
    event_type: str
    from_party: str = ""
    to_party: str = ""
    gps_lat: Optional[Decimal] = None
    gps_lng: Optional[Decimal] = None
    quantity_kg: Decimal = Decimal("0")
    notes: str = ""


class MineralBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    coc_id: str
    site_id: str
    mineral_type: str
    origin_lat: Optional[Decimal] = None
    origin_lng: Optional[Decimal] = None
    extraction_timestamp: Optional[datetime] = None
    weight_kg: Decimal
    grade_detected: Optional[Decimal] = None
    grade_confirmed: Optional[Decimal] = None
    status: str
    qr_code_url: str
    created_by_id: Optional[UUID] = None
    created_at: datetime
    events: list[CustodyEventOut] = []


class MineralBatchCreate(BaseModel):
    site_id: str
    mineral_type: str
    origin_lat: Optional[Decimal] = None
    origin_lng: Optional[Decimal] = None
    extraction_timestamp: Optional[datetime] = None
    weight_kg: Decimal = Decimal("0")
    grade_detected: Optional[Decimal] = None
    grade_confirmed: Optional[Decimal] = None
    status: str = "scanned"
    qr_code_url: str = ""


class MineralBatchUpdate(BaseModel):
    grade_detected: Optional[Decimal] = None
    grade_confirmed: Optional[Decimal] = None
    status: Optional[str] = None
    qr_code_url: Optional[str] = None
