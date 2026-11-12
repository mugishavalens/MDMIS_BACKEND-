import time
from datetime import timezone

from sqlalchemy import event, exc
from sqlalchemy.dialects.sqlite import DATETIME as SQLITE_DATETIME
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


# Connections idle longer than this get pinged on checkout; hotter ones are
# handed out as-is.
_PING_IF_IDLE_SECONDS = 60

_url, _connect_args = settings.sqlalchemy_url_and_connect_args
engine = create_async_engine(
    _url,
    echo=False,
    connect_args=_connect_args,
    # Neon's pooled endpoint closes idle backend connections server-side;
    # without a liveness check, SQLAlchemy can hand out a connection Neon
    # already dropped, raising "connection is closed" (asyncpg
    # InterfaceError). recycle proactively retires connections before
    # Neon's own idle timeout gets to them.
    #
    # pool_pre_ping is deliberately OFF: it pings on EVERY checkout, which
    # measured ~900ms extra per request against Neon us-east-2 from Kigali.
    # _ping_if_idle below does the same check only for connections that
    # have sat idle long enough to plausibly have been dropped.
    pool_pre_ping=False,
    pool_recycle=300,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class _UTCSQLiteDateTime(SQLITE_DATETIME):
    """SQLite has no time-zone type: DateTime(timezone=True) columns come
    back naive there, while Postgres returns them aware. Code comparing them
    with datetime.now(timezone.utc) then crashes ("can't subtract
    offset-naive and offset-aware datetimes") on the local SQLite fallback
    only. Every datetime column here is timezone=True and stored as UTC, so
    on SQLite: write aware values converted to UTC, read values back as UTC."""

    def bind_processor(self, dialect):
        process = super().bind_processor(dialect)

        def bind(value):
            if value is not None and value.tzinfo is not None:
                value = value.astimezone(timezone.utc).replace(tzinfo=None)
            return process(value) if process else value
        return bind

    def result_processor(self, dialect, coltype):
        process = super().result_processor(dialect, coltype)

        def result(value):
            value = process(value) if process else value
            if value is not None and value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value
        return result


if engine.dialect.name == "sqlite":
    from sqlalchemy import types as sqltypes

    engine.sync_engine.dialect.colspecs = {**engine.sync_engine.dialect.colspecs, sqltypes.DateTime: _UTCSQLiteDateTime}


@event.listens_for(engine.sync_engine, "connect")
@event.listens_for(engine.sync_engine, "checkin")
def _mark_last_used(dbapi_connection, connection_record):
    connection_record.info["last_used"] = time.monotonic()


@event.listens_for(engine.sync_engine, "checkout")
def _ping_if_idle(dbapi_connection, connection_record, connection_proxy):
    idle = time.monotonic() - connection_record.info.get("last_used", 0)
    if idle < _PING_IF_IDLE_SECONDS:
        return
    try:
        engine.dialect.do_ping(dbapi_connection)
    except Exception as e:
        # The pool discards this connection and retries checkout with a
        # fresh one — same recovery pool_pre_ping gives.
        raise exc.DisconnectionError() from e


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
