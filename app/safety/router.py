from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.crud import org_scoped_crud_router
from app.database import get_db
from app.deps import get_current_user

from .models import SafetyIncident
from .schemas import SafetyIncidentCreate, SafetyIncidentOut, SafetyIncidentUpdate


def _stamp_reporter(data: dict, user: User) -> dict:
    data["reported_by_id"] = user.id
    return data


router = org_scoped_crud_router(
    model=SafetyIncident,
    out_schema=SafetyIncidentOut,
    create_schema=SafetyIncidentCreate,
    update_schema=SafetyIncidentUpdate,
    prefix="/safety",
    tags=["safety"],
    on_create=_stamp_reporter,
)


@router.post("/{item_id}/acknowledge", response_model=SafetyIncidentOut)
async def acknowledge_incident(
    item_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """REQ-SAFE-003: Safety Officers acknowledge an open incident."""
    query = select(SafetyIncident).where(SafetyIncident.id == item_id)
    if user.role != "system_admin":
        query = query.where(SafetyIncident.organisation_id == user.organisation_id)
    incident = (await db.execute(query)).scalar_one_or_none()
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    incident.status = "acknowledged"
    incident.acknowledged_by_id = user.id
    incident.acknowledged_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(incident)
    return incident
