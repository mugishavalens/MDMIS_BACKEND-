from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    secret_key: str = "dev-insecure-secret-key-change-me"
    debug: bool = True
    database_url: str = "sqlite+aiosqlite:///./db.sqlite3"
    cors_allowed_origins: str = "http://localhost:3000"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    # Frontend origin used to build invite-acceptance links in emails.
    frontend_url: str = "http://localhost:3000"

    # SendGrid — leave sendgrid_api_key empty in dev; send_email() then just
    # logs the email to the console instead of calling the SendGrid API.
    sendgrid_api_key: str = ""
    email_from: str = "no-reply@mdmis.rw"
    email_from_name: str = "MDMIS"

    otp_expire_minutes: int = 10
    invitation_expire_days: int = 7

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

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
