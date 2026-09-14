from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CustodyEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    batchId: UUID = Field(validation_alias="batch_id")
    stage: str = Field(validation_alias="event_type")
    fromParty: str = Field(validation_alias="from_party")
    toParty: str = Field(validation_alias="to_party")
    gpsLat: Optional[float] = Field(default=None, validation_alias="gps_lat")
    gpsLng: Optional[float] = Field(default=None, validation_alias="gps_lng")
    quantityKg: float = Field(validation_alias="quantity_kg")
    timestamp: datetime
    notes: str
    flagged: bool


class CustodyEventCreate(BaseModel):
    batch_id: UUID
    event_type: str
    from_party: str = ""
    to_party: str = ""
    gps_lat: Optional[Decimal] = None
    gps_lng: Optional[Decimal] = None
    quantity_kg: Decimal = Decimal("0")
    notes: str = ""
    flagged: bool = False


class MineralBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    tagId: str = Field(validation_alias="coc_id")
    siteId: str = Field(validation_alias="site_id")
    mineral: str = Field(validation_alias="mineral_type")
    originLat: Optional[float] = Field(default=None, validation_alias="origin_lat")
    originLng: Optional[float] = Field(default=None, validation_alias="origin_lng")
    extractionTimestamp: Optional[datetime] = Field(default=None, validation_alias="extraction_timestamp")
    weightKg: float = Field(validation_alias="weight_kg")
    gradeDetected: Optional[float] = Field(default=None, validation_alias="grade_detected")
    gradeConfirmed: Optional[float] = Field(default=None, validation_alias="grade_confirmed")
    status: str
    compliant: bool
    complianceNote: str = Field(validation_alias="compliance_note")
    # Not a stored column — computed at read time from the latest custody
    # event (see traceability/router.py) since custody events are an
    # immutable append-only log, not a cached "current stage" field.
    currentStage: str = ""  # always overwritten by the router; see _build_batch_out
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
    compliant: Optional[bool] = None
    compliance_note: Optional[str] = None
