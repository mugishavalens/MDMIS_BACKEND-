import logging
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


_DEFAULT_SECRET_KEY = "dev-insecure-secret-key-change-me"
_DEFAULT_ML_SERVICE_KEY = "dev-insecure-ml-service-key-change-me"


def _is_placeholder(value: str) -> bool:
    """The code defaults and .env.example placeholders all contain change-me."""
    return "change-me" in value


class Settings(BaseSettings):
    secret_key: str = _DEFAULT_SECRET_KEY
    debug: bool = True
    database_url: str = "sqlite+aiosqlite:///./db.sqlite3"
    cors_allowed_origins: str = "http://localhost:3000"
    # Optional regex for origins that can't be listed up front, e.g. Vercel
    # preview deployments (a new URL per deploy). Empty = exact list only.
    cors_allowed_origin_regex: str = ""
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    # Frontend origin used to build invite-acceptance links in emails.
    frontend_url: str = "http://localhost:3000"

    # Brevo — leave brevo_api_key empty in dev; send_email() then just
    # logs the email to the console instead of calling the Brevo API.
    brevo_api_key: str = ""
    email_from: str = "no-reply@mdmis.rw"
    email_from_name: str = "MDMIS"

    otp_expire_minutes: int = 10

    # Sensor file storage (REQ-ING-007). "local" writes under storage_dir —
    # fine for development, but Render's disk is wiped on every deploy, so
    # production should use "s3" (AWS S3 or any S3-compatible store such as
    # Cloudflare R2, via s3_endpoint_url).
    storage_backend: str = "local"
    storage_dir: str = "storage"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = "auto"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    # SRS allows 10 GB via resumable multipart; single-request uploads are
    # capped lower until resumable upload is implemented.
    max_upload_mb: int = 500
    invitation_expire_days: int = 7

    # mdmis-ml-service (separate repo/process). ml_service_api_key must
    # match that service's own SERVICE_API_KEY — it's the shared secret
    # both directions of backend<->ML-service traffic use.
    ml_service_url: str = "http://localhost:8100"
    ml_service_api_key: str = _DEFAULT_ML_SERVICE_KEY

    # Organisations whose lab_confirmed zones may train the shared ML model
    # (comma-separated UUIDs). Empty = none: any organisation can sign up
    # and confirm its own zones, so training data is opt-in per org.
    training_org_ids: str = ""

    # /docs, /redoc and /openapi.json. Unset = on for local SQLite
    # development, off in production.
    api_docs_enabled: bool | None = None

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    @property
    def is_production(self) -> bool:
        """Anything but the local SQLite fallback is treated as a real
        deployment (Neon on Render)."""
        return not self.database_url.startswith("sqlite")

    @property
    def ml_service_key_usable(self) -> bool:
        return not (self.is_production and _is_placeholder(self.ml_service_api_key))

    @property
    def docs_enabled(self) -> bool:
        return self.api_docs_enabled if self.api_docs_enabled is not None else not self.is_production

    @property
    def training_org_id_list(self) -> list[uuid.UUID]:
        return [uuid.UUID(v.strip()) for v in self.training_org_ids.split(",") if v.strip()]

    def check_production_secrets(self) -> None:
        """Refuse to start a deployment that signs tokens with the published
        default secret: anyone could forge a login for any account."""
        if not self.is_production:
            return
        if _is_placeholder(self.secret_key):
            raise RuntimeError(
                "SECRET_KEY is a published placeholder. Set it to a long random value, e.g. "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\"."
            )
        if len(self.secret_key) < 32:
            logging.getLogger("mdmis").warning("SECRET_KEY is shorter than 32 characters; use a longer random value.")
        if _is_placeholder(self.ml_service_api_key):
            logging.getLogger("mdmis").warning(
                "ML_SERVICE_API_KEY is a published placeholder: service-key endpoints are disabled until it's set."
            )

    @property
    def cors_origins_list(self) -> list[str]:
        # Browsers send Origin without a trailing slash; strip any pasted one
        # so "https://app.example.com/" still matches.
        return [o.strip().rstrip("/") for o in self.cors_allowed_origins.split(",") if o.strip().rstrip("/")]

    @property
    def sqlalchemy_url_and_connect_args(self) -> tuple[str, dict]:
        """Normalize a plain postgresql:// URL (e.g. copied from Neon) into
        the asyncpg driver URL SQLAlchemy needs. Neon's copy-paste connection
        string carries sslmode and channel_binding query params that libpq
        understands but asyncpg.connect() doesn't accept as kwargs — both are
        stripped and translated into (or covered by) the ssl connect arg."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]

        if not url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
            return url, {}

        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        sslmode = query.pop("sslmode", None)
        query.pop("channel_binding", None)
        connect_args: dict = {}
        if sslmode in ("require", "verify-full", "verify-ca"):
            connect_args["ssl"] = True

        parts = parts._replace(scheme="postgresql+asyncpg", query=urlencode(query))
        return urlunsplit(parts), connect_args


settings = Settings()
