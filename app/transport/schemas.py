from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ShipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: Optional[UUID] = None
    origin_name: str
    origin_lat: Decimal
    origin_lng: Decimal
    destination_name: str
    destination_lat: Decimal
    destination_lng: Decimal
    driver: str
    vehicle: str
    status: str
    progress_pct: int
    eta_hours: Decimal
    weight_kg: Decimal
    gps_integrity: bool
    created_at: datetime
    updated_at: datetime


class ShipmentCreate(BaseModel):
    batch_id: Optional[UUID] = None
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
