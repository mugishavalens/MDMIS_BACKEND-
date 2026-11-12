from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import MINERAL_CHOICES, RISK_CHOICES, STATUS_CHOICES

Mineral = Literal[MINERAL_CHOICES]
Risk = Literal[RISK_CHOICES]
SiteStatus = Literal[STATUS_CHOICES]
# Site ids appear in URLs and terrain folder names: keep them plain.
SITE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    district: str
    lat: float
    lng: float
    primaryMineral: str = Field(validation_alias="primary_mineral")
    secondaryMinerals: list = Field(validation_alias="secondary_minerals")
    gradePct: float = Field(validation_alias="grade_pct")
    confidence: float
    estimatedTonnage: int = Field(validation_alias="estimated_tonnage")
    safetyScore: int = Field(validation_alias="safety_score")
    riskLevel: str = Field(validation_alias="risk_level")
    status: str
    lastScan: Optional[datetime] = Field(default=None, validation_alias="last_scan")
    lastScanMethod: str = Field(default="", validation_alias="last_scan_method")
    depthMeters: int = Field(validation_alias="depth_meters")
    dataSource: str = Field(default="", validation_alias="data_source")


class SiteCreate(BaseModel):
    id: str = Field(pattern=SITE_ID_PATTERN)
    name: str
    district: str = ""
    country_code: str = Field(default="RW", pattern=r"^[A-Z]{2}$")
    lat: float
    lng: float
    primary_mineral: Mineral
    secondary_minerals: list[Mineral] = []
    grade_pct: Decimal = Decimal("0")
    confidence: Decimal = Decimal("0")
    estimated_tonnage: int = 0
    safety_score: int = 0
    risk_level: Risk = "low"
    status: SiteStatus = "active"
    last_scan: Optional[datetime] = None
    last_scan_method: str = ""
    depth_meters: int = 0
    data_source: str = ""


class SiteUpdate(BaseModel):
    name: Optional[str] = None
    district: Optional[str] = None
    lat: Optional[Decimal] = None
    lng: Optional[Decimal] = None
    primary_mineral: Optional[Mineral] = None
    secondary_minerals: Optional[list[Mineral]] = None
    grade_pct: Optional[Decimal] = None
    confidence: Optional[Decimal] = None
    estimated_tonnage: Optional[int] = None
    safety_score: Optional[int] = None
    risk_level: Optional[Risk] = None
    status: Optional[SiteStatus] = None
    last_scan: Optional[datetime] = None
    last_scan_method: Optional[str] = None
    depth_meters: Optional[int] = None
    data_source: Optional[str] = None
