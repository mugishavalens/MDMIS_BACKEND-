from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.config import settings
from app.crud import org_scoped_crud_router
from app.database import get_db
from app.deps import get_current_user, require_service_key

from .models import MineralZone, ScanSession
from .schemas import (
    MineralZoneCreate,
    MineralZoneOut,
    MineralZoneUpdate,
    RetrainDataItem,
    ScanClassifyRequest,
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


@scan_session_router.get(
    "/retrain-data", response_model=list[RetrainDataItem], dependencies=[Depends(require_service_key)]
)
async def get_retrain_data(db: AsyncSession = Depends(get_db)):
    """Pulled by mdmis-ml-service's scripts/retrain.py: every lab_confirmed
    MineralZone paired with the spectrum its ScanSession stored. Not
    org-scoped (service-key auth, not a per-user JWT) — the ML model is
    trained across every organisation's confirmed labels, same as the
    public seed dataset it started from.

    Registered before GET /{item_id} on purpose: FastAPI/Starlette tries
    routes in registration order, and a plain "{item_id}" path segment
    would otherwise match the literal string "retrain-data" first and fail
    UUID validation instead of falling through to this route."""
    query = (
        select(MineralZone, ScanSession)
        .join(ScanSession, MineralZone.scan_session_id == ScanSession.id)
        .where(MineralZone.status == "lab_confirmed", ScanSession.raw_reading.is_not(None))
    )
    rows = (await db.execute(query)).all()
    return [
        RetrainDataItem(
            zone_id=zone.id,
            mineral_type=zone.mineral_type,
            x_values=session.raw_reading["x_values"],
            intensities=session.raw_reading["intensities"],
        )
        for zone, session in rows
    ]


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


@scan_session_router.post("/{item_id}/classify", response_model=MineralZoneOut, status_code=status.HTTP_201_CREATED)
async def classify_scan_session(
    item_id: UUID,
    payload: ScanClassifyRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """SENSORS -> ML (classification) -> BACKEND: sends the raw spectral
    reading to mdmis-ml-service and materializes its prediction as a
    MineralZone. Synchronous (not a background job) — a RandomForest
    inference over a ~200-point spectrum is a few milliseconds, so there's
    no long-running work to hide behind BackgroundTasks here."""
    session = (
        await db.execute(_scope(select(ScanSession).where(ScanSession.id == item_id), user))
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")

    session.status = "classifying"
    session.raw_reading = {"x_values": payload.x_values, "intensities": payload.intensities}
    await db.commit()

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.ml_service_url}/classify",
                json={
                    "x_values": payload.x_values,
                    "intensities": payload.intensities,
                    "sensor_type": payload.sensor_type,
                },
                headers={"X-ML-Service-Key": settings.ml_service_api_key},
            )
        resp.raise_for_status()
        result = resp.json()
    except httpx.HTTPError as e:
        session.status = "failed"
        await db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"ML service call failed: {e}")

    zone = MineralZone(
        scan_session_id=session.id,
        organisation_id=session.organisation_id,
        mineral_type=result["mineral_type"],
        confidence_score=result["confidence_score"],
        confidence_alternatives=result["confidence_alternatives"],
        model_version=result["model_version"],
    )
    db.add(zone)
    session.status = "complete"
    await db.commit()
    await db.refresh(zone)
    return zone
