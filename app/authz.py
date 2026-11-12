"""Who may change what, and checks that referenced records belong to the
caller's organisation.

Role groups mirror the frontend's PERMISSIONS table (lib/rbac.ts), so a
button the UI shows is one the API allows. system_admin passes every
check (require_role). Reading stays open to every role in the org; these
groups only gate writes.
"""
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User

# map.annotate
SITE_EDITORS = ("org_admin", "geologist", "mine_manager")
# scans.classify
SCAN_EDITORS = ("org_admin", "geologist", "mine_manager")
# Marking a zone lab_confirmed makes it training ground truth for the ML
# model (scripts/retrain.py), so only geologists and org admins can.
LAB_CONFIRMERS = ("org_admin", "geologist")
# traceability.edit: batches and custody events
TRACE_EDITORS = ("org_admin", "mine_manager")
# compliance.submit / compliance.edit: reports and a batch's compliance verdict
COMPLIANCE_EDITORS = ("org_admin", "compliance_manager")
# safety.acknowledge
SAFETY_RESPONDERS = ("org_admin", "mine_manager")
# Deleting is permanent: organisation owners only.
DELETERS = ("org_admin",)


def has_role(user: User, roles: tuple[str, ...]) -> bool:
    return user.role == "system_admin" or user.role in roles


def check_role(user: User, roles: tuple[str, ...], action: str = "do this") -> None:
    if not has_role(user, roles):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role can't {action}.")


async def get_owned(db: AsyncSession, model: Any, obj_id: Any, user: User, label: str = "Record") -> Any:
    """The referenced row, if the caller's organisation owns it; 404
    otherwise (same answer as "doesn't exist", so IDs can't be probed)."""
    obj = await db.get(model, obj_id) if obj_id is not None else None
    if obj is None or (user.role != "system_admin" and obj.organisation_id != user.organisation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found.")
    return obj
