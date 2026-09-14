from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


_url, _connect_args = settings.sqlalchemy_url_and_connect_args
engine = create_async_engine(
    _url,
    echo=False,
    connect_args=_connect_args,
    # Neon's pooled endpoint closes idle backend connections server-side;
    # without these, SQLAlchemy can hand out a connection Neon already
    # dropped, raising "connection is closed" (asyncpg InterfaceError).
    # pre_ping verifies (and silently replaces) a stale connection before
    # each use; recycle proactively retires connections before Neon's own
    # idle timeout gets to them.
    pool_pre_ping=True,
    pool_recycle=300,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
