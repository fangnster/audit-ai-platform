from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Optional

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


def sync_database_url(database_url: Optional[str] = None) -> str:
    """Convert the async PostgreSQL URL into a psycopg2-safe sync URL."""
    url = database_url or settings.DATABASE_URL
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    parsed = urlsplit(url)
    if not parsed.scheme.startswith("postgresql"):
        return url

    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    has_sslmode = any(key.lower() == "sslmode" for key, _ in query_items)
    added_sslmode = False
    normalized_query: list[tuple[str, str]] = []
    for key, value in query_items:
        lowered_key = key.lower()
        if lowered_key == "ssl":
            lowered_value = value.lower()
            ssl_enabled = lowered_value not in {"0", "false", "disable", "disabled", "none", "no"}
            if ssl_enabled and not has_sslmode and not added_sslmode:
                normalized_query.append(("sslmode", "require"))
                added_sslmode = True
            continue
        normalized_query.append((key, value))

    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urlencode(normalized_query),
        parsed.fragment,
    ))


def async_database_url(database_url: Optional[str] = None) -> str:
    """Convert common PostgreSQL URLs into an asyncpg-safe async URL."""
    url = database_url or settings.DATABASE_URL
    if url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    parsed = urlsplit(url)
    if not parsed.scheme.startswith("postgresql"):
        return url

    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    has_ssl = any(key.lower() == "ssl" for key, _ in query_items)
    added_ssl = False
    normalized_query: list[tuple[str, str]] = []
    for key, value in query_items:
        lowered_key = key.lower()
        if lowered_key == "sslmode":
            if not has_ssl and not added_ssl:
                normalized_query.append(("ssl", value))
                added_ssl = True
            continue
        normalized_query.append((key, value))

    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urlencode(normalized_query),
        parsed.fragment,
    ))


engine = create_async_engine(async_database_url(), echo=settings.SQL_ECHO, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
