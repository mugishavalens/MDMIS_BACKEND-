from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ShipmentStatus = Literal["loading", "in-transit", "delayed", "delivered"]


class LastPing(BaseModel):
    lat: float
    lng: float
    at: datetime


class ShipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    # Derived fields below are filled in by the router's _build_out.
    reference: Optional[str] = None
    lotId: Optional[UUID] = Field(default=None, validation_alias="batch_id")
    batchCode: Optional[str] = None
    vehicleId: Optional[UUID] = Field(default=None, validation_alias="vehicle_id")
    driverId: Optional[UUID] = Field(default=None, validation_alias="driver_id")
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
    gpsIntegrity: bool = True
    lastPing: Optional[LastPing] = None
    signalAgeMinutes: Optional[int] = None
    departedAt: Optional[datetime] = Field(default=None, validation_alias="departed_at")
    deliveredAt: Optional[datetime] = Field(default=None, validation_alias="delivered_at")
    created_at: datetime
    updated_at: datetime


class PingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    lat: float
    lng: float
    speedKmh: Optional[float] = Field(default=None, validation_alias="speed_kmh")
    source: str
    recordedAt: datetime = Field(validation_alias="recorded_at")


class ShipmentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    eventType: str = Field(validation_alias="event_type")
    note: str
    actorName: str = Field(validation_alias="actor_name")
    createdAt: datetime = Field(validation_alias="created_at")


class ShipmentDetailOut(ShipmentOut):
    pings: list[PingOut] = []
    events: list[ShipmentEventOut] = []


class ShipmentCreate(BaseModel):
    batch_id: Optional[UUID] = None
    vehicle_id: Optional[UUID] = None
    driver_id: Optional[UUID] = None
    # Filled from the batch (mineral, weight) and its site (origin) when a
    # batch is given and these are omitted.
    mineral_type: Optional[str] = None
    weight_kg: Optional[Decimal] = Field(default=None, ge=0)
    origin_name: Optional[str] = None
    origin_lat: Optional[Decimal] = Field(default=None, ge=-90, le=90)
    origin_lng: Optional[Decimal] = Field(default=None, ge=-180, le=180)
    destination_name: str = Field(min_length=1)
    destination_lat: Decimal = Field(ge=-90, le=90)
    destination_lng: Decimal = Field(ge=-180, le=180)
    eta_hours: Decimal = Field(default=Decimal("0"), ge=0)
    # Free-text fallbacks for when no registered vehicle/driver is chosen.
    driver: str = ""
    vehicle: str = ""
    note: str = ""


class ShipmentUpdate(BaseModel):
    progress_pct: Optional[int] = Field(default=None, ge=0, le=100)
    eta_hours: Optional[Decimal] = Field(default=None, ge=0)
    gps_integrity: Optional[bool] = None


class ShipmentStatusChange(BaseModel):
    status: ShipmentStatus
    note: str = ""


class PingCreate(BaseModel):
    lat: Decimal = Field(ge=-90, le=90)
    lng: Decimal = Field(ge=-180, le=180)
    speed_kmh: Optional[Decimal] = Field(default=None, ge=0, le=300)
    source: Literal["device", "manual"] = "manual"


# ---- Vehicles & drivers ------------------------------------------------------


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    plate: str
    vehicleType: str = Field(validation_alias="vehicle_type")
    capacityKg: float = Field(validation_alias="capacity_kg")
    status: str
    currentShipmentId: Optional[UUID] = None
    currentShipmentRef: Optional[str] = None
    created_at: datetime


class VehicleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    plate: str = Field(min_length=1, max_length=20)
    vehicle_type: Literal["truck", "pickup", "trailer", "van", "other"] = "truck"
    capacity_kg: Decimal = Field(default=Decimal("0"), ge=0)


class VehicleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    plate: Optional[str] = Field(default=None, min_length=1, max_length=20)
    vehicle_type: Optional[Literal["truck", "pickup", "trailer", "van", "other"]] = None
    capacity_kg: Optional[Decimal] = Field(default=None, ge=0)
    status: Optional[Literal["available", "maintenance", "retired"]] = None


class DriverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    fullName: str = Field(validation_alias="full_name")
    phone: str
    licenseNo: str = Field(validation_alias="license_no")
    status: str
    currentShipmentId: Optional[UUID] = None
    currentShipmentRef: Optional[str] = None
    created_at: datetime


class DriverCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    phone: str = ""
    license_no: str = ""


class DriverUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    phone: Optional[str] = None
    license_no: Optional[str] = None
    status: Optional[Literal["active", "inactive"]] = None
