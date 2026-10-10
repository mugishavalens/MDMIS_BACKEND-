import httpx
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.config import settings
from app.crud import org_scoped_crud_router
from app.database import get_db
from app.deps import get_current_user

from .models import Site
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
    """The 3D block's ground surface (frontend DemGrid shape), proxied from
    mdmis-ml-service. Proxied rather than called from the browser because
    the ML service needs ML_SERVICE_API_KEY, which must never reach the
    frontend — and so the same org scoping as every other site route
    applies before anything is fetched."""
    query = select(Site).where(Site.id == site_id)
    if user.role != "system_admin":
        query = query.where(Site.organisation_id == user.organisation_id)
    if (await db.execute(query)).scalar_one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{settings.ml_service_url}/terrain/{site_id}",
                headers={"X-ML-Service-Key": settings.ml_service_api_key},
            )
    except httpx.HTTPError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ML service unreachable: {e}")
    if resp.status_code == 404:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No terrain ingested for this site yet.")
    if resp.status_code != 200:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ML service error {resp.status_code}.")
    return resp.json()
