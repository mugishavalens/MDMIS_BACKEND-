from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.crud import org_scoped_crud_router
from app.database import get_db
from app.deps import get_current_user

from .models import MineralZone, ScanSession
from .schemas import (
    MineralZoneCreate,
    MineralZoneOut,
    MineralZoneUpdate,
    ScanSessionCreate,
    ScanSessionOut,
    ScanSessionUpdate,
)

mineral_zone_router = org_scoped_crud_router(
    model=MineralZone,
    out_schema=MineralZoneOut,
    create_schema=MineralZoneCreate,
    update_schema=MineralZoneUpdate,
    # Deliberately NOT nested under /scans: a path like /scans/{item_id}
    # (scan_session_router's detail route) would otherwise shadow
    # /scans/zones since both match "/scans/<one segment>".
    prefix="/mineral-zones",
    tags=["scans"],
)

# scan_session_router is hand-written rather than the generic CRUD factory
# (same reason traceability's batch_router is) so the response can include
# operatorName via a join to accounts.models.User — the frontend has no
# other legitimate way to resolve operator_id to a display name.
scan_session_router = APIRouter(prefix="/scans", tags=["scans"])


def _scope(query, user: User):
    if user.role == "system_admin":
        return query
    return query.where(ScanSession.organisation_id == user.organisation_id)


def _build_session_out(session: ScanSession, operator: User | None) -> ScanSessionOut:
    out = ScanSessionOut.model_validate(session)
    return out.model_copy(update={"operatorName": operator.full_name if operator else None})


@scan_session_router.get("/", response_model=list[ScanSessionOut])
async def list_scan_sessions(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    query = _scope(select(ScanSession, User).outerjoin(User, ScanSession.operator_id == User.id), user)
    rows = (await db.execute(query)).all()
    return [_build_session_out(session, operator) for session, operator in rows]


@scan_session_router.get("/{item_id}", response_model=ScanSessionOut)
async def get_scan_session(item_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    query = _scope(
        select(ScanSession, User).outerjoin(User, ScanSession.operator_id == User.id).where(ScanSession.id == item_id),
        user,
    )
    row = (await db.execute(query)).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    session, operator = row
    return _build_session_out(session, operator)


@scan_session_router.post("/", response_model=ScanSessionOut, status_code=status.HTTP_201_CREATED)
async def create_scan_session(
    payload: ScanSessionCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    session = ScanSession(**payload.model_dump(), organisation_id=user.organisation_id, operator_id=user.id)
    db.add(session)
    await db.commit()
    await db.refresh(session, attribute_names=["zones"])
    return _build_session_out(session, user)


@scan_session_router.patch("/{item_id}", response_model=ScanSessionOut)
async def update_scan_session(
    item_id: UUID,
    payload: ScanSessionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    obj = (await db.execute(_scope(select(ScanSession).where(ScanSession.id == item_id), user))).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    await db.commit()
    await db.refresh(obj, attribute_names=["zones"])
    operator = await db.get(User, obj.operator_id) if obj.operator_id else None
    return _build_session_out(obj, operator)


@scan_session_router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scan_session(item_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    obj = (await db.execute(_scope(select(ScanSession).where(ScanSession.id == item_id), user))).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    await db.delete(obj)
    await db.commit()
