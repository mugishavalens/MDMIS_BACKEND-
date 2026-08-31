from app.crud import org_scoped_crud_router

from .models import ComplianceReport
from .schemas import ComplianceReportCreate, ComplianceReportOut, ComplianceReportUpdate


def _stamp_generator(data: dict, user) -> dict:
    data["generated_by_id"] = user.id
    return data


router = org_scoped_crud_router(
    model=ComplianceReport,
    out_schema=ComplianceReportOut,
    create_schema=ComplianceReportCreate,
    update_schema=ComplianceReportUpdate,
    prefix="/compliance",
    tags=["compliance"],
    on_create=_stamp_generator,
)
