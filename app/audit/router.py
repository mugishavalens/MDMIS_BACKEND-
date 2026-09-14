from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.database import get_db
from app.deps import require_role

from .models import AuditLog
from .schemas import AuditLogOut, AuditSummary

router = APIRouter(prefix="/audit", tags=["audit"])


def _scope(query, user: User):
    if user.role == "system_admin":
        return query
    return query.where(AuditLog.organisation_id == user.organisation_id)


@router.get("/", response_model=list[AuditLogOut])
async def list_audit_logs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("org_admin", "system_admin")),
):
    query = _scope(select(AuditLog), user).order_by(AuditLog.created_at.desc()).limit(200)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/summary", response_model=AuditSummary)
async def get_audit_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("org_admin", "system_admin")),
):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    events_today = await db.scalar(
        _scope(select(func.count(AuditLog.id)).where(AuditLog.created_at >= today_start), user)
    )
    return AuditSummary(eventsToday=events_today or 0)
