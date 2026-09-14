from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.accounts.models import User
from app.audit.service import log_event
from app.database import get_db
from app.deps import get_current_user

from .models import SafetyIncident
from .schemas import SafetyIncidentCreate, SafetyIncidentOut, SafetyIncidentUpdate

# Hand-written rather than the generic CRUD factory (same reason scans'
# scan_session_router is) so the response can include reportedByName /
# acknowledgedByName via joins to accounts.models.User.
router = APIRouter(prefix="/safety", tags=["safety"])

Reporter = aliased(User)
Acknowledger = aliased(User)


def _scope(query, user: User):
    if user.role == "system_admin":
        return query
    return query.where(SafetyIncident.organisation_id == user.organisation_id)


def _joined_query():
    return (
        select(SafetyIncident, Reporter, Acknowledger)
        .outerjoin(Reporter, SafetyIncident.reported_by_id == Reporter.id)
        .outerjoin(Acknowledger, SafetyIncident.acknowledged_by_id == Acknowledger.id)
    )


def _build_out(incident: SafetyIncident, reporter: User | None, acknowledger: User | None) -> SafetyIncidentOut:
    out = SafetyIncidentOut.model_validate(incident)
    return out.model_copy(update={
        "reportedByName": reporter.full_name if reporter else None,
        "acknowledgedByName": acknowledger.full_name if acknowledger else None,
    })


@router.get("/", response_model=list[SafetyIncidentOut])
async def list_incidents(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (await db.execute(_scope(_joined_query(), user))).all()
    return [_build_out(i, r, a) for i, r, a in rows]


@router.get("/{item_id}", response_model=SafetyIncidentOut)
async def get_incident(item_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    row = (await db.execute(_scope(_joined_query(), user).where(SafetyIncident.id == item_id))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    incident, reporter, acknowledger = row
    return _build_out(incident, reporter, acknowledger)


@router.post("/", response_model=SafetyIncidentOut, status_code=status.HTTP_201_CREATED)
async def create_incident(
    payload: SafetyIncidentCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    incident = SafetyIncident(**payload.model_dump(), organisation_id=user.organisation_id, reported_by_id=user.id)
    db.add(incident)
    await db.flush()  # populate incident.id (default=uuid.uuid4 applies at flush, not construction)
    await log_event(db, user, "safety.report", "safety_incident", str(incident.id), payload.incident_type)
    await db.commit()
    await db.refresh(incident)
    return _build_out(incident, user, None)


@router.patch("/{item_id}", response_model=SafetyIncidentOut)
async def update_incident(
    item_id: UUID,
    payload: SafetyIncidentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    obj = (
        await db.execute(_scope(select(SafetyIncident).where(SafetyIncident.id == item_id), user))
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    await db.commit()
    await db.refresh(obj)
    reporter = await db.get(User, obj.reported_by_id) if obj.reported_by_id else None
    acknowledger = await db.get(User, obj.acknowledged_by_id) if obj.acknowledged_by_id else None
    return _build_out(obj, reporter, acknowledger)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_incident(item_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    obj = (
        await db.execute(_scope(select(SafetyIncident).where(SafetyIncident.id == item_id), user))
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    await db.delete(obj)
    await db.commit()


@router.post("/{item_id}/acknowledge", response_model=SafetyIncidentOut)
async def acknowledge_incident(
    item_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """REQ-SAFE-003: Safety Officers acknowledge an open incident."""
    obj = (
        await db.execute(_scope(select(SafetyIncident).where(SafetyIncident.id == item_id), user))
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    obj.status = "acknowledged"
    obj.acknowledged_by_id = user.id
    obj.acknowledged_at = datetime.now(timezone.utc)
    await log_event(db, user, "safety.acknowledge", "safety_incident", str(obj.id), obj.incident_type)
    await db.commit()
    await db.refresh(obj)
    reporter = await db.get(User, obj.reported_by_id) if obj.reported_by_id else None
    return _build_out(obj, reporter, user)
