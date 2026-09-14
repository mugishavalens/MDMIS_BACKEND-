from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ShipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    lotId: Optional[UUID] = Field(default=None, validation_alias="batch_id")
    mineral: str = Field(default="", validation_alias="mineral_type")
    originName: str = Field(validation_alias="origin_name")
    originLat: float = Field(validation_alias="origin_lat")
    originLng: float = Field(validation_alias="origin_lng")
    destinationName: str = Field(validation_alias="destination_name")
    destinationLat: float = Field(validation_alias="destination_lat")
    destinationLng: float = Field(validation_alias="destination_lng")
    driver: str
    vehicle: str
    status: str
    progress: int = Field(validation_alias="progress_pct")
    etaHours: float = Field(validation_alias="eta_hours")
    weightKg: float = Field(validation_alias="weight_kg")
    gpsIntegrity: bool = Field(validation_alias="gps_integrity")
    created_at: datetime
    updated_at: datetime


class ShipmentCreate(BaseModel):
    batch_id: Optional[UUID] = None
    mineral_type: str = ""
    origin_name: str
    origin_lat: Decimal
    origin_lng: Decimal
    destination_name: str
    destination_lat: Decimal
    destination_lng: Decimal
    driver: str = ""
    vehicle: str = ""
    status: str = "loading"
    progress_pct: int = 0
    eta_hours: Decimal = Decimal("0")
    weight_kg: Decimal = Decimal("0")
    gps_integrity: bool = True


class ShipmentUpdate(BaseModel):
    driver: Optional[str] = None
    vehicle: Optional[str] = None
    status: Optional[str] = None
    progress_pct: Optional[int] = None
    eta_hours: Optional[Decimal] = None
    gps_integrity: Optional[bool] = None
