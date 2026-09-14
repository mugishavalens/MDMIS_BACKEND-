from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConfidenceAlternative(BaseModel):
    mineral: str
    probability: float


class MineralZoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    scanSessionId: UUID = Field(validation_alias="scan_session_id")
    mineral: str = Field(validation_alias="mineral_type")
    confidence: int = Field(validation_alias="confidence_score")
    alternatives: list[ConfidenceAlternative] = Field(default_factory=list, validation_alias="confidence_alternatives")
    gradePct: Optional[float] = Field(default=None, validation_alias="grade_pct")
    areaHa: Optional[float] = Field(default=None, validation_alias="area_ha")
    estimatedDepthM: Optional[float] = Field(default=None, validation_alias="estimated_depth_m")
    estimatedTonnage: Optional[float] = Field(default=None, validation_alias="estimated_tonnage")
    status: str
    flaggedAnomaly: bool = Field(validation_alias="flagged_anomaly")
    created_at: datetime


class MineralZoneCreate(BaseModel):
    scan_session_id: UUID
    mineral_type: str
    confidence_score: int = 0
    confidence_alternatives: list[ConfidenceAlternative] = []
    grade_pct: Optional[Decimal] = None
    area_ha: Optional[Decimal] = None
    estimated_depth_m: Optional[Decimal] = None
    estimated_tonnage: Optional[Decimal] = None
    status: str = "unconfirmed"
    flagged_anomaly: bool = False


class MineralZoneUpdate(BaseModel):
    confidence_score: Optional[int] = None
    confidence_alternatives: Optional[list[ConfidenceAlternative]] = None
    grade_pct: Optional[Decimal] = None
    area_ha: Optional[Decimal] = None
    estimated_depth_m: Optional[Decimal] = None
    estimated_tonnage: Optional[Decimal] = None
    status: Optional[str] = None
    flagged_anomaly: Optional[bool] = None


class ScanSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    siteId: str = Field(validation_alias="site_id")
    operatorId: Optional[UUID] = Field(default=None, validation_alias="operator_id")
    # Not a stored column — resolved via a join in the router (operator_id
    # is the only link to accounts.models.User, and the frontend has no
    # other legitimate way to look up a user's display name).
    operatorName: Optional[str] = None
    sensorTypes: list = Field(validation_alias="sensor_types")
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
