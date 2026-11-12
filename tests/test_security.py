"""Security regression check: replays every attack from the 2026-11-12
audit, and the legitimate path for each, on a throwaway SQLite DB.
Run from the repo root: python tests/test_security.py  (PASS = safe)."""
import asyncio
import os
import re
import sys
import tempfile
import uuid

DB = os.path.join(tempfile.mkdtemp(), "audit.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB}"
os.environ.pop("BREVO_API_KEY", None)
sys.path.insert(0, os.getcwd())

import io  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import app.models_registry  # noqa: E402,F401
from app import ratelimit  # noqa: E402
from app.accounts.models import Organisation, User  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.security import create_access_token, create_refresh_token, hash_password  # noqa: E402
from app.sites.models import Site  # noqa: E402

ROLES = ("org_admin", "geologist", "compliance_manager", "mine_manager")
users: dict[str, User] = {}
results = []


async def setup():
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        for tag in "AB":
            org = Organisation(name=f"Org {tag}", slug=f"org-{tag.lower()}", primary_contact_email=f"a@{tag}.rw")
            db.add(org)
            await db.flush()
            for role in ROLES:
                u = User(organisation_id=org.id, email=f"{role}@{tag.lower()}.rw", full_name=f"{tag} {role}", role=role,
                         password_hash=hash_password("Passw0rd!"), is_active=True, is_email_verified=True)
                db.add(u)
                users[f"{tag}:{role}"] = u
            db.add(Site(id=f"SITE-{tag}", organisation_id=org.id, name=f"Site {tag}", lat=-1.9, lng=30.0,
                        primary_mineral="cassiterite"))
        admin = User(organisation_id=None, email="root@mdmis.rw", full_name="Root", role="system_admin",
                     password_hash=hash_password("Passw0rd!"), is_active=True, is_email_verified=True)
        db.add(admin)
        users["sys"] = admin
        await db.commit()


asyncio.run(setup())
c = TestClient(app, raise_server_exceptions=False)


def H(who):
    u = users[who]
    return {"Authorization": f"Bearer {create_access_token(str(u.id), 0)}"}


def check(name, safe, detail=""):
    results.append(safe)
    print(f"{'PASS' if safe else 'FAIL'}  {name}" + (f"  [{detail}]" if detail != "" else ""))


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


A, B = H("A:org_admin"), H("B:org_admin")
scan_b = c.post("/api/scans/", json={"site_id": "SITE-B"}, headers=B).json()
zone_b = c.post("/api/mineral-zones/", json={"scan_session_id": scan_b["id"], "mineral_type": "gold"}, headers=B).json()
batch_b = c.post("/api/traceability/", json={"site_id": "SITE-B", "mineral_type": "gold"}, headers=B).json()

print("-- cross-tenant reads stay blocked --")
for path in ("/api/sites/SITE-B", f"/api/scans/{scan_b['id']}", f"/api/mineral-zones/{zone_b['id']}",
             f"/api/traceability/{batch_b['id']}"):
    check(f"A reads {path.split('/')[2]}", c.get(path, headers=A).status_code == 404)

print("-- cross-tenant writes --")
for name, method, path, body in [
    ("scan session on B's site", "post", "/api/scans/", {"site_id": "SITE-B"}),
    ("zone in B's scan session", "post", "/api/mineral-zones/", {"scan_session_id": scan_b["id"], "mineral_type": "gold"}),
    ("batch on B's site", "post", "/api/traceability/", {"site_id": "SITE-B", "mineral_type": "gold"}),
    ("safety incident on B's site", "post", "/api/safety/", {"site_id": "SITE-B", "incident_type": "other"}),
    ("safety incident on A's site citing B's zone", "post", "/api/safety/",
     {"site_id": "SITE-A", "incident_type": "other", "zone_id": zone_b["id"]}),
    ("safety rule for B's site", "post", "/api/safety-rules/", {"site_id": "SITE-B", "metric": "co_ppm", "comparator": "gt",
                                                                "threshold": 1}),
]:
    r = getattr(c, method)(path, json=body, headers=A)
    check(f"A creates {name}", r.status_code == 404, r.status_code)
r = c.post("/api/sites/", json={"id": "SITE-B", "name": "x", "lat": 0, "lng": 0, "primary_mineral": "gold"}, headers=A)
check("duplicate site id -> 409, not 500", r.status_code == 409, r.status_code)

print("-- roles (org A) --")
scan_a = c.post("/api/scans/", json={"site_id": "SITE-A"}, headers=A).json()
batch_a = c.post("/api/traceability/", json={"site_id": "SITE-A", "mineral_type": "gold"}, headers=A).json()
report_a = c.post("/api/compliance/", json={"title": "r", "framework": "oecd", "period": "Q1"}, headers=A).json()
cases = [
    ("compliance_manager", "post", "/api/sites/", {"id": "SITE-A2", "name": "x", "lat": 0, "lng": 0, "primary_mineral": "gold"}, False),
    ("geologist", "post", "/api/sites/", {"id": "SITE-A3", "name": "x", "lat": 0, "lng": 0, "primary_mineral": "gold"}, True),
    ("mine_manager", "delete", "/api/sites/SITE-A3", None, False),
    ("compliance_manager", "post", "/api/mineral-zones/", {"scan_session_id": scan_a["id"], "mineral_type": "gold"}, False),
    ("mine_manager", "post", "/api/mineral-zones/", {"scan_session_id": scan_a["id"], "mineral_type": "gold", "status": "lab_confirmed"}, False),
    ("geologist", "post", "/api/mineral-zones/", {"scan_session_id": scan_a["id"], "mineral_type": "gold", "status": "lab_confirmed"}, True),
    ("mine_manager", "patch", f"/api/traceability/{batch_a['id']}", {"compliant": True}, False),
    ("compliance_manager", "patch", f"/api/traceability/{batch_a['id']}", {"compliant": True, "compliance_note": "ok"}, True),
    ("compliance_manager", "patch", f"/api/traceability/{batch_a['id']}", {"status": "graded"}, False),
    ("mine_manager", "patch", f"/api/traceability/{batch_a['id']}", {"status": "graded"}, True),
    ("compliance_manager", "post", "/api/custody-events/", {"batch_id": batch_a["id"], "event_type": "weigh_in"}, False),
    ("mine_manager", "post", "/api/custody-events/", {"batch_id": batch_a["id"], "event_type": "weigh_in"}, True),
    ("geologist", "post", "/api/compliance/", {"title": "x", "framework": "oecd", "period": "Q1"}, False),
    ("compliance_manager", "post", "/api/compliance/", {"title": "x", "framework": "oecd", "period": "Q1"}, True),
    ("compliance_manager", "delete", f"/api/compliance/{report_a['id']}", None, False),
    ("geologist", "post", "/api/safety/", {"site_id": "SITE-A", "incident_type": "other"}, True),
    ("geologist", "delete", f"/api/scans/{scan_a['id']}", None, False),
]
for role, method, path, body, allowed in cases:
    r = getattr(c, method)(path, headers=H(f"A:{role}"), **({"json": body} if body is not None else {}))
    ok = (r.status_code < 300) if allowed else (r.status_code == 403)
    what = f"{role} {method.upper()} {path.split('/')[2]}" + (f" {list(body)[-1]}" if body else "")
    check(f"{what}: {'allowed' if allowed else 'refused'}", ok, r.status_code)
r = c.post("/api/scans/", json={"site_id": "SITE-B"}, headers=H("sys"))
check("system_admin acts on any org's site; row lands in that org", r.status_code == 201, r.status_code)

print("-- stored XSS / input validation --")
r = c.post("/api/sites/", json={"id": "SITE-X", "name": "x", "lat": 0, "lng": 0,
                                "primary_mineral": "<img src=x onerror=alert(1)>"}, headers=A)
check("script in primary_mineral rejected", r.status_code == 422, r.status_code)
r = c.post("/api/sites/", json={"id": "../../etc", "name": "x", "lat": 0, "lng": 0, "primary_mineral": "gold"}, headers=A)
check("path characters in site id rejected", r.status_code == 422, r.status_code)
r = c.patch(f"/api/mineral-zones/{zone_b['id']}", json={"status": "hacked"}, headers=B)
check("unknown zone status rejected", r.status_code == 422, r.status_code)

print("-- auth --")
for i in range(5):
    c.post("/api/auth/login/", json={"email": "org_admin@a.rw", "password": f"wrong{i}"})
r = c.post("/api/auth/login/", json={"email": "org_admin@a.rw", "password": "Passw0rd!"})
check("6th attempt after 5 failures -> 429 even with right password", r.status_code == 429, r.status_code)
ratelimit.login_failures.reset("org_admin@a.rw")
r = c.post("/api/auth/login/", json={"email": "org_admin@a.rw", "password": "Passw0rd!"})
check("normal login works", r.status_code == 200 and "access" in r.json(), r.status_code)

codes = [quiet(c.post, "/api/auth/resend-otp/", json={"email": "victim@x.rw"})[0].status_code for _ in range(5)]
check("code emails capped at 3 per address per 15 min", codes[:3] == [200] * 3 and codes[3] == 429, codes)

# the code-only login hole: resend to an ACTIVE account must send nothing,
# and verify-otp must not log an active account in
ratelimit.code_emails.clear()
r, out = quiet(c.post, "/api/auth/resend-otp/", json={"email": "geologist@a.rw"})
check("resend-otp sends no code to an active account", "verification code" not in out, r.status_code)
r = c.post("/api/auth/verify-otp/", json={"email": "geologist@a.rw", "code": "123456"})
check("verify-otp can't log in an active account", r.status_code == 400, r.status_code)

# password reset: code by email, new password, old sessions end
ratelimit.code_emails.clear()
old_refresh = create_refresh_token(str(users["A:geologist"].id), 0)
r, out = quiet(c.post, "/api/auth/forgot-password/", json={"email": "geologist@a.rw"})
code = re.search(r"letter-spacing:4px'>(\d{6})<", out)
check("forgot-password emails a reset code", r.status_code == 200 and code is not None, r.status_code)
r = c.post("/api/auth/reset-password/", json={"email": "geologist@a.rw", "code": code.group(1) if code else "000000",
                                               "new_password": "Brand-new-pass1"})
check("reset-password with the code works", r.status_code == 200, r.status_code)
r = c.post("/api/auth/refresh/", json={"refresh": old_refresh})
check("refresh token from before the reset is dead", r.status_code == 401, r.status_code)
r = c.post("/api/auth/login/", json={"email": "geologist@a.rw", "password": "Brand-new-pass1"})
check("login with the new password", r.status_code == 200, r.status_code)
fresh = r.json()

# change password returns tokens for this session, kills the rest
other_session = c.post("/api/auth/login/", json={"email": "geologist@a.rw", "password": "Brand-new-pass1"}).json()
r = c.post("/api/auth/change-password/", json={"current_password": "Brand-new-pass1", "new_password": "Another-pass2"},
           headers={"Authorization": f"Bearer {fresh['access']}"})
check("change-password returns fresh tokens", r.status_code == 200 and "access" in r.json(), r.status_code)
mine = r.json()
check("other session's access token dead after change",
      c.get("/api/auth/me/", headers={"Authorization": f"Bearer {other_session['access']}"}).status_code == 401)
check("this session's new token works",
      c.get("/api/auth/me/", headers={"Authorization": f"Bearer {mine['access']}"}).status_code == 200)
r = c.post("/api/auth/logout/", headers={"Authorization": f"Bearer {mine['access']}"})
check("logout ends the session", r.status_code == 204 and
      c.get("/api/auth/me/", headers={"Authorization": f"Bearer {mine['access']}"}).status_code == 401, r.status_code)

r = c.post("/api/auth/register/", json={"email": "long@x.rw", "password": "y" * 100, "full_name": "n"})
check("password over 72 bytes rejected", r.status_code == 422, r.status_code)

# squatting: someone registers a victim's address; the owner reclaims it
ratelimit.code_emails.clear()
quiet(c.post, "/api/auth/register/", json={"email": "owner@x.rw", "password": "attacker-pass", "full_name": "x"})
ratelimit.code_emails.clear()
r, out = quiet(c.post, "/api/auth/forgot-password/", json={"email": "owner@x.rw"})
code = re.search(r"letter-spacing:4px'>(\d{6})<", out)
r = c.post("/api/auth/reset-password/", json={"email": "owner@x.rw", "code": code.group(1), "new_password": "owners-own-pass"})
check("real owner reclaims a squatted address via reset", r.status_code == 200, r.status_code)
check("squatter's password no longer works",
      c.post("/api/auth/login/", json={"email": "owner@x.rw", "password": "attacker-pass"}).status_code == 400)

print("-- invitation email escaping --")
ratelimit.code_emails.clear()
evil_org = '<a href="https://evil.example">Verify your account</a>'
async def rename():
    async with AsyncSessionLocal() as db:
        org = await db.get(Organisation, users["A:org_admin"].organisation_id)
        org.name = evil_org
        await db.commit()
asyncio.run(rename())
r, out = quiet(c.post, "/api/accounts/invitations/", json={"email": "new@a.rw", "role": "geologist"}, headers=A)
body = out.split("Subject:", 1)[1].split("\n", 1)[1]  # subject is plain text; the HTML body is what renders
check("org name in invitation email body is escaped", r.status_code == 201 and "<a href=\"https://evil" not in body
      and "&lt;a href=" in body, r.status_code)

print("-- service key / docs / headers --")
check("default ML service key refused in production",
      not type(settings)(database_url="postgresql://x/y", ml_service_api_key="dev-insecure-ml-service-key-change-me").ml_service_key_usable)
try:
    type(settings)(database_url="postgresql://x/y", secret_key="dev-insecure-secret-key-change-me").check_production_secrets()
    check("production refuses to start with the default SECRET_KEY", False)
except RuntimeError:
    check("production refuses to start with the default SECRET_KEY", True)
check("API docs off in production", not type(settings)(database_url="postgresql://x/y").docs_enabled)
r = c.get("/api/health")
missing = [h for h in ("x-content-type-options", "x-frame-options", "strict-transport-security", "content-security-policy")
           if h not in {k.lower() for k in r.headers}]
check("security headers present", not missing, ",".join(missing))
r = c.get("/api/scans/retrain-data", headers={"X-ML-Service-Key": settings.ml_service_api_key})
check("retrain-data returns nothing until TRAINING_ORG_IDS is set", r.status_code == 200 and r.json() == [], r.status_code)

print(f"\n{sum(results)}/{len(results)} passed")
