"""Sensor data ingestion — the two ways data enters MDMIS (REQ-ING-003):

1. Manual upload: a signed-in user uploads a sensor file in the web app.
2. Direct injection: a registered sensor device authenticates with its own
   API key (X-Device-Key header) and pushes either live readings (gas,
   slope, displacement…) or survey files, with no human involved.

Both paths share one validation pipeline and one immutable ingestion log
(SensorFile rows), and both attach files to a ScanSession for the
preprocessing → classification pipeline. Live readings are also checked
against the safety threshold rules, which can open incidents on their own.
"""
import hashlib
import os
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.audit.service import log_event
from app.config import settings
from app.database import get_db
from app.deps import get_current_user, require_role
from app.safety.rules import evaluate_readings
from app.scans.models import ScanSession
from app.security import ALGORITHM
from app.sites.models import Site

from .models import SensorDevice, SensorFile, SensorReading
from .schemas import (
    AutoIncidentOut,
    DeviceCreate,
    DeviceOut,
    DeviceSummaryOut,
    DeviceUpdate,
    DeviceWithKeyOut,
    DownloadUrlOut,
    IngestReadingsOut,
    ReadingOut,
    ReadingsBatchIn,
    SensorFileOut,
)
from .storage import DOWNLOAD_URL_TTL_SECONDS, build_key, get_storage
from .validation import SENSOR_FORMATS, validate_sensor_file

devices_router = APIRouter(prefix="/devices", tags=["ingestion"])
ingest_router = APIRouter(prefix="/ingest", tags=["ingestion"])
files_router = APIRouter(prefix="/sensor-files", tags=["ingestion"])
readings_router = APIRouter(prefix="/sensor-readings", tags=["ingestion"])

require_uploader = require_role("geologist", "mine_manager", "org_admin")
require_device_manager = require_role("mine_manager", "org_admin")

ONLINE_WINDOW = timedelta(minutes=15)
_CHUNK = 1024 * 1024
_MAX_FUTURE_SKEW = timedelta(minutes=5)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _scope(query, model, user: User):
    if user.role == "system_admin":
        return query
    return query.where(model.organisation_id == user.organisation_id)


def _require_org(user: User):
    if user.organisation_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account has no organisation.")
    return user.organisation_id


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _new_key() -> str:
    return "mdk_" + secrets.token_urlsafe(32)


def _device_out(d: SensorDevice) -> DeviceOut:
    online = d.is_active and d.last_seen_at is not None and _now() - d.last_seen_at <= ONLINE_WINDOW
    return DeviceOut.model_validate(d).model_copy(update={"online": online})


async def get_device(
    x_device_key: str | None = Header(default=None), db: AsyncSession = Depends(get_db)
) -> SensorDevice:
    """Authenticates a sensor device by its API key."""
    if not x_device_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-Device-Key header.")
    device = (
        await db.execute(select(SensorDevice).where(SensorDevice.api_key_hash == _hash_key(x_device_key)))
    ).scalar_one_or_none()
    if device is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid device key.")
    if not device.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This device has been deactivated.")
    return device


# ---- Shared file pipeline -------------------------------------------------------


def _manual_bbox(min_lat, min_lng, max_lat, max_lng) -> list[float] | None:
    parts = [min_lng, min_lat, max_lng, max_lat]
    return [float(p) for p in parts] if all(p is not None for p in parts) else None


async def _resolve_session(
    db: AsyncSession, org_id, site_id: str, sensor_type: str, scan_session_id: UUID | None, operator_id
) -> ScanSession:
    if scan_session_id is not None:
        session = (
            await db.execute(
                select(ScanSession).where(ScanSession.id == scan_session_id, ScanSession.organisation_id == org_id)
            )
        ).scalar_one_or_none()
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan session not found.")
        if session.site_id != site_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That scan session belongs to a different site.")
        if sensor_type not in session.sensor_types:
            session.sensor_types = [*session.sensor_types, sensor_type]
        return session
    session = ScanSession(
        organisation_id=org_id, site_id=site_id, operator_id=operator_id, sensor_types=[sensor_type], status="uploaded",
    )
    db.add(session)
    await db.flush()
    return session


async def _ingest_file(
    db: AsyncSession,
    *,
    upload: UploadFile,
    org_id,
    site_id: str,
    sensor_type: str,
    scan_session_id: UUID | None,
    manual_bbox: list[float] | None,
    method: str,
    user: User | None,
    device: SensorDevice | None,
):
    filename = upload.filename or "upload"
    max_bytes = settings.max_upload_mb * 1024 * 1024
    digest = hashlib.sha256()
    size = 0
    fd, tmp_path = tempfile.mkstemp(prefix="mdmis-upload-")
    try:
        with os.fdopen(fd, "wb") as tmp:
            while chunk := await upload.read(_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        f"File exceeds the {settings.max_upload_mb} MB upload limit.",
                    )
                digest.update(chunk)
                tmp.write(chunk)

        result = await run_in_threadpool(validate_sensor_file, tmp_path, filename, sensor_type, size, manual_bbox)
        record = SensorFile(
            organisation_id=org_id, site_id=site_id, sensor_type=sensor_type, original_filename=filename[:255],
            file_kind=result.kind, size_bytes=size, sha256=digest.hexdigest(), bbox=result.bbox,
            file_metadata=result.metadata, validation_errors=result.errors, validation_warnings=result.warnings,
            upload_method=method, uploaded_by_id=user.id if user else None, device_id=device.id if device else None,
            status="validated" if result.ok else "rejected",
        )
        if result.ok:
            session = await _resolve_session(
                db, org_id, site_id, sensor_type, scan_session_id, user.id if user else None
            )
            record.scan_session_id = session.id
            record.storage_key = build_key(org_id, filename)
            await run_in_threadpool(get_storage().save, record.storage_key, tmp_path)
        db.add(record)
        await db.flush()
        if user is not None:
            await log_event(
                db, user, "sensor.upload" if result.ok else "sensor.reject", "sensor_file", str(record.id),
                f"{sensor_type}: {filename}",
            )
        await db.commit()
        await db.refresh(record)
    finally:
        os.unlink(tmp_path)

    out = SensorFileOut.model_validate(record).model_copy(update={
        "uploadedByName": user.full_name if user else None,
        "deviceName": device.name if device else None,
    })
    if not result.ok:
        # REQ-ING-002: reject with a report of what failed and how to fix it.
        first = result.errors[0]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": f"{first['message']} {first['fix']}",
                "errors": result.errors,
                "file": out.model_dump(mode="json"),
            },
        )
    return out


# ---- Path 1: manual upload ------------------------------------------------------


@files_router.post("/", response_model=SensorFileOut, status_code=status.HTTP_201_CREATED)
async def upload_sensor_file(
    file: UploadFile = File(...),
    site_id: str = Form(...),
    sensor_type: str = Form(...),
    scan_session_id: UUID | None = Form(default=None),
    min_lat: float | None = Form(default=None),
    min_lng: float | None = Form(default=None),
    max_lat: float | None = Form(default=None),
    max_lng: float | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_uploader),
):
    org_id = _require_org(user)
    site = await db.get(Site, site_id)
    if site is None or (user.role != "system_admin" and site.organisation_id != org_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found.")
    return await _ingest_file(
        db, upload=file, org_id=org_id, site_id=site_id, sensor_type=sensor_type, scan_session_id=scan_session_id,
        manual_bbox=_manual_bbox(min_lat, min_lng, max_lat, max_lng), method="manual", user=user, device=None,
    )


@files_router.get("/", response_model=list[SensorFileOut])
async def list_sensor_files(
    scan_session_id: UUID | None = None,
    site_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = (
        _scope(select(SensorFile, User.full_name, SensorDevice.name), SensorFile, user)
        .outerjoin(User, SensorFile.uploaded_by_id == User.id)
        .outerjoin(SensorDevice, SensorFile.device_id == SensorDevice.id)
        .order_by(SensorFile.created_at.desc())
        .limit(limit)
    )
    if scan_session_id is not None:
        query = query.where(SensorFile.scan_session_id == scan_session_id)
    if site_id is not None:
        query = query.where(SensorFile.site_id == site_id)
    rows = (await db.execute(query)).all()
    return [
        SensorFileOut.model_validate(f).model_copy(update={"uploadedByName": uploader, "deviceName": device})
        for f, uploader, device in rows
    ]


@files_router.get("/{file_id}/download-url", response_model=DownloadUrlOut)
async def sensor_file_download_url(file_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    record = (await db.execute(_scope(select(SensorFile).where(SensorFile.id == file_id), SensorFile, user))).scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    if record.storage_key is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Rejected uploads aren't stored.")
    external = get_storage().presigned_url(record.storage_key, record.original_filename)
    if external:
        return DownloadUrlOut(url=external, external=True, expiresIn=DOWNLOAD_URL_TTL_SECONDS)
    token = jwt.encode(
        {"sub": str(record.id), "type": "file_download", "exp": _now() + timedelta(seconds=DOWNLOAD_URL_TTL_SECONDS)},
        settings.secret_key, algorithm=ALGORITHM,
    )
    return DownloadUrlOut(url=f"/sensor-files/{record.id}/raw?token={token}", external=False, expiresIn=DOWNLOAD_URL_TTL_SECONDS)


@files_router.get("/{file_id}/raw")
async def sensor_file_raw(file_id: UUID, token: str, db: AsyncSession = Depends(get_db)):
    """Local-storage download, authorised by the short-lived token from
    /download-url (so a plain browser link works, like a presigned URL)."""
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Download link is invalid or has expired.")
    if claims.get("type") != "file_download" or claims.get("sub") != str(file_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Download link is invalid.")
    record = await db.get(SensorFile, file_id)
    path = get_storage().local_path(record.storage_key) if record and record.storage_key else None
    if path is None or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    return FileResponse(path, filename=record.original_filename)


# ---- Path 2: direct injection from sensor devices -------------------------------


@ingest_router.post("/readings", response_model=IngestReadingsOut, status_code=status.HTTP_201_CREATED)
async def ingest_readings(payload: ReadingsBatchIn, db: AsyncSession = Depends(get_db), device: SensorDevice = Depends(get_device)):
    now = _now()
    batch = []
    for r in payload.readings:
        at = r.recorded_at or now
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at > now + _MAX_FUTURE_SKEW:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"recorded_at {at.isoformat()} is in the future; check the device clock.")
        batch.append({"values": r.values, "recorded_at": at, "lat": r.lat, "lng": r.lng})
        db.add(SensorReading(
            organisation_id=device.organisation_id, device_id=device.id, site_id=device.site_id,
            sensor_type=device.sensor_type, recorded_at=at, lat=r.lat, lng=r.lng, values=r.values,
        ))
    latest = max(batch, key=lambda b: b["recorded_at"])
    if device.last_seen_at is None or latest["recorded_at"] >= device.last_seen_at:
        device.last_values = latest["values"]
    device.last_seen_at = now
    incidents = await evaluate_readings(db, device, batch)
    await db.commit()
    return IngestReadingsOut(
        accepted=len(batch),
        incidentsCreated=[
            AutoIncidentOut(id=i.id, incidentType=i.incident_type, riskScore=i.risk_score, description=i.description)
            for i in incidents
        ],
    )


@ingest_router.post("/files", response_model=SensorFileOut, status_code=status.HTTP_201_CREATED)
async def ingest_file(
    file: UploadFile = File(...),
    scan_session_id: UUID | None = Form(default=None),
    min_lat: float | None = Form(default=None),
    min_lng: float | None = Form(default=None),
    max_lat: float | None = Form(default=None),
    max_lng: float | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    device: SensorDevice = Depends(get_device),
):
    if device.sensor_type not in SENSOR_FORMATS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{device.sensor_type}' devices send readings (POST /ingest/readings), not files.",
        )
    device.last_seen_at = _now()
    return await _ingest_file(
        db, upload=file, org_id=device.organisation_id, site_id=device.site_id, sensor_type=device.sensor_type,
        scan_session_id=scan_session_id, manual_bbox=_manual_bbox(min_lat, min_lng, max_lat, max_lng),
        method="api", user=None, device=device,
    )


# ---- Live readings (for the UI) -------------------------------------------------


@readings_router.get("/", response_model=list[ReadingOut])
async def list_readings(
    device_id: UUID | None = None,
    site_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = _scope(select(SensorReading), SensorReading, user).order_by(SensorReading.recorded_at.desc()).limit(limit)
    if device_id is not None:
        query = query.where(SensorReading.device_id == device_id)
    if site_id is not None:
        query = query.where(SensorReading.site_id == site_id)
    return [ReadingOut.model_validate(r) for r in (await db.execute(query)).scalars()]


# ---- Device registry ------------------------------------------------------------


async def _get_owned_device(db: AsyncSession, user: User, device_id: UUID) -> SensorDevice:
    device = (
        await db.execute(_scope(select(SensorDevice).where(SensorDevice.id == device_id), SensorDevice, user))
    ).scalar_one_or_none()
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found.")
    return device


@devices_router.get("/", response_model=list[DeviceOut])
async def list_devices(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (await db.execute(_scope(select(SensorDevice), SensorDevice, user).order_by(SensorDevice.name))).scalars()
    return [_device_out(d) for d in rows]


@devices_router.get("/summary", response_model=DeviceSummaryOut)
async def device_summary(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    cutoff = _now() - ONLINE_WINDOW
    row = (await db.execute(_scope(select(
        func.count(SensorDevice.id),
        func.count(SensorDevice.id).filter(SensorDevice.is_active.is_(True)),
        func.count(SensorDevice.id).filter(SensorDevice.is_active.is_(True), SensorDevice.last_seen_at >= cutoff),
    ), SensorDevice, user))).one()
    return DeviceSummaryOut(total=row[0], active=row[1], online=row[2])


@devices_router.post("/", response_model=DeviceWithKeyOut, status_code=status.HTTP_201_CREATED)
async def register_device(payload: DeviceCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_device_manager)):
    org_id = _require_org(user)
    site = await db.get(Site, payload.site_id)
    if site is None or (user.role != "system_admin" and site.organisation_id != org_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found.")
    key = _new_key()
    device = SensorDevice(
        organisation_id=org_id, site_id=payload.site_id, name=payload.name.strip(), sensor_type=payload.sensor_type,
        api_key_hash=_hash_key(key), api_key_prefix=key[:12], created_by_id=user.id, last_values={},
    )
    db.add(device)
    await db.flush()
    await log_event(db, user, "device.register", "sensor_device", str(device.id), f"{device.name} ({device.sensor_type})")
    await db.commit()
    await db.refresh(device)
    return DeviceWithKeyOut(**_device_out(device).model_dump(), apiKey=key)


@devices_router.patch("/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: UUID, payload: DeviceUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(require_device_manager)
):
    device = await _get_owned_device(db, user, device_id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(device, field, value)
    if "is_active" in updates:
        await log_event(db, user, "device.activate" if device.is_active else "device.deactivate",
                        "sensor_device", str(device.id), device.name)
    await db.commit()
    await db.refresh(device)
    return _device_out(device)


@devices_router.post("/{device_id}/rotate-key", response_model=DeviceWithKeyOut)
async def rotate_device_key(device_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_device_manager)):
    device = await _get_owned_device(db, user, device_id)
    key = _new_key()
    device.api_key_hash, device.api_key_prefix = _hash_key(key), key[:12]
    await log_event(db, user, "device.rotate_key", "sensor_device", str(device.id), device.name)
    await db.commit()
    await db.refresh(device)
    return DeviceWithKeyOut(**_device_out(device).model_dump(), apiKey=key)
