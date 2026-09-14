"""Seed a demo organisation, the 4 demo users, and the 10 demo sites used by
the frontend. Run with: python -m app.seed
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.accounts.models import Organisation, User
from app.compliance.models import ComplianceReport
from app.database import AsyncSessionLocal
from app.safety.models import SafetyIncident
from app.scans.models import MineralZone, ScanSession
from app.security import hash_password
from app.sites.models import Site
from app.traceability.models import CustodyEvent, MineralBatch
from app.transport.models import Shipment

DEMO_PASSWORD = "demo1234"

# (email, full_name, role, password) — password defaults to DEMO_PASSWORD
# when omitted. system_admin is the only real (non-quick-demo) credential
# exposed on the login page, so it gets its own password.
DEMO_USERS = [
    ("vivamugisha@gmail.com", "Mugisha", "system_admin", "MDMIS@2026"),
    ("owner@mdmis.rw", "E. Uwase", "org_admin", None),
    ("analyst@mdmis.rw", "D. Nzeyimana", "mine_manager", None),
    ("geo@mdmis.rw", "J. Habimana", "geologist", None),
    ("compliance@mdmis.rw", "C. Mukamana", "compliance_manager", None),
]

# Mirrors frontend/lib/mdmis-data.ts SITES so the map explorer's static
# terrain assets (frontend/public/terrain/<id>/) line up with real DB rows.
DEMO_SITES = [
    dict(id="RW-RTG-01", name="Rutongo Tin Belt", district="Rulindo", lat=-1.7783, lng=30.0611,
         primary_mineral="cassiterite", secondary_minerals=["wolframite"], grade_pct=1.8, confidence=96.4,
         estimated_tonnage=42500, safety_score=82, risk_level="low", status="active",
         last_scan="2026-06-08T09:12:00Z", depth_meters=48),
    dict(id="RW-GTB-02", name="Gatumba Coltan Field", district="Ngororero", lat=-1.8642, lng=29.5231,
         primary_mineral="coltan", secondary_minerals=["beryl", "cassiterite"], grade_pct=0.42, confidence=93.1,
         estimated_tonnage=12800, safety_score=61, risk_level="moderate", status="active",
         last_scan="2026-06-08T07:44:00Z", depth_meters=32),
    dict(id="RW-NYK-03", name="Nyakabingo Mine", district="Rulindo", lat=-1.7419, lng=30.0089,
         primary_mineral="wolframite", secondary_minerals=[], grade_pct=1.1, confidence=97.8,
         estimated_tonnage=30100, safety_score=88, risk_level="low", status="active",
         last_scan="2026-06-07T16:20:00Z", depth_meters=65),
    dict(id="RW-GFW-04", name="Gifurwe Tungsten", district="Rutsiro", lat=-1.9928, lng=29.4102,
         primary_mineral="wolframite", secondary_minerals=["cassiterite"], grade_pct=0.95, confidence=91.5,
         estimated_tonnage=18900, safety_score=44, risk_level="high", status="flagged",
         last_scan="2026-06-08T05:03:00Z", depth_meters=27),
    dict(id="RW-RWK-05", name="Rwinkwavu Prospect", district="Kayonza", lat=-2.1481, lng=30.5892,
         primary_mineral="gold", secondary_minerals=[], grade_pct=4.2, confidence=88.7,
         estimated_tonnage=3400, safety_score=73, risk_level="moderate", status="surveying",
         last_scan="2026-06-08T10:31:00Z", depth_meters=12),
    dict(id="RW-NMB-06", name="Nemba Coltan", district="Gakenke", lat=-1.6892, lng=29.7743,
         primary_mineral="coltan", secondary_minerals=["cassiterite"], grade_pct=0.51, confidence=94.9,
         estimated_tonnage=9600, safety_score=79, risk_level="low", status="active",
         last_scan="2026-06-07T14:55:00Z", depth_meters=40),
    dict(id="RW-BGR-07", name="Bugarama Ridge", district="Rusizi", lat=-2.6889, lng=29.0031,
         primary_mineral="lithium", secondary_minerals=["beryl"], grade_pct=1.35, confidence=85.2,
         estimated_tonnage=7200, safety_score=58, risk_level="moderate", status="surveying",
         last_scan="2026-06-08T08:17:00Z", depth_meters=22),
    dict(id="RW-MSH-08", name="Musha Cassiterite", district="Rwamagana", lat=-1.9231, lng=30.3402,
         primary_mineral="cassiterite", secondary_minerals=["coltan"], grade_pct=1.62, confidence=95.6,
         estimated_tonnage=21500, safety_score=34, risk_level="critical", status="flagged",
         last_scan="2026-06-08T11:02:00Z", depth_meters=55),
    dict(id="RW-KRG-09", name="Karongi Beryl Zone", district="Karongi", lat=-2.0031, lng=29.3781,
         primary_mineral="beryl", secondary_minerals=["lithium"], grade_pct=0.88, confidence=82.3,
         estimated_tonnage=5100, safety_score=76, risk_level="low", status="active",
         last_scan="2026-06-06T13:40:00Z", depth_meters=18),
    dict(id="RW-RTS-10", name="Rutsiro Gold Belt", district="Rutsiro", lat=-1.9312, lng=29.3312,
         primary_mineral="gold", secondary_minerals=["wolframite"], grade_pct=3.6, confidence=90.1,
         estimated_tonnage=2800, safety_score=67, risk_level="moderate", status="active",
         last_scan="2026-06-08T06:28:00Z", depth_meters=15),
]

# ---- Scans ------------------------------------------------------------------

DEMO_SCANS = [
    dict(
        site_id="RW-MSH-08", operator_email="geo@mdmis.rw", sensor_types=["hyperspectral"],
        status="complete", uploaded_at="2026-06-08T11:02:00Z",
        zones=[
            dict(mineral_type="cassiterite", confidence_score=96, grade_pct=1.62, area_ha=14.2, alternatives=[
                {"mineral": "cassiterite", "probability": 95.6}, {"mineral": "coltan", "probability": 3.1},
                {"mineral": "wolframite", "probability": 1.3},
            ]),
        ],
    ),
    dict(
        site_id="RW-RWK-05", operator_email="analyst@mdmis.rw", sensor_types=["gpr"],
        status="complete", uploaded_at="2026-06-08T10:31:00Z",
        zones=[
            dict(mineral_type="gold", confidence_score=89, grade_pct=4.2, area_ha=6.1, alternatives=[
                {"mineral": "gold", "probability": 88.7}, {"mineral": "cassiterite", "probability": 7.2},
                {"mineral": "beryl", "probability": 4.1},
            ]),
        ],
    ),
    dict(
        site_id="RW-RTG-01", operator_email="geo@mdmis.rw", sensor_types=["hyperspectral"],
        status="complete", uploaded_at="2026-06-08T09:12:00Z",
        zones=[
            dict(mineral_type="cassiterite", confidence_score=96, grade_pct=1.8, area_ha=18.4, alternatives=[
                {"mineral": "cassiterite", "probability": 96.4}, {"mineral": "wolframite", "probability": 2.4},
                {"mineral": "coltan", "probability": 1.2},
            ]),
        ],
    ),
    dict(
        site_id="RW-BGR-07", operator_email=None, sensor_types=["satellite"],
        status="classifying", uploaded_at="2026-06-08T10:17:00Z", zones=[],
    ),
]

# ---- Traceability -------------------------------------------------------------

DEMO_BATCHES = [
    dict(
        seq=1, site_id="RW-RTG-01", mineral_type="cassiterite", weight_kg=1250, grade_detected=1.8,
        grade_confirmed=1.78, status="in_transit", compliant=True, extraction_date="2026-05-24",
        events=[
            dict(event_type="extraction", from_party="Rutongo Mining Co.", to_party="RMB Agent",
                 quantity_kg=1250, timestamp="2026-05-24T11:30:00Z"),
            dict(event_type="weigh_in", from_party="RMB Agent", to_party="RMB Weigh Station",
                 quantity_kg=1250, timestamp="2026-05-24T15:10:00Z"),
            dict(event_type="dispatch", from_party="RMB Weigh Station", to_party="Kigali Logistics Hub",
                 quantity_kg=1250, timestamp="2026-05-26T06:45:00Z"),
        ],
    ),
    dict(
        seq=1, site_id="RW-NMB-06", mineral_type="coltan", weight_kg=640, grade_detected=0.51,
        grade_confirmed=None, status="in_storage", compliant=True, extraction_date="2026-06-03",
        events=[
            dict(event_type="extraction", from_party="Nemba Coop", to_party="RMB Agent",
                 quantity_kg=640, timestamp="2026-06-03T10:00:00Z"),
            dict(event_type="storage_in", from_party="RMB Agent", to_party="Kigali Logistics Hub",
                 quantity_kg=640, timestamp="2026-06-05T16:40:00Z"),
        ],
    ),
    dict(
        seq=1, site_id="RW-GFW-04", mineral_type="wolframite", weight_kg=980, grade_detected=0.95,
        grade_confirmed=None, status="scanned", compliant=False, extraction_date="2026-06-06",
        compliance_note=(
            "Extracted by an unregistered operator and tagged by a disputed agent. "
            "Export blocked pending RMB investigation."
        ),
        events=[
            dict(event_type="extraction", from_party="Unregistered operator", to_party="RMB Agent",
                 quantity_kg=980, timestamp="2026-06-06T09:45:00Z"),
            dict(event_type="weigh_in", from_party="RMB Agent (disputed)", to_party="RMB Weigh Station",
                 quantity_kg=980, timestamp="2026-06-06T12:00:00Z", flagged=True),
        ],
    ),
]

# ---- Transport ----------------------------------------------------------------

_KIGALI = dict(name="Kigali Logistics Hub", lat=-1.9441, lng=30.0619)
_MOMBASA = dict(name="Port of Mombasa", lat=-4.0435, lng=39.6682)
_DAR = dict(name="Port of Dar es Salaam", lat=-6.7924, lng=39.2083)

DEMO_SHIPMENTS = [
    dict(origin=_KIGALI, destination=_MOMBASA, driver="J. Nkurunziza", vehicle="Truck-14",
         mineral_type="cassiterite", status="in-transit", progress_pct=62, eta_hours=9.5, weight_kg=1250,
         gps_integrity=True),
    dict(origin=dict(name="Rutongo Mine", lat=-1.7783, lng=30.0611), destination=_KIGALI, driver="P. Habiyaremye",
         vehicle="Truck-08", mineral_type="wolframite", status="delayed", eta_hours=3.0, weight_kg=980,
         gps_integrity=False, progress_pct=28),
    dict(origin=_KIGALI, destination=_DAR, driver="A. Uwase", vehicle="Truck-22", mineral_type="coltan",
         status="loading", progress_pct=5, eta_hours=14.0, weight_kg=640, gps_integrity=True),
]

# ---- Compliance -----------------------------------------------------------

DEMO_REPORTS = [
    dict(title="OECD Due Diligence - Q2 Supply Chain", framework="oecd", period="Q2 2026", status="submitted",
         coverage_pct=97.2, flagged_lots=1, submitted_to="OECD Secretariat"),
    dict(title="ITSCI Traceability Audit", framework="itsci", period="Q2 2026", status="approved",
         coverage_pct=99.1, flagged_lots=0, submitted_to="ITSCI Programme"),
    dict(title="RMB Licensing Renewal", framework="rmb", period="2026", status="draft",
         coverage_pct=84.0, flagged_lots=2, submitted_to="Rwanda Mines Board"),
]

# ---- Safety -----------------------------------------------------------------

DEMO_INCIDENTS = [
    dict(site_id="RW-MSH-08", incident_type="structural_instability", risk_score=88, status="open",
         description="Subsurface instability detected - safety score dropped to 34.",
         reporter_email="geo@mdmis.rw"),
    dict(site_id="RW-GFW-04", incident_type="slope_failure", risk_score=61, status="acknowledged",
         description="Minor slope movement detected after heavy rainfall.",
         reporter_email="analyst@mdmis.rw", acknowledger_email="analyst@mdmis.rw"),
    dict(site_id="RW-BGR-07", incident_type="gas_threshold", risk_score=35, status="resolved",
         description="CO2 sensor briefly exceeded threshold; ventilation corrected.",
         reporter_email="geo@mdmis.rw", acknowledger_email="analyst@mdmis.rw"),
]


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def seed():
    async with AsyncSessionLocal() as db:
        org = await db.scalar(select(Organisation).where(Organisation.slug == "mdmis-rwanda"))
        if org is None:
            org = Organisation(
                name="MDMIS Rwanda Operations",
                slug="mdmis-rwanda",
                country_code="RW",
                license_tier="enterprise",
                primary_contact_email="admin@mdmis.rw",
            )
            db.add(org)
            await db.flush()
            print(f"Created organisation: {org.name}")
        else:
            print(f"Using organisation: {org.name}")

        for email, full_name, role, password in DEMO_USERS:
            existing = await db.scalar(select(User).where(User.email == email))
            if existing:
                print(f"User already exists: {email}")
                continue
            user = User(
                organisation_id=org.id,
                email=email,
                full_name=full_name,
                role=role,
                password_hash=hash_password(password or DEMO_PASSWORD),
                is_active=True,
                is_staff=(role == "system_admin"),
            )
            db.add(user)
            print(f"Created user: {email} ({role})")

        for data in DEMO_SITES:
            site = await db.get(Site, data["id"])
            last_scan = datetime.fromisoformat(data["last_scan"].replace("Z", "+00:00"))
            if site is None:
                site = Site(organisation_id=org.id, **{**data, "last_scan": last_scan})
                db.add(site)
                print(f"Created site: {data['id']}")
            else:
                for k, v in {**data, "last_scan": last_scan}.items():
                    if k == "id":
                        continue
                    setattr(site, k, v)
                print(f"Updated site: {data['id']}")

        await db.flush()
        users_by_email = {u.email: u for u in (await db.execute(select(User).where(User.organisation_id == org.id))).scalars()}

        # ---- Scans (only if the org has none yet — these aren't idempotent
        # per-record like sites/users, just "don't pile up on every run") ----
        scan_count = await db.scalar(select(func.count(ScanSession.id)).where(ScanSession.organisation_id == org.id))
        if not scan_count:
            for data in DEMO_SCANS:
                operator = users_by_email.get(data["operator_email"]) if data["operator_email"] else None
                session = ScanSession(
                    organisation_id=org.id, site_id=data["site_id"], operator_id=operator.id if operator else None,
                    sensor_types=data["sensor_types"], status=data["status"], uploaded_at=_iso(data["uploaded_at"]),
                )
                db.add(session)
                await db.flush()
                for zone in data["zones"]:
                    db.add(MineralZone(
                        scan_session_id=session.id, organisation_id=org.id, mineral_type=zone["mineral_type"],
                        confidence_score=zone["confidence_score"], confidence_alternatives=zone["alternatives"],
                        grade_pct=zone["grade_pct"], area_ha=zone["area_ha"],
                    ))
            print(f"Seeded {len(DEMO_SCANS)} scan session(s).")

        # ---- Traceability -----------------------------------------------------
        batch_count = await db.scalar(select(func.count(MineralBatch.id)).where(MineralBatch.organisation_id == org.id))
        if not batch_count:
            for data in DEMO_BATCHES:
                date_part = data["extraction_date"].replace("-", "")
                coc_id = f"COC-{data['site_id']}-{date_part}-{data['seq']:04d}"
                batch = MineralBatch(
                    coc_id=coc_id, organisation_id=org.id, site_id=data["site_id"], mineral_type=data["mineral_type"],
                    weight_kg=data["weight_kg"], grade_detected=data["grade_detected"],
                    grade_confirmed=data["grade_confirmed"], status=data["status"], compliant=data["compliant"],
                    compliance_note=data.get("compliance_note", ""), created_by_id=users_by_email["geo@mdmis.rw"].id,
                )
                db.add(batch)
                await db.flush()
                for ev in data["events"]:
                    db.add(CustodyEvent(
                        batch_id=batch.id, event_type=ev["event_type"], from_party=ev["from_party"],
                        to_party=ev["to_party"], quantity_kg=ev["quantity_kg"], timestamp=_iso(ev["timestamp"]),
                        flagged=ev.get("flagged", False),
                    ))
            print(f"Seeded {len(DEMO_BATCHES)} mineral batch(es).")

        # ---- Transport ----------------------------------------------------------
        shipment_count = await db.scalar(select(func.count(Shipment.id)).where(Shipment.organisation_id == org.id))
        if not shipment_count:
            for data in DEMO_SHIPMENTS:
                db.add(Shipment(
                    organisation_id=org.id, mineral_type=data["mineral_type"],
                    origin_name=data["origin"]["name"], origin_lat=data["origin"]["lat"], origin_lng=data["origin"]["lng"],
                    destination_name=data["destination"]["name"], destination_lat=data["destination"]["lat"],
                    destination_lng=data["destination"]["lng"], driver=data["driver"], vehicle=data["vehicle"],
                    status=data["status"], progress_pct=data["progress_pct"], eta_hours=data["eta_hours"],
                    weight_kg=data["weight_kg"], gps_integrity=data["gps_integrity"],
                ))
            print(f"Seeded {len(DEMO_SHIPMENTS)} shipment(s).")

        # ---- Compliance -----------------------------------------------------
        report_count = await db.scalar(select(func.count(ComplianceReport.id)).where(ComplianceReport.organisation_id == org.id))
        if not report_count:
            for data in DEMO_REPORTS:
                db.add(ComplianceReport(organisation_id=org.id, generated_by_id=users_by_email["compliance@mdmis.rw"].id, **data))
            print(f"Seeded {len(DEMO_REPORTS)} compliance report(s).")

        # ---- Safety -----------------------------------------------------------
        incident_count = await db.scalar(select(func.count(SafetyIncident.id)).where(SafetyIncident.organisation_id == org.id))
        if not incident_count:
            for data in DEMO_INCIDENTS:
                reporter = users_by_email[data["reporter_email"]]
                acknowledger_email = data.get("acknowledger_email")
                incident = SafetyIncident(
                    organisation_id=org.id, site_id=data["site_id"], incident_type=data["incident_type"],
                    risk_score=data["risk_score"], status=data["status"], description=data["description"],
                    reported_by_id=reporter.id,
                )
                if acknowledger_email:
                    incident.acknowledged_by_id = users_by_email[acknowledger_email].id
                    incident.acknowledged_at = datetime.now(timezone.utc) - timedelta(hours=6)
                db.add(incident)
            print(f"Seeded {len(DEMO_INCIDENTS)} safety incident(s).")

        await db.commit()
        print(f"Seed complete. Password for {DEMO_USERS[0][0]}: {DEMO_USERS[0][3]}")
        print(f"Password for all other demo users: {DEMO_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(seed())
