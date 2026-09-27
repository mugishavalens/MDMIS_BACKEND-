"""Transportation tracking: shipments, their GPS trail and status timeline,
plus the vehicle/driver registry they're assigned from.

Hand-written rather than the generic CRUD factory because shipments carry
real business rules — status transitions, vehicle/driver availability,
capacity checks, and the dispatch/receipt custody events a shipment
writes onto its mineral batch's chain of custody.

Vehicles and drivers live under their own top-level prefixes (not nested
under /transport) so "/transport/vehicles" can never be mis-routed as a
shipment id lookup — same reasoning as traceability's split routers.
"""
import math
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.database import get_db
from app.deps import get_current_user, require_role
from app.sites.models import Site
from app.traceability.models import CustodyEvent, MineralBatch

from .models import ACTIVE_SHIPMENT_STATUSES, Driver, Shipment, ShipmentEvent, ShipmentPing, Vehicle
from .schemas import (
    DriverCreate,
    DriverOut,
    DriverUpdate,
    LastPing,
    PingCreate,
    PingOut,
    ShipmentCreate,
    ShipmentDetailOut,
    ShipmentEventOut,
    ShipmentOut,
    ShipmentStatusChange,
    ShipmentUpdate,
    VehicleCreate,
    VehicleOut,
    VehicleUpdate,
)

router = APIRouter(prefix="/transport", tags=["transport"])
vehicle_router = APIRouter(prefix="/vehicles", tags=["transport"])
driver_router = APIRouter(prefix="/drivers", tags=["transport"])

# Dispatchers: the roles that may create shipments, change their status,
# log positions and manage the fleet. system_admin always passes.
require_dispatcher = require_role("mine_manager", "org_admin")

# An in-motion shipment with no position report for this long is treated
# as having lost GPS integrity.
GPS_LOSS_MINUTES = 15
# Used for ETA when a ping carries no (or a near-zero) speed reading.
_DEFAULT_SPEED_KMH = 45.0

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "loading": {"in-transit"},
    "in-transit": {"delayed", "delivered"},
    "delayed": {"in-transit", "delivered"},
    "delivered": set(),
}


def _scope(query, model, user: User):
    if user.role == "system_admin":
        return query
    return query.where(model.organisation_id == user.organisation_id)


def _require_org(user: User):
    if user.organisation_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account has no organisation.")
    return user.organisation_id


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _reference(s: Shipment) -> str:
    return s.reference or f"SHP-{str(s.id)[:8].upper()}"


def _build_out(s: Shipment, batch_code: str | None, now: datetime | None = None) -> ShipmentOut:
    now = now or datetime.now(timezone.utc)
    gps_ok = s.gps_integrity
    signal_age = None
    last_ping = None
    if s.last_ping_at is not None:
        last_ping = LastPing(lat=float(s.last_lat), lng=float(s.last_lng), at=s.last_ping_at)
        signal_age = int((now - s.last_ping_at).total_seconds() // 60)
        if s.status in ("in-transit", "delayed"):
            gps_ok = signal_age <= GPS_LOSS_MINUTES
    return ShipmentOut.model_validate(s).model_copy(update={
        "reference": _reference(s),
        "batchCode": batch_code,
        "gpsIntegrity": gps_ok,
        "lastPing": last_ping,
        "signalAgeMinutes": signal_age,
    })


def _shipment_query():
    return select(Shipment, MineralBatch.coc_id).outerjoin(MineralBatch, Shipment.batch_id == MineralBatch.id)


async def _get_shipment(db: AsyncSession, user: User, shipment_id: UUID) -> tuple[Shipment, str | None]:
    row = (await db.execute(_scope(_shipment_query().where(Shipment.id == shipment_id), Shipment, user))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shipment not found.")
    return row[0], row[1]


def _add_event(db: AsyncSession, s: Shipment, user: User, event_type: str, note: str = "") -> None:
    db.add(ShipmentEvent(shipment_id=s.id, event_type=event_type, note=note, actor_name=user.full_name))


async def _active_shipment_for(db: AsyncSession, column, value) -> Shipment | None:
    return (
        await db.execute(
            select(Shipment).where(column == value, Shipment.status.in_(ACTIVE_SHIPMENT_STATUSES)).limit(1)
        )
    ).scalar_one_or_none()


# ---- Shipments ---------------------------------------------------------------


@router.get("/", response_model=list[ShipmentOut])
async def list_shipments(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        await db.execute(_scope(_shipment_query(), Shipment, user).order_by(Shipment.created_at.desc()))
    ).all()
    now = datetime.now(timezone.utc)
    return [_build_out(s, code, now) for s, code in rows]


@router.get("/{shipment_id}", response_model=ShipmentDetailOut)
async def get_shipment(shipment_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    s, code = await _get_shipment(db, user, shipment_id)
    pings = (
        await db.execute(
            select(ShipmentPing).where(ShipmentPing.shipment_id == s.id).order_by(ShipmentPing.recorded_at)
        )
    ).scalars().all()
    events = (
        await db.execute(
            select(ShipmentEvent).where(ShipmentEvent.shipment_id == s.id).order_by(ShipmentEvent.created_at)
        )
    ).scalars().all()
    return ShipmentDetailOut(
        **_build_out(s, code).model_dump(),
        pings=[PingOut.model_validate(p) for p in pings],
        events=[ShipmentEventOut.model_validate(e) for e in events],
    )


@router.post("/", response_model=ShipmentOut, status_code=status.HTTP_201_CREATED)
async def create_shipment(
    payload: ShipmentCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_dispatcher)
):
    org_id = _require_org(user)
    data = payload.model_dump()
    batch_code = None

    if payload.batch_id is not None:
        batch = (
            await db.execute(_scope(select(MineralBatch).where(MineralBatch.id == payload.batch_id), MineralBatch, user))
        ).scalar_one_or_none()
        if batch is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Mineral batch not found.")
        if await _active_shipment_for(db, Shipment.batch_id, batch.id):
            raise HTTPException(status.HTTP_409_CONFLICT, f"Batch {batch.coc_id} is already on an active shipment.")
        batch_code = batch.coc_id
        site = await db.get(Site, batch.site_id)
        if data["mineral_type"] is None:
            data["mineral_type"] = batch.mineral_type
        if data["weight_kg"] is None:
            data["weight_kg"] = batch.weight_kg
        if data["origin_lat"] is None and site is not None:
            data["origin_name"] = data["origin_name"] or site.name
            data["origin_lat"], data["origin_lng"] = site.lat, site.lng

    if not data["origin_name"] or data["origin_lat"] is None or data["origin_lng"] is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Origin is required when no batch is selected.")

    weight = float(data["weight_kg"] or 0)

    if payload.vehicle_id is not None:
        vehicle = (
            await db.execute(_scope(select(Vehicle).where(Vehicle.id == payload.vehicle_id), Vehicle, user))
        ).scalar_one_or_none()
        if vehicle is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found.")
        if vehicle.status != "available":
            raise HTTPException(status.HTTP_409_CONFLICT, f"{vehicle.name} is {vehicle.status}.")
        busy = await _active_shipment_for(db, Shipment.vehicle_id, vehicle.id)
        if busy:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{vehicle.name} is already on shipment {_reference(busy)}.")
        if vehicle.capacity_kg and weight > float(vehicle.capacity_kg):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{weight:,.0f} kg exceeds {vehicle.name}'s capacity of {float(vehicle.capacity_kg):,.0f} kg.",
            )
        data["vehicle"] = vehicle.name

    if payload.driver_id is not None:
        driver = (
            await db.execute(_scope(select(Driver).where(Driver.id == payload.driver_id), Driver, user))
        ).scalar_one_or_none()
        if driver is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver not found.")
        if driver.status != "active":
            raise HTTPException(status.HTTP_409_CONFLICT, f"{driver.full_name} is inactive.")
        busy = await _active_shipment_for(db, Shipment.driver_id, driver.id)
        if busy:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"{driver.full_name} is already on shipment {_reference(busy)}."
            )
        data["driver"] = driver.full_name

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"SHP-{today}"
    count = await db.scalar(select(func.count()).select_from(Shipment).where(Shipment.reference.like(f"{prefix}%")))

    note = data.pop("note")
    shipment = Shipment(
        **{k: v for k, v in data.items() if v is not None},
        reference=f"{prefix}-{(count or 0) + 1:04d}",
        organisation_id=org_id,
        status="loading",
        progress_pct=0,
    )
    db.add(shipment)
    await db.flush()
    _add_event(db, shipment, user, "created", note)
    await db.commit()
    await db.refresh(shipment)
    return _build_out(shipment, batch_code)


@router.patch("/{shipment_id}", response_model=ShipmentOut)
async def update_shipment(
    shipment_id: UUID,
    payload: ShipmentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_dispatcher),
):
    s, code = await _get_shipment(db, user, shipment_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(s, field, value)
    await db.commit()
    await db.refresh(s)
    return _build_out(s, code)


@router.post("/{shipment_id}/status", response_model=ShipmentOut)
async def change_status(
    shipment_id: UUID,
    payload: ShipmentStatusChange,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_dispatcher),
):
    s, code = await _get_shipment(db, user, shipment_id)
    new, old = payload.status, s.status
    if new not in _ALLOWED_TRANSITIONS.get(old, set()):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Can't change a {old} shipment to {new}.")

    now = datetime.now(timezone.utc)
    s.status = new
    ref = _reference(s)
    carrier = " / ".join(p for p in (s.driver, s.vehicle) if p) or "Carrier"

    if old == "loading" and new == "in-transit":
        s.departed_at = now
        _add_event(db, s, user, "departed", payload.note)
        if s.batch_id is not None:
            db.add(CustodyEvent(
                batch_id=s.batch_id, event_type="dispatch", from_party=s.origin_name, to_party=carrier,
                gps_lat=s.origin_lat, gps_lng=s.origin_lng, quantity_kg=s.weight_kg,
                authorised_by_id=user.id, notes=f"Auto-recorded: shipment {ref} departed.",
            ))
    elif new == "delayed":
        _add_event(db, s, user, "delayed", payload.note)
    elif old == "delayed" and new == "in-transit":
        _add_event(db, s, user, "resumed", payload.note)
    elif new == "delivered":
        s.delivered_at = now
        s.progress_pct = 100
        s.eta_hours = 0
        _add_event(db, s, user, "delivered", payload.note)
        if s.batch_id is not None:
            db.add(CustodyEvent(
                batch_id=s.batch_id, event_type="receipt", from_party=carrier, to_party=s.destination_name,
                gps_lat=s.destination_lat, gps_lng=s.destination_lng, quantity_kg=s.weight_kg,
                authorised_by_id=user.id, notes=f"Auto-recorded: shipment {ref} delivered.",
            ))

    await db.commit()
    await db.refresh(s)
    return _build_out(s, code)


@router.post("/{shipment_id}/pings", response_model=ShipmentOut, status_code=status.HTTP_201_CREATED)
async def record_ping(
    shipment_id: UUID,
    payload: PingCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_dispatcher),
):
    s, code = await _get_shipment(db, user, shipment_id)
    if s.status not in ("in-transit", "delayed"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Positions can only be logged for shipments on the road.")

    lat, lng = float(payload.lat), float(payload.lng)
    now = datetime.now(timezone.utc)
    db.add(ShipmentPing(
        shipment_id=s.id, lat=payload.lat, lng=payload.lng, speed_kmh=payload.speed_kmh,
        source=payload.source, recorded_by_id=user.id, recorded_at=now,
    ))
    s.last_ping_at, s.last_lat, s.last_lng = now, payload.lat, payload.lng
    s.gps_integrity = True

    # Straight-line estimate: share of the origin→destination distance
    # covered so far, and time to cover the rest at the reported speed.
    done = _haversine_km(float(s.origin_lat), float(s.origin_lng), lat, lng)
    left = _haversine_km(lat, lng, float(s.destination_lat), float(s.destination_lng))
    if done + left > 0:
        s.progress_pct = max(0, min(99, round(100 * done / (done + left))))
    speed = float(payload.speed_kmh) if payload.speed_kmh and payload.speed_kmh > 5 else _DEFAULT_SPEED_KMH
    s.eta_hours = round(left / speed, 1)

    await db.commit()
    await db.refresh(s)
    return _build_out(s, code, now)


# ---- Vehicles ------------------------------------------------------------------


async def _active_assignments(db: AsyncSession, user: User, column) -> dict:
    """{vehicle_id or driver_id: (shipment_id, reference)} for active shipments."""
    rows = (
        await db.execute(
            _scope(select(column, Shipment.id, Shipment.reference), Shipment, user)
            .where(column.isnot(None), Shipment.status.in_(ACTIVE_SHIPMENT_STATUSES))
        )
    ).all()
    return {key: (sid, ref or f"SHP-{str(sid)[:8].upper()}") for key, sid, ref in rows}


def _vehicle_out(v: Vehicle, assignments: dict) -> VehicleOut:
    current = assignments.get(v.id)
    return VehicleOut.model_validate(v).model_copy(update={
        "currentShipmentId": current[0] if current else None,
        "currentShipmentRef": current[1] if current else None,
    })


async def _get_vehicle(db: AsyncSession, user: User, vehicle_id: UUID) -> Vehicle:
    v = (await db.execute(_scope(select(Vehicle).where(Vehicle.id == vehicle_id), Vehicle, user))).scalar_one_or_none()
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found.")
    return v


@vehicle_router.get("/", response_model=list[VehicleOut])
async def list_vehicles(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    vehicles = (await db.execute(_scope(select(Vehicle), Vehicle, user).order_by(Vehicle.name))).scalars().all()
    assignments = await _active_assignments(db, user, Shipment.vehicle_id)
    return [_vehicle_out(v, assignments) for v in vehicles]


@vehicle_router.post("/", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    payload: VehicleCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_dispatcher)
):
    org_id = _require_org(user)
    plate = payload.plate.strip().upper()
    dup = await db.scalar(
        select(func.count()).select_from(Vehicle).where(Vehicle.organisation_id == org_id, Vehicle.plate == plate)
    )
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A vehicle with plate {plate} already exists.")
    v = Vehicle(**payload.model_dump(exclude={"plate"}), plate=plate, organisation_id=org_id)
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return _vehicle_out(v, {})


@vehicle_router.patch("/{vehicle_id}", response_model=VehicleOut)
async def update_vehicle(
    vehicle_id: UUID, payload: VehicleUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(require_dispatcher)
):
    v = await _get_vehicle(db, user, vehicle_id)
    updates = payload.model_dump(exclude_unset=True)
    busy = await _active_shipment_for(db, Shipment.vehicle_id, v.id)
    if busy and updates.get("status") in ("maintenance", "retired"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{v.name} is on shipment {_reference(busy)}.")
    if "plate" in updates:
        updates["plate"] = updates["plate"].strip().upper()
    for field, value in updates.items():
        setattr(v, field, value)
    await db.commit()
    await db.refresh(v)
    return _vehicle_out(v, {v.id: (busy.id, _reference(busy))} if busy else {})


# ---- Drivers -------------------------------------------------------------------


def _driver_out(d: Driver, assignments: dict) -> DriverOut:
    current = assignments.get(d.id)
    return DriverOut.model_validate(d).model_copy(update={
        "currentShipmentId": current[0] if current else None,
        "currentShipmentRef": current[1] if current else None,
    })


@driver_router.get("/", response_model=list[DriverOut])
async def list_drivers(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    drivers = (await db.execute(_scope(select(Driver), Driver, user).order_by(Driver.full_name))).scalars().all()
    assignments = await _active_assignments(db, user, Shipment.driver_id)
    return [_driver_out(d, assignments) for d in drivers]


@driver_router.post("/", response_model=DriverOut, status_code=status.HTTP_201_CREATED)
async def create_driver(
    payload: DriverCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_dispatcher)
):
    d = Driver(**payload.model_dump(), organisation_id=_require_org(user))
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return _driver_out(d, {})


@driver_router.patch("/{driver_id}", response_model=DriverOut)
async def update_driver(
    driver_id: UUID, payload: DriverUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(require_dispatcher)
):
    d = (await db.execute(_scope(select(Driver).where(Driver.id == driver_id), Driver, user))).scalar_one_or_none()
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver not found.")
    updates = payload.model_dump(exclude_unset=True)
    busy = await _active_shipment_for(db, Shipment.driver_id, d.id)
    if busy and updates.get("status") == "inactive":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{d.full_name} is on shipment {_reference(busy)}.")
    for field, value in updates.items():
        setattr(d, field, value)
    await db.commit()
    await db.refresh(d)
    return _driver_out(d, {d.id: (busy.id, _reference(busy))} if busy else {})
