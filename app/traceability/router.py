from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.audit.service import log_event
from app.database import get_db
from app.deps import get_current_user

from .models import CustodyEvent, MineralBatch
from .schemas import CustodyEventCreate, CustodyEventOut, MineralBatchCreate, MineralBatchOut, MineralBatchUpdate

# Two separate routers with distinct top-level prefixes — NOT
# /traceability/events nested under /traceability/{batch_id} — so a
# request for "events" can never be mis-routed as a batch_id lookup.
batch_router = APIRouter(prefix="/traceability", tags=["traceability"])
custody_event_router = APIRouter(prefix="/custody-events", tags=["traceability"])


def _scope_batches(query, user: User):
    if user.role == "system_admin":
        return query
    return query.where(MineralBatch.organisation_id == user.organisation_id)


def _build_batch_out(batch: MineralBatch) -> MineralBatchOut:
    """currentStage isn't a stored column — custody events are an immutable
    append-only log (REQ-TRACE-003), so "current stage" is derived from the
    latest event each time rather than cached and risking drift."""
    stage = max(batch.events, key=lambda e: e.timestamp).event_type if batch.events else "extraction"
    return MineralBatchOut.model_validate(batch).model_copy(update={"currentStage": stage})


@batch_router.get("/", response_model=list[MineralBatchOut])
async def list_batches(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(_scope_batches(select(MineralBatch), user))
    return [_build_batch_out(b) for b in result.scalars().all()]


@batch_router.post("/", response_model=MineralBatchOut, status_code=status.HTTP_201_CREATED)
async def create_batch(
    payload: MineralBatchCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """REQ-TRACE-001: system-generated, permanent coc_id:
    COC-{SITE_CODE}-{YYYYMMDD}-{SEQUENCE}."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"COC-{payload.site_id}-{today}"
    count = await db.scalar(
        select(func.count()).select_from(MineralBatch).where(MineralBatch.coc_id.like(f"{prefix}%"))
    )
    coc_id = f"{prefix}-{(count or 0) + 1:04d}"

    batch = MineralBatch(
        **payload.model_dump(),
        coc_id=coc_id,
        organisation_id=user.organisation_id,
        created_by_id=user.id,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch, attribute_names=["events"])
    return _build_batch_out(batch)


@batch_router.get("/{batch_id}", response_model=MineralBatchOut)
async def get_batch(batch_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    obj = (
        await db.execute(_scope_batches(select(MineralBatch).where(MineralBatch.id == batch_id), user))
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return _build_batch_out(obj)


@batch_router.patch("/{batch_id}", response_model=MineralBatchOut)
async def update_batch(
    batch_id: UUID,
    payload: MineralBatchUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    obj = (
        await db.execute(_scope_batches(select(MineralBatch).where(MineralBatch.id == batch_id), user))
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(obj, field, value)
    if updates.get("compliant") is False:
        await log_event(
            db, user, "batch.flag_noncompliant", "mineral_batch", str(obj.id),
            obj.compliance_note or "Marked non-compliant",
        )
    await db.commit()
    await db.refresh(obj, attribute_names=["events"])
    return _build_batch_out(obj)


# --- Custody events: create/list/retrieve only — immutable, per REQ-TRACE-003 ---


@custody_event_router.get("/", response_model=list[CustodyEventOut])
async def list_custody_events(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(CustodyEvent).join(MineralBatch)
    if user.role != "system_admin":
        query = query.where(MineralBatch.organisation_id == user.organisation_id)
    result = await db.execute(query)
    return result.scalars().all()


@custody_event_router.post("/", response_model=CustodyEventOut, status_code=status.HTTP_201_CREATED)
async def create_custody_event(
    payload: CustodyEventCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    batch = (
        await db.execute(_scope_batches(select(MineralBatch).where(MineralBatch.id == payload.batch_id), user))
    ).scalar_one_or_none()
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mineral batch not found.")

    event = CustodyEvent(**payload.model_dump(), authorised_by_id=user.id)
    db.add(event)
    if event.flagged:
        await db.flush()  # populate event.id (default=uuid.uuid4 applies at flush, not construction)
        await log_event(
            db, user, "custody.flag", "custody_event", str(event.id),
            f"{event.event_type}: {event.from_party} -> {event.to_party}",
        )
    await db.commit()
    await db.refresh(event)
    return event


@custody_event_router.get("/{event_id}", response_model=CustodyEventOut)
async def get_custody_event(event_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(CustodyEvent).join(MineralBatch).where(CustodyEvent.id == event_id)
    if user.role != "system_admin":
        query = query.where(MineralBatch.organisation_id == user.organisation_id)
    obj = (await db.execute(query)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return obj
