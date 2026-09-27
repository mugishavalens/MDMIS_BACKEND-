"""Shared audit-logging utility, imported by any domain that has a
security/compliance-relevant mutation to record — the same category of
import as app.deps/app.database that every router already makes; this is
infrastructure, not a domain-to-domain reach-in.

Deliberately NOT wired into every single CRUD endpoint across every domain
— only the actions that actually matter for an audit trail (invites,
custody events, non-compliance flags, safety acknowledgements). A blanket
wrapper around every PATCH would be noise, not signal.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User

from .models import AuditLog


async def log_event(
    db: AsyncSession,
    user: User | None,
    action: str,
    resource_type: str,
    resource_id: str = "",
    detail: str = "",
) -> None:
    """Adds the audit row to the session without committing — the caller's
    own db.commit() (already happening right after their mutation) persists
    both together, atomically."""
    if user is None:
        return
    db.add(AuditLog(
        organisation_id=user.organisation_id,
        actor_id=user.id,
        actor_name=user.full_name,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        detail=detail,
    ))
