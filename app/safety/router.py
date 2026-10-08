from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.accounts.models import User
from app.audit.service import log_event
from app.database import get_db
from app.deps import get_current_user, require_role

from .models import IncidentEvent, SafetyIncident, SafetyRule
from .rules import ensure_default_rules
from .schemas import (
    IncidentEventOut,
    IncidentNoteIn,
    IncidentStatusChange,
    SafetyIncidentCreate,
    SafetyIncidentDetailOut,
    SafetyIncidentOut,
    SafetyIncidentUpdate,
    SafetyRuleCreate,
    SafetyRuleOut,
    SafetyRuleUpdate,
)

# Hand-written rather than the generic CRUD factory (same reason scans'
# scan_session_router is) so the response can include reportedByName /
# acknowledgedByName / resolvedByName via joins to accounts.models.User.
router = APIRouter(prefix="/safety", tags=["safety"])
# Separate top-level prefix so "/safety/rules" can't be mistaken for an incident id.
rules_router = APIRouter(prefix="/safety-rules", tags=["safety"])

# Roles that may act on incidents (acknowledge/escalate/resolve/reopen) —
# matches the frontend's safety.acknowledge permission. system_admin passes.
require_responder = require_role("mine_manager", "org_admin")

Reporter = aliased(User)
Acknowledger = aliased(User)
Resolver = aliased(User)

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"acknowledged", "escalated", "resolved"},
    "acknowledged": {"escalated", "resolved"},
    "escalated": {"acknowledged", "resolved"},
    "resolved": {"open"},
}
# Changes that must say why — they're the ones someone reviews later.
_NOTE_REQUIRED = {"escalated", "resolved", "open"}
_EVENT_FOR_STATUS = {"acknowledged": "acknowledged", "escalated": "escalated", "resolved": "resolved", "open": "reopened"}
_AUDIT_FOR_STATUS = {
    "acknowledged": "safety.acknowledge",
    "escalated": "safety.escalate",
    "resolved": "safety.resolve",
    "open": "safety.reopen",
}


def _scope(query, user: User):
    if user.role == "system_admin":
        return query
    return query.where(SafetyIncident.organisation_id == user.organisation_id)


def _joined_query():
    return (
        select(SafetyIncident, Reporter, Acknowledger, Resolver)
        .outerjoin(Reporter, SafetyIncident.reported_by_id == Reporter.id)
        .outerjoin(Acknowledger, SafetyIncident.acknowledged_by_id == Acknowledger.id)
        .outerjoin(Resolver, SafetyIncident.resolved_by_id == Resolver.id)
    )


def _build_out(
    incident: SafetyIncident, reporter: User | None, acknowledger: User | None, resolver: User | None = None
) -> SafetyIncidentOut:
    out = SafetyIncidentOut.model_validate(incident)
    return out.model_copy(update={
        # Sensor-raised incidents have no human reporter; name the sensor.
        "reportedByName": reporter.full_name if reporter else (incident.source_label or None),
        "acknowledgedByName": acknowledger.full_name if acknowledger else None,
        "resolvedByName": resolver.full_name if resolver else None,
    })


async def _get_row(db: AsyncSession, user: User, item_id: UUID):
    row = (await db.execute(_scope(_joined_query(), user).where(SafetyIncident.id == item_id))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return row


async def _reload_out(db: AsyncSession, user: User, item_id: UUID) -> SafetyIncidentOut:
    return _build_out(*(await _get_row(db, user, item_id)))


def _add_event(db: AsyncSession, incident: SafetyIncident, user: User, event_type: str, note: str = "") -> None:
    db.add(IncidentEvent(
        incident_id=incident.id, event_type=event_type, note=note, actor_id=user.id, actor_name=user.full_name,
    ))


async def _apply_status(db: AsyncSession, obj: SafetyIncident, user: User, new: str, note: str) -> None:
    if new not in _ALLOWED_TRANSITIONS.get(obj.status, set()):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Can't change a {obj.status} incident to {new}.")
    if new in _NOTE_REQUIRED and not note.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add a note explaining this change.")
    now = datetime.now(timezone.utc)
    obj.status = new
    if new == "acknowledged" and obj.acknowledged_at is None:
        obj.acknowledged_by_id, obj.acknowledged_at = user.id, now
    elif new == "resolved":
        obj.resolved_by_id, obj.resolved_at = user.id, now
    elif new == "open":
        obj.resolved_by_id = obj.resolved_at = None
    _add_event(db, obj, user, _EVENT_FOR_STATUS[new], note.strip())
    await log_event(db, user, _AUDIT_FOR_STATUS[new], "safety_incident", str(obj.id), note.strip() or obj.incident_type)


@router.get("/", response_model=list[SafetyIncidentOut])
async def list_incidents(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (await db.execute(_scope(_joined_query(), user).order_by(SafetyIncident.created_at.desc()))).all()
    return [_build_out(*r) for r in rows]


@router.get("/{item_id}", response_model=SafetyIncidentDetailOut)
async def get_incident(item_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    out = _build_out(*(await _get_row(db, user, item_id)))
    events = (
        await db.execute(
            select(IncidentEvent).where(IncidentEvent.incident_id == item_id).order_by(IncidentEvent.created_at)
        )
    ).scalars().all()
    return SafetyIncidentDetailOut(
        **out.model_dump(), events=[IncidentEventOut.model_validate(e) for e in events]
    )


@router.post("/", response_model=SafetyIncidentOut, status_code=status.HTTP_201_CREATED)
async def create_incident(
    payload: SafetyIncidentCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    incident = SafetyIncident(**payload.model_dump(), organisation_id=user.organisation_id, reported_by_id=user.id)
    db.add(incident)
    await db.flush()  # populate incident.id (default=uuid.uuid4 applies at flush, not construction)
    _add_event(db, incident, user, "reported", payload.description)
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
    return await _reload_out(db, user, item_id)


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
    item_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_responder)
):
    """REQ-SAFE-003: Safety Officers acknowledge an open incident."""
    obj = (await _get_row(db, user, item_id))[0]
    await _apply_status(db, obj, user, "acknowledged", "")
    await db.commit()
    return await _reload_out(db, user, item_id)


@router.post("/{item_id}/status", response_model=SafetyIncidentOut)
async def change_incident_status(
    item_id: UUID,
    payload: IncidentStatusChange,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_responder),
):
    obj = (await _get_row(db, user, item_id))[0]
    await _apply_status(db, obj, user, payload.status, payload.note)
    await db.commit()
    return await _reload_out(db, user, item_id)


@router.post("/{item_id}/notes", response_model=IncidentEventOut, status_code=status.HTTP_201_CREATED)
async def add_incident_note(
    item_id: UUID, payload: IncidentNoteIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Any member of the organisation can add a field observation."""
    obj = (await _get_row(db, user, item_id))[0]
    event = IncidentEvent(
        incident_id=obj.id, event_type="note", note=payload.note.strip(), actor_id=user.id, actor_name=user.full_name,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return IncidentEventOut.model_validate(event)


# ---- Threshold rules (REQ-SAFE-001) -------------------------------------------


def _rule_scope(query, user: User):
    if user.role == "system_admin":
        return query
    return query.where(SafetyRule.organisation_id == user.organisation_id)


async def _get_rule(db: AsyncSession, user: User, rule_id: UUID) -> SafetyRule:
    rule = (await db.execute(_rule_scope(select(SafetyRule).where(SafetyRule.id == rule_id), user))).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found.")
    return rule


@rules_router.get("/", response_model=list[SafetyRuleOut])
async def list_rules(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if user.organisation_id is not None:
        await ensure_default_rules(db, user.organisation_id)
        await db.commit()
    rows = (await db.execute(_rule_scope(select(SafetyRule), user).order_by(SafetyRule.metric, SafetyRule.site_id))).scalars()
    return [SafetyRuleOut.model_validate(r) for r in rows]


@rules_router.post("/", response_model=SafetyRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(payload: SafetyRuleCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_responder)):
    if user.organisation_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account has no organisation.")
    rule = SafetyRule(**payload.model_dump(), organisation_id=user.organisation_id)
    db.add(rule)
    await log_event(db, user, "safety.rule_create", "safety_rule", "", f"{rule.metric} {rule.comparator} {rule.threshold}")
    await db.commit()
    await db.refresh(rule)
    return SafetyRuleOut.model_validate(rule)


@rules_router.patch("/{rule_id}", response_model=SafetyRuleOut)
async def update_rule(
    rule_id: UUID, payload: SafetyRuleUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(require_responder)
):
    rule = await _get_rule(db, user, rule_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    await log_event(db, user, "safety.rule_update", "safety_rule", str(rule.id),
                    f"{rule.metric} {rule.comparator} {rule.threshold} enabled={rule.enabled}")
    await db.commit()
    await db.refresh(rule)
    return SafetyRuleOut.model_validate(rule)


@rules_router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_responder)):
    rule = await _get_rule(db, user, rule_id)
    await log_event(db, user, "safety.rule_delete", "safety_rule", str(rule.id), rule.metric)
    await db.delete(rule)
    await db.commit()

