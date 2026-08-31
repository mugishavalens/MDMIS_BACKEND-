from app.crud import org_scoped_crud_router

from .models import Site
from .schemas import SiteCreate, SiteOut, SiteUpdate

router = org_scoped_crud_router(
    model=Site,
    out_schema=SiteOut,
    create_schema=SiteCreate,
    update_schema=SiteUpdate,
    prefix="/sites",
    tags=["sites"],
    id_type=str,
)
