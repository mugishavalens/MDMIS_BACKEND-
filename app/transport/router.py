from app.crud import org_scoped_crud_router

from .models import Shipment
from .schemas import ShipmentCreate, ShipmentOut, ShipmentUpdate

router = org_scoped_crud_router(
    model=Shipment,
    out_schema=ShipmentOut,
    create_schema=ShipmentCreate,
    update_schema=ShipmentUpdate,
    prefix="/transport",
    tags=["transport"],
)
