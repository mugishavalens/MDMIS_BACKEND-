from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SafetyIncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    site_id: str
    zone_id: Optional[UUID] = None
    incident_type: str
    risk_score: int
    sensor_readings: dict
    gps_lat: Optional[Decimal] = None
    gps_lng: Optional[Decimal] = None
    reported_by_id: Optional[UUID] = None
    acknowledged_by_id: Optional[UUID] = None
    acknowledged_at: Optional[datetime] = None
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
