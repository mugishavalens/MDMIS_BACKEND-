"""Drone surveys against a stand-in ML service (httpx MockTransport):
roles, organisation isolation, upload checks, the job's life cycle and the
site terrain switching to the survey. Run: python tests/test_drone_surveys.py"""
import asyncio
import json
import os
import sys
import tempfile

DB = os.path.join(tempfile.mkdtemp(), "drone.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB}"
os.environ.pop("BREVO_API_KEY", None)
sys.path.insert(0, os.getcwd())

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models_registry  # noqa: E402,F401
from app.accounts.models import Organisation, User  # noqa: E402
from app.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.drone_surveys import router as drone_router  # noqa: E402
from app.main import app  # noqa: E402
from app.security import create_access_token, hash_password  # noqa: E402
from app.sites.models import Site  # noqa: E402

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
            for role in ("org_admin", "geologist", "compliance_manager"):
                u = User(organisation_id=org.id, email=f"{role}@{tag.lower()}.rw", full_name=role, role=role,
                         password_hash=hash_password("Passw0rd!"), is_active=True, is_email_verified=True)
                db.add(u)
                users[f"{tag}:{role}"] = u
            db.add(Site(id=f"SITE-{tag}", organisation_id=org.id, name=f"Site {tag}", lat=-1.9, lng=30.0,
                        primary_mineral="gold"))
        await db.commit()


asyncio.run(setup())

# ---- stand-in ML service: queued -> running -> done
JOB = {"polls": 0, "fail": False}
GRID = {"gridSize": 2, "minLat": -1.91, "maxLat": -1.90, "minLon": 30.0, "maxLon": 30.01,
        "elevations": [[1, 2], [3, 4]], "minElevation": 1, "maxElevation": 4}


def ml(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if request.headers.get("X-ML-Service-Key") != drone_router.settings.ml_service_api_key:
        return httpx.Response(401)
    if path == "/reconstructions" and request.method == "POST":
        return httpx.Response(202, json={"id": "job0001", "state": "queued", "stage": "queued", "message": "queued"})
    if path == "/reconstructions/job0001":
        JOB["polls"] += 1
        if JOB["fail"]:
            return httpx.Response(200, json={"state": "failed", "error": "too little overlap"})
        if JOB["polls"] == 1:
            return httpx.Response(200, json={"state": "running", "stage": "dense", "progress": 0.6, "message": "dense"})
        return httpx.Response(200, json={"state": "done", "stage": "done", "progress": 1.0, "stats": {"photos_used": 5}})
    name = path.rsplit("/", 1)[-1]
    if name in ("ground.json", "surface.json"):
        return httpx.Response(200, json={**GRID, "source": name})
    if name == "cloud.json":
        return httpx.Response(200, json={"points": [], "colors": [], "cameras": []})
    if name == "ortho.jpg":
        return httpx.Response(200, content=bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"ortho")
    return httpx.Response(404)


_RealClient = httpx.AsyncClient


class FakeClient(_RealClient):
    def __init__(self, *a, **k):
        k["transport"] = httpx.MockTransport(ml)
        super().__init__(*a, **k)


drone_router.httpx.AsyncClient = FakeClient
c = TestClient(app, raise_server_exceptions=False)


def H(who):
    return {"Authorization": f"Bearer {create_access_token(str(users[who].id), 0)}"}


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail != "" else ""))


JPEG = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"x" * 64


def photos(n, data=JPEG):
    return [("files", (f"DJI_{i:04d}.JPG", data, "image/jpeg")) for i in range(n)]


A, B = H("A:org_admin"), H("B:org_admin")
r = c.post("/api/drone-surveys/", data={"site_id": "SITE-A"}, files=photos(5), headers=H("A:compliance_manager"))
check("compliance manager can't upload surveys", r.status_code == 403, r.status_code)
r = c.post("/api/drone-surveys/", data={"site_id": "SITE-B"}, files=photos(5), headers=A)
check("can't upload to another organisation's site", r.status_code == 404, r.status_code)
r = c.post("/api/drone-surveys/", data={"site_id": "SITE-A"}, files=photos(4), headers=A)
check("fewer than 5 photos refused", r.status_code == 400, r.status_code)
r = c.post("/api/drone-surveys/", data={"site_id": "SITE-A"}, files=photos(5, b"GIF89a"), headers=A)
check("non-JPEG refused", r.status_code == 400 and "not a JPEG" in r.json()["detail"], r.text)

r = c.post("/api/drone-surveys/", data={"site_id": "SITE-A", "label": "June flight"}, files=photos(6),
           headers=H("A:geologist"))
check("geologist uploads a survey", r.status_code == 201 and r.json()["state"] == "queued", r.text)
sid = r.json()["id"]
r = c.get(f"/api/drone-surveys/{sid}", headers=A)
check("poll shows progress", r.json()["state"] == "running" and r.json()["progress"] == 0.6, r.json())
check("ortho not ready while running", c.get(f"/api/drone-surveys/{sid}/ortho.jpg", headers=A).status_code == 404)
r = c.get(f"/api/drone-surveys/{sid}", headers=A)
check("job finishes", r.json()["state"] == "done" and r.json()["stats"] == {"photos_used": 5}, r.json())
t = c.get("/api/sites/SITE-A/terrain", headers=A).json()
check("site terrain is now the drone survey", t.get("droneSurveyId") == sid and t["surfaceElevations"] == GRID["elevations"]
      and t["source"].startswith("Drone survey June flight"), t)
r = c.get(f"/api/drone-surveys/{sid}/ortho.jpg", headers=A)
check("orthophoto served", r.status_code == 200 and r.headers["content-type"] == "image/jpeg")
check("model served", c.get(f"/api/drone-surveys/{sid}/model", headers=A).json()["ground"]["gridSize"] == 2)
check("other organisation can't read the survey", c.get(f"/api/drone-surveys/{sid}", headers=B).status_code == 404)
check("other organisation can't read its orthophoto", c.get(f"/api/drone-surveys/{sid}/ortho.jpg", headers=B).status_code == 404)
check("list is organisation-scoped", c.get("/api/drone-surveys/", headers=B).json() == [])
check("list by site", [s["id"] for s in c.get("/api/drone-surveys/?site_id=SITE-A", headers=A).json()] == [sid])

JOB.update(polls=0, fail=True)
r = c.post("/api/drone-surveys/", data={"site_id": "SITE-A"}, files=photos(5), headers=A)
sid2 = r.json()["id"]
r = c.get(f"/api/drone-surveys/{sid2}", headers=A)
check("failed job reports the reason", r.json()["state"] == "failed" and "overlap" in r.json()["error"], r.json())

check("geologist can't delete", c.delete(f"/api/drone-surveys/{sid}", headers=H("A:geologist")).status_code == 403)
check("org admin deletes", c.delete(f"/api/drone-surveys/{sid}", headers=A).status_code == 204)
check("deleting the survey removes its terrain", c.get("/api/sites/SITE-A/terrain", headers=A).status_code != 200)


class DownClient(_RealClient):
    def __init__(self, *a, **k):
        k["transport"] = httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("down")))
        super().__init__(*a, **k)


drone_router.httpx.AsyncClient = DownClient
r = c.post("/api/drone-surveys/", data={"site_id": "SITE-A"}, files=photos(5), headers=A)
check("processing service down -> 503 with a clear message", r.status_code == 503 and "not reachable" in r.json()["detail"], r.text)

check("uploadable sites are the organisation's own",
      [x["id"] for x in c.get("/api/drone-surveys/sites", headers=A).json()] == ["SITE-A"])
check("roles that can't upload get no sites", c.get("/api/drone-surveys/sites", headers=H("A:compliance_manager")).json() == [])

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
