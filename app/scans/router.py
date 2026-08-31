from app.crud import org_scoped_crud_router

from .models import MineralZone, ScanSession
from .schemas import (
    MineralZoneCreate,
    MineralZoneOut,
    MineralZoneUpdate,
    ScanSessionCreate,
    ScanSessionOut,
    ScanSessionUpdate,
)


def _stamp_operator(data: dict, user) -> dict:
    data["operator_id"] = user.id
    return data


scan_session_router = org_scoped_crud_router(
    model=ScanSession,
    out_schema=ScanSessionOut,
    create_schema=ScanSessionCreate,
    update_schema=ScanSessionUpdate,
    prefix="/scans",
    tags=["scans"],
    on_create=_stamp_operator,
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
