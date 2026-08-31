from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.accounts.router import router as auth_router
from app.compliance.router import router as compliance_router
from app.config import settings
from app.safety.router import router as safety_router
from app.scans.router import mineral_zone_router, scan_session_router
from app.sites.router import router as sites_router
from app.traceability.router import batch_router, custody_event_router
from app.transport.router import router as transport_router

app = FastAPI(title="MDMIS Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "mdmis-backend"}


app.include_router(auth_router, prefix="/api")
app.include_router(sites_router, prefix="/api")
app.include_router(scan_session_router, prefix="/api")
app.include_router(mineral_zone_router, prefix="/api")
app.include_router(batch_router, prefix="/api")
app.include_router(custody_event_router, prefix="/api")
app.include_router(safety_router, prefix="/api")
app.include_router(transport_router, prefix="/api")
app.include_router(compliance_router, prefix="/api")
