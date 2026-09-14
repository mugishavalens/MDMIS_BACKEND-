from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SafetyIncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    siteId: str = Field(validation_alias="site_id")
    zoneId: Optional[UUID] = Field(default=None, validation_alias="zone_id")
    incidentType: str = Field(validation_alias="incident_type")
    riskScore: int = Field(validation_alias="risk_score")
    sensorReadings: dict = Field(validation_alias="sensor_readings")
    gpsLat: Optional[float] = Field(default=None, validation_alias="gps_lat")
    gpsLng: Optional[float] = Field(default=None, validation_alias="gps_lng")
    reportedById: Optional[UUID] = Field(default=None, validation_alias="reported_by_id")
    # Not stored columns — resolved via a join in the router, same reason
    # scans' operatorName is (reported_by_id/acknowledged_by_id are the
    # only link to accounts.models.User).
    reportedByName: Optional[str] = None
    acknowledgedById: Optional[UUID] = Field(default=None, validation_alias="acknowledged_by_id")
    acknowledgedByName: Optional[str] = None
    acknowledgedAt: Optional[datetime] = Field(default=None, validation_alias="acknowledged_at")
    status: str
    description: str
    created_at: datetime


class SafetyIncidentCreate(BaseModel):
    site_id: str
    zone_id: Optional[UUID] = None
    incident_type: str
    risk_score: int = 0
    sensor_readings: dict = {}
    gps_lat: Optional[Decimal] = None
    gps_lng: Optional[Decimal] = None
    description: str = ""


class SafetyIncidentUpdate(BaseModel):
    status: Optional[str] = None
    description: Optional[str] = None
