import httpx
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.config import settings
from app.crud import org_scoped_crud_router
from app.database import get_db
from app.deps import get_current_user

from .models import Site, SiteTerrain
from .schemas import SiteCreate, SiteOut, SiteUpdate

router = org_scoped_crud_router(
    model=Site,
    out_schema=SiteOut,
    create_schema=SiteCreate,
    update_schema=SiteUpdate,
    prefix="/sites",
    tags=["sites"],
    id_type=str,
)


@router.get("/{site_id}/terrain")
async def get_site_terrain(site_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """The 3D block's ground surface (frontend DemGrid shape).

    Served from the site_terrains table, so the deployed app needs only the
    backend. If a site has no stored terrain yet, ask mdmis-ml-service once
    and store what it returns (handy in local dev, where ingest_terrain.py
    writes to the ML service's folder). The ML service needs
    ML_SERVICE_API_KEY, which must never reach the frontend, and the same
    org scoping as every other site route applies before anything is read."""
    query = select(Site).where(Site.id == site_id)
    if user.role != "system_admin":
        query = query.where(Site.organisation_id == user.organisation_id)
    if (await db.execute(query)).scalar_one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")

    stored = await db.get(SiteTerrain, site_id)
    if stored is not None:
        return stored.grid

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{settings.ml_service_url}/terrain/{site_id}",
                headers={"X-ML-Service-Key": settings.ml_service_api_key},
            )
    except httpx.HTTPError:
        # Not a 502: no stored terrain and no ML service (the deployed setup)
        # just means this site has no terrain; the frontend falls back.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No terrain stored for this site yet.")
    if resp.status_code == 404:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No terrain ingested for this site yet.")
    if resp.status_code != 200:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ML service error {resp.status_code}.")
    grid = resp.json()
    db.add(SiteTerrain(site_id=site_id, grid=grid, source=str(grid.get("source", ""))[:200]))
    await db.commit()
    return grid
