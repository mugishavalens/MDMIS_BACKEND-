from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    district: str
    lat: Decimal
    lng: Decimal
    primaryMineral: str = Field(validation_alias="primary_mineral")
    secondaryMinerals: list = Field(validation_alias="secondary_minerals")
    gradePct: Decimal = Field(validation_alias="grade_pct")
    confidence: Decimal
    estimatedTonnage: int = Field(validation_alias="estimated_tonnage")
    safetyScore: int = Field(validation_alias="safety_score")
    riskLevel: str = Field(validation_alias="risk_level")
    status: str
    lastScan: Optional[datetime] = Field(default=None, validation_alias="last_scan")
    depthMeters: int = Field(validation_alias="depth_meters")


class SiteCreate(BaseModel):
    id: str
    name: str
    district: str = ""
    country_code: str = "RW"
    lat: Decimal
    lng: Decimal
    primary_mineral: str
    secondary_minerals: list = []
    grade_pct: Decimal = Decimal("0")
    confidence: Decimal = Decimal("0")
    estimated_tonnage: int = 0
    safety_score: int = 0
    risk_level: str = "low"
    status: str = "active"
    last_scan: Optional[datetime] = None
    depth_meters: int = 0


class SiteUpdate(BaseModel):
    name: Optional[str] = None
    district: Optional[str] = None
    lat: Optional[Decimal] = None
    lng: Optional[Decimal] = None
    primary_mineral: Optional[str] = None
    secondary_minerals: Optional[list] = None
    grade_pct: Optional[Decimal] = None
    confidence: Optional[Decimal] = None
    estimated_tonnage: Optional[int] = None
    safety_score: Optional[int] = None
    risk_level: Optional[str] = None
    status: Optional[str] = None
    last_scan: Optional[datetime] = None
    depth_meters: Optional[int] = None
