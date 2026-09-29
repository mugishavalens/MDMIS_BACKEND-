"""Demo sensor data for the seed: devices on both ingestion paths, a live
reading history (including a CO spike that tripped a safety rule), and an
ingestion log with manual uploads, device pushes and rejected files.

Every demo file is a small but genuinely valid GeoTIFF / SEG-Y / CSV that
goes through the real validator and storage, so the log, metadata and
downloads behave exactly like real uploads.
"""
import hashlib
import math
import os
import random
import secrets
import struct
import tempfile
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.ingestion.models import SensorDevice, SensorFile, SensorReading
from app.ingestion.storage import build_key, get_storage
from app.ingestion.validation import validate_sensor_file
from app.safety.models import IncidentEvent
from app.safety.rules import evaluate_readings
from app.scans.models import ScanSession
from app.sites.models import Site

_rng = random.Random(42)  # deterministic demo data


def _geotiff(lon0: float, lat0: float, w: int, h: int, bands: int, px: float = 0.0001) -> bytes:
    base = 8 + 2 + 12 * 5 + 4
    scale = struct.pack("<3d", px, px, 0)
    tie = struct.pack("<6d", 0, 0, 0, lon0, lat0, 0)
    entries = [
        struct.pack("<HHI4s", 256, 3, 1, struct.pack("<H", w) + b"\0\0"),
        struct.pack("<HHI4s", 257, 3, 1, struct.pack("<H", h) + b"\0\0"),
        struct.pack("<HHI4s", 277, 3, 1, struct.pack("<H", bands) + b"\0\0"),
        struct.pack("<HHI4s", 33550, 12, 3, struct.pack("<I", base)),
        struct.pack("<HHI4s", 33922, 12, 6, struct.pack("<I", base + len(scale))),
    ]
    body = bytes(_rng.getrandbits(8) for _ in range(6000))
    return b"II*\0" + struct.pack("<I", 8) + struct.pack("<H", 5) + b"".join(entries) + struct.pack("<I", 0) + scale + tie + body


def _segy(traces: int = 40, samples: int = 512) -> bytes:
    header = bytearray(3600)
    header[:80] = b"C 1 MDMIS DEMO GPR LINE 12  250MHz ANTENNA".ljust(80)
    header[3216:3222] = struct.pack(">HHH", 400, 0, samples)
    trace = bytes(240) + bytes(samples * 2)
    return bytes(header) + trace * traces


def _mag_csv(lat0: float, lon0: float, n: int) -> bytes:
    rows = ["timestamp,lat,lon,total_field_nT,altitude_m"]
    t0 = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)
    for i in range(n):
        lat = lat0 + (i // 20) * 0.0004
        lon = lon0 + (i % 20) * 0.0003
        field = 48120 + 35 * math.sin(i / 7) + _rng.uniform(-4, 4)
        rows.append(f"{(t0 + timedelta(seconds=2 * i)).isoformat()},{lat:.6f},{lon:.6f},{field:.1f},{1.8:.1f}")
    return ("\n".join(rows) + "\n").encode()


async def _store_file(db, *, org_id, site, sensor_type, filename, content, created_at, method,
                      user=None, device=None, session=None, manual_bbox=None):
    fd, path = tempfile.mkstemp(prefix="mdmis-demo-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        result = validate_sensor_file(path, filename, sensor_type, len(content), manual_bbox)
        record = SensorFile(
            organisation_id=org_id, site_id=site.id, sensor_type=sensor_type, original_filename=filename,
            file_kind=result.kind, size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
            bbox=result.bbox, file_metadata=result.metadata, validation_errors=result.errors,
            validation_warnings=result.warnings, status="validated" if result.ok else "rejected",
            upload_method=method, uploaded_by_id=user.id if user else None, device_id=device.id if device else None,
            created_at=created_at,
        )
        if result.ok:
            if session is None:
                session = ScanSession(organisation_id=org_id, site_id=site.id, operator_id=user.id if user else None,
                                      sensor_types=[sensor_type], status="uploaded", uploaded_at=created_at)
                db.add(session)
                await db.flush()
            elif sensor_type not in session.sensor_types:
                session.sensor_types = [*session.sensor_types, sensor_type]
            record.scan_session_id = session.id
            record.storage_key = build_key(org_id, filename)
            get_storage().save(record.storage_key, path)
        db.add(record)
    finally:
        os.unlink(path)


def _device(org_id, site_id, name, sensor_type, created_by, **kw) -> SensorDevice:
    key = "mdk_" + secrets.token_urlsafe(32)  # never shown; rotate in the UI to get a usable key
    return SensorDevice(
        organisation_id=org_id, site_id=site_id, name=name, sensor_type=sensor_type,
        api_key_hash=hashlib.sha256(key.encode()).hexdigest(), api_key_prefix=key[:12],
        created_by_id=created_by.id, last_values={}, **kw,
    )


def _gas(t: int, spike: bool) -> dict:
    co = 7.5 + 2.5 * math.sin(t / 5) + _rng.uniform(-0.8, 0.8)
    if spike:
        co = 38 + _rng.uniform(0, 14)
    return {
        "co_ppm": round(co, 1), "h2s_ppm": round(1.1 + _rng.uniform(-0.3, 0.3), 2),
        "ch4_pct_lel": round(2.4 + _rng.uniform(-0.6, 0.6), 2), "o2_pct": round(20.8 + _rng.uniform(-0.12, 0.08), 2),
        "co2_ppm": round(880 + 120 * math.sin(t / 8) + _rng.uniform(-30, 30)),
    }


def _slope(t: int) -> dict:
    return {
        "displacement_rate_mm_per_h": round(0.22 + 0.05 * math.sin(t / 10) + _rng.uniform(-0.03, 0.03), 3),
        "slope_angle_deg": round(38.4 + _rng.uniform(-0.2, 0.2), 2),
        "pore_pressure_kpa": round(96 + 3 * math.sin(t / 12) + _rng.uniform(-1.5, 1.5), 1),
    }


async def seed_sensor_demo(db, org, users_by_email) -> None:
    if await db.scalar(select(func.count(SensorDevice.id)).where(SensorDevice.organisation_id == org.id)):
        return
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    mgr, geo = users_by_email["analyst@mdmis.rw"], users_by_email["geo@mdmis.rw"]
    sites = {s.id: s for s in (await db.execute(select(Site).where(Site.organisation_id == org.id))).scalars()}
    if not all(k in sites for k in ("RW-MSH-08", "RW-GFW-04", "RW-RTG-01", "RW-RWK-05", "RW-BGR-07", "RW-NYK-03")):
        return

    # ---- Path 2 devices ---------------------------------------------------------
    musha_gas = _device(org.id, "RW-MSH-08", "Gas Node · Musha Shaft 2", "gas", mgr)
    gifurwe_slope = _device(org.id, "RW-GFW-04", "Slope Monitor · Gifurwe East Wall", "geotechnical", mgr)
    rutongo_gas = _device(org.id, "RW-RTG-01", "Gas Node · Rutongo Adit 1", "gas", mgr)
    drone = _device(org.id, "RW-RTG-01", "DJI M300 · Hyperspectral Drone", "hyperspectral", mgr,
                    last_seen_at=now - timedelta(hours=26))
    rover = _device(org.id, "RW-NYK-03", "Mag Rover 02", "magnetometer", mgr, last_seen_at=now - timedelta(days=2, hours=3))
    retired = _device(org.id, "RW-NYK-03", "Gas Node · Nyakabingo (old)", "gas", mgr, is_active=False,
                      last_seen_at=now - timedelta(days=19))
    db.add_all([musha_gas, gifurwe_slope, rutongo_gas, drone, rover, retired])
    await db.flush()

    # Live history: one reading every 10 min for the last 12 h.
    spike = []
    for dev, gen, stop_before in ((musha_gas, "gas", None), (gifurwe_slope, "slope", None),
                                  (rutongo_gas, "gas", timedelta(hours=4))):
        latest = None
        for i in range(72):
            at = now - timedelta(minutes=10 * (71 - i))
            if stop_before and at > now - stop_before:
                break  # Rutongo node went offline 4 h ago
            is_spike = dev is musha_gas and 50 <= i <= 53  # ~3.5 h ago
            values = _gas(i, is_spike) if gen == "gas" else _slope(i)
            db.add(SensorReading(organisation_id=org.id, device_id=dev.id, site_id=dev.site_id,
                                 sensor_type=dev.sensor_type, recorded_at=at, values=values, received_at=at))
            if is_spike:
                spike.append({"values": values, "recorded_at": at, "lat": None, "lng": None})
            latest = (at, values)
        dev.last_seen_at, dev.last_values = latest

    # The spike trips the CO rule through the real engine, dated when it happened.
    for inc in await evaluate_readings(db, musha_gas, spike):
        first = spike[0]["recorded_at"]
        inc.created_at = first
        for ev in (await db.execute(select(IncidentEvent).where(IncidentEvent.incident_id == inc.id))).scalars():
            ev.created_at = first

    # ---- Ingestion log: Path 1 (manual) and Path 2 (device) files -------------------
    sessions = {}
    for s in (await db.execute(select(ScanSession).where(ScanSession.organisation_id == org.id))).scalars():
        sessions.setdefault((s.site_id, tuple(s.sensor_types)[:1]), s)

    def session_for(site_id, sensor):
        return sessions.get((site_id, (sensor,)))

    def site_box(site, d=0.01):
        lat, lng = float(site.lat), float(site.lng)
        return [lng - d, lat - d, lng + d, lat + d]

    msh, rwk, bgr, rtg, nyk = (sites[k] for k in ("RW-MSH-08", "RW-RWK-05", "RW-BGR-07", "RW-RTG-01", "RW-NYK-03"))
    files = [
        dict(site=msh, sensor_type="hyperspectral", filename="msh08_flight03_hyperspectral.tif", method="manual", user=geo,
             content=_geotiff(float(msh.lng) - 0.004, float(msh.lat) + 0.003, 80, 60, 186),
             created_at=now - timedelta(days=4, hours=2), session=session_for("RW-MSH-08", "hyperspectral")),
        dict(site=rwk, sensor_type="gpr", filename="rwk05_gpr_line12.sgy", method="manual", user=mgr,
             content=_segy(), manual_bbox=site_box(rwk, 0.004),
             created_at=now - timedelta(days=3, hours=5), session=session_for("RW-RWK-05", "gpr")),
        dict(site=bgr, sensor_type="satellite", filename="S2B_T35MRU_20260921_B01-B12.tif", method="manual", user=mgr,
             content=_geotiff(float(bgr.lng) - 0.05, float(bgr.lat) + 0.04, 100, 80, 13, px=0.001),
             created_at=now - timedelta(days=2, hours=7), session=session_for("RW-BGR-07", "satellite")),
        dict(site=nyk, sensor_type="magnetometer", filename="nyk03_mag_grid_A.csv", method="manual", user=geo,
             content=_mag_csv(float(nyk.lat) - 0.004, float(nyk.lng) - 0.003, 240), created_at=now - timedelta(days=1, hours=20)),
        dict(site=rtg, sensor_type="hyperspectral", filename="rtg01_cube_export.h5", method="manual", user=geo,
             content=b"\x89HDF\r\n\x1a\n" + bytes(4000), created_at=now - timedelta(days=1, hours=6)),
        dict(site=rwk, sensor_type="gamma", filename="gamma_survey_rwk05.xlsx", method="manual", user=mgr,
             content=b"PK\x03\x04" + bytes(3000), created_at=now - timedelta(hours=30)),
        dict(site=rtg, sensor_type="hyperspectral", filename="rtg01_auto_flight_0927.tif", method="api", device=drone,
             content=_geotiff(float(rtg.lng) - 0.003, float(rtg.lat) + 0.002, 90, 70, 186),
             created_at=now - timedelta(hours=26), session=session_for("RW-RTG-01", "hyperspectral")),
        dict(site=nyk, sensor_type="magnetometer", filename="rover02_track_0926.csv", method="api", device=rover,
             content=_mag_csv(float(nyk.lat) + 0.002, float(nyk.lng) + 0.001, 180), created_at=now - timedelta(days=2, hours=3)),
    ]
    for f in files:
        await _store_file(db, org_id=org.id, **f)
    print("Seeded sensor demo: 6 devices, 12 h of live readings, 8 ingestion log entries (2 rejected).")
