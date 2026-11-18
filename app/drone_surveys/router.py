"""Drone surveys: upload a flight's photos for a site, follow the
reconstruction, and get a 3D block (bare ground, surface, orthophoto).

The heavy work runs in mdmis-ml-service (POST /reconstructions there). This
router forwards the upload with the service key (which never reaches the
browser), mirrors the job's progress on each poll, and when the job is done
copies the result here and makes it the site's terrain."""
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.audit.service import log_event
from app.authz import DELETERS, SITE_EDITORS, check_role, get_owned
from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.sites.models import Site, SiteTerrain

from .models import DroneSurvey

router = APIRouter(prefix="/drone-surveys", tags=["drone-surveys"])

MAX_PHOTOS = 600
MAX_PHOTO_BYTES = 30 * 1024 * 1024
MAX_TOTAL_BYTES = 400 * 1024 * 1024
JPEG_MAGIC = bytes([0xFF, 0xD8, 0xFF])
TERMINAL = ("done", "failed")


class DroneSurveyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    site_id: str
    label: str
    photo_count: int
    state: str
    stage: str
    progress: float
    message: str
    error: str
    stats: dict | None
    created_at: datetime
    completed_at: datetime | None


def _ml_headers() -> dict:
    if not settings.ml_service_key_usable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Drone processing is not configured on this server.")
    return {"X-ML-Service-Key": settings.ml_service_api_key}


async def _readable(db: AsyncSession, survey_id: uuid.UUID, user: User) -> DroneSurvey:
    """Own organisation's surveys, plus those of shared demo sites (their 3D
    block is public to every organisation)."""
    q = select(DroneSurvey).join(Site, Site.id == DroneSurvey.site_id).where(DroneSurvey.id == survey_id)
    if user.role != "system_admin":
        q = q.where(or_(DroneSurvey.organisation_id == user.organisation_id, Site.is_shared.is_(True)))
    survey = (await db.execute(q)).scalar_one_or_none()
    if survey is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return survey


@router.post("/", response_model=DroneSurveyOut, status_code=status.HTTP_201_CREATED)
async def create_survey(
    site_id: str = Form(...),
    label: str = Form(""),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_role(user, SITE_EDITORS, "upload drone surveys")
    site = await get_owned(db, Site, site_id, user, "site")
    if not 5 <= len(files) <= MAX_PHOTOS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Upload between 5 and {MAX_PHOTOS} photos.")
    parts, total = [], 0
    for f in files:
        data = await f.read(MAX_PHOTO_BYTES + 1)
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{f.filename}: larger than 30 MB.")
        if not data.startswith(JPEG_MAGIC):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{f.filename}: not a JPEG photo.")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Upload larger than 400 MB; let the page shrink the photos first.")
        parts.append(("files", (f.filename or "photo.jpg", data, "image/jpeg")))
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10)) as client:
            resp = await client.post(f"{settings.ml_service_url}/reconstructions", files=parts,
                                     data={"label": f"{site.id} {label}"[:200]}, headers=_ml_headers())
    except httpx.HTTPError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The drone processing service is not reachable right now.")
    if resp.status_code == 400:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, resp.json().get("detail", "Photos rejected."))
    if resp.status_code != 202:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Drone processing service error {resp.status_code}.")
    job = resp.json()
    survey = DroneSurvey(organisation_id=site.organisation_id, site_id=site.id, created_by_id=user.id,
                         label=label[:200], photo_count=len(parts), ml_job_id=job["id"], state=job["state"],
                         stage=job.get("stage", "queued"), message=job.get("message", "")[:300])
    db.add(survey)
    await log_event(db, user, "drone_survey.create", "drone_survey", str(survey.id),
                    f"Uploaded {len(parts)} drone photos for {site.id}")
    await db.commit()
    await db.refresh(survey)
    return survey


@router.get("/sites")
async def uploadable_sites(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Sites the caller may upload a survey for: their organisation's own
    (shared demo sites of other organisations are read-only)."""
    from app.authz import has_role
    if not has_role(user, SITE_EDITORS):
        return []
    q = select(Site.id, Site.name).order_by(Site.name)
    if user.role != "system_admin":
        q = q.where(Site.organisation_id == user.organisation_id)
    return [{"id": i, "name": n} for i, n in (await db.execute(q)).all()]


@router.get("/", response_model=list[DroneSurveyOut])
async def list_surveys(site_id: str | None = None, db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    q = select(DroneSurvey).order_by(DroneSurvey.created_at.desc())
    if user.role != "system_admin":
        q = q.where(DroneSurvey.organisation_id == user.organisation_id)
    if site_id:
        q = q.where(DroneSurvey.site_id == site_id)
    return (await db.execute(q)).scalars().all()


async def _collect_result(db: AsyncSession, survey: DroneSurvey, client: httpx.AsyncClient) -> None:
    base = f"{settings.ml_service_url}/reconstructions/{survey.ml_job_id}"
    got = {}
    for name in ("ground.json", "surface.json", "cloud.json", "ortho.jpg"):
        r = await client.get(f"{base}/{name}", headers=_ml_headers())
        r.raise_for_status()
        got[name] = r.content if name.endswith(".jpg") else r.json()
    survey.ground, survey.surface, survey.cloud = got["ground.json"], got["surface.json"], got["cloud.json"]
    survey.ortho = got["ortho.jpg"]
    # the site's 3D block now shows this survey: bare ground as the surface,
    # the trees/boulders layer and orthophoto alongside
    grid = {**survey.ground, "surfaceElevations": survey.surface["elevations"],
            "droneSurveyId": str(survey.id),
            "source": f"Drone survey{(' ' + survey.label) if survey.label else ''}, "
                      f"{datetime.now(timezone.utc):%Y-%m-%d}"}
    terrain = await db.get(SiteTerrain, survey.site_id)
    if terrain is None:
        db.add(SiteTerrain(site_id=survey.site_id, grid=grid, source=grid["source"][:200]))
    else:
        terrain.grid, terrain.source = grid, grid["source"][:200]


@router.get("/{survey_id}", response_model=DroneSurveyOut)
async def get_survey(survey_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Polling this refreshes progress from the processing service; the call
    that sees the job finish also stores the result."""
    survey = await _readable(db, survey_id, user)
    if survey.state in TERMINAL:
        return survey
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{settings.ml_service_url}/reconstructions/{survey.ml_job_id}", headers=_ml_headers())
            if r.status_code == 404:
                survey.state, survey.error = "failed", "The processing service lost this job; upload the photos again."
            elif r.status_code == 200:
                job = r.json()
                survey.stage, survey.progress = job.get("stage", survey.stage), float(job.get("progress", 0))
                survey.message = str(job.get("message", ""))[:300]
                if job["state"] == "done":
                    await _collect_result(db, survey, client)
                    survey.stats, survey.state, survey.progress = job.get("stats"), "done", 1.0
                    survey.completed_at = datetime.now(timezone.utc)
                elif job["state"] == "failed":
                    survey.state, survey.error = "failed", str(job.get("error", "Reconstruction failed."))[:500]
                    survey.completed_at = datetime.now(timezone.utc)
                else:
                    survey.state = job["state"]
    except httpx.HTTPError:
        survey.message = "Processing service not reachable; still waiting."
    await db.commit()
    await db.refresh(survey)
    return survey


@router.get("/{survey_id}/ortho.jpg")
async def get_ortho(survey_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    survey = await _readable(db, survey_id, user)
    if survey.ortho is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not ready yet.")
    return Response(survey.ortho, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/{survey_id}/model")
async def get_model(survey_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Ground and surface grids plus the point sample, for the survey viewer."""
    survey = await _readable(db, survey_id, user)
    if survey.ground is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not ready yet.")
    return {"ground": survey.ground, "surface": survey.surface, "cloud": survey.cloud, "stats": survey.stats}


@router.delete("/{survey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_survey(survey_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    check_role(user, DELETERS, "delete drone surveys")
    survey = await get_owned(db, DroneSurvey, survey_id, user, "drone survey")
    terrain = await db.get(SiteTerrain, survey.site_id)
    if terrain is not None and terrain.grid.get("droneSurveyId") == str(survey.id):
        await db.delete(terrain)  # the block falls back to the public elevation model
    await db.delete(survey)
    await db.commit()
