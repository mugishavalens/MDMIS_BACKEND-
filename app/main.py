from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.accounts.router import accounts_router, router as auth_router
from app.audit.router import router as audit_router
from app.compliance.router import router as compliance_router
from app.config import settings
from app.dashboard.router import router as dashboard_router
from app.ingestion.router import devices_router, files_router, ingest_router, readings_router
from app.safety.router import router as safety_router, rules_router as safety_rules_router
from app.scans.router import mineral_zone_router, scan_session_router
from app.sites.router import router as sites_router
from app.traceability.router import batch_router, custody_event_router
from app.transport.router import driver_router, router as transport_router, vehicle_router

settings.check_production_secrets()

app = FastAPI(
    title="MDMIS Backend",
    version="1.0.0",
    # The API docs list every route and schema; off in production unless
    # API_DOCS_ENABLED=true.
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    # JSON and file downloads only: nothing here should ever run as a page.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        # /docs serves an HTML page with scripts; leave its CSP alone.
        if name == "Content-Security-Policy" and request.url.path in ("/docs", "/redoc"):
            continue
        response.headers.setdefault(name, value)
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=settings.cors_allowed_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "mdmis-backend"}


app.include_router(auth_router, prefix="/api")
app.include_router(accounts_router, prefix="/api")
app.include_router(sites_router, prefix="/api")
app.include_router(scan_session_router, prefix="/api")
app.include_router(mineral_zone_router, prefix="/api")
app.include_router(batch_router, prefix="/api")
app.include_router(custody_event_router, prefix="/api")
app.include_router(safety_router, prefix="/api")
app.include_router(safety_rules_router, prefix="/api")
app.include_router(transport_router, prefix="/api")
app.include_router(vehicle_router, prefix="/api")
app.include_router(driver_router, prefix="/api")
app.include_router(compliance_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(audit_router, prefix="/api")
app.include_router(devices_router, prefix="/api")
app.include_router(ingest_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(readings_router, prefix="/api")
