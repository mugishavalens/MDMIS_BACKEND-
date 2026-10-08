import time

from sqlalchemy import event, exc
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
