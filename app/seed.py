"""Seed a demo organisation, the 4 demo users, and the 10 demo sites used by
the frontend. Run with: python -m app.seed
"""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.accounts.models import Organisation, User
from app.database import AsyncSessionLocal
from app.security import hash_password
from app.sites.models import Site

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

        await db.commit()
        print(f"Seed complete. Password for {DEMO_USERS[0][0]}: {DEMO_USERS[0][3]}")
        print(f"Password for all other demo users: {DEMO_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(seed())
