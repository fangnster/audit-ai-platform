from urllib.parse import parse_qs, urlsplit

from app.database import async_database_url, sync_database_url


def test_sync_database_url_converts_asyncpg_and_ssl_param():
    url = sync_database_url("postgresql+asyncpg://user:pass@example.com:5432/db?ssl=true")

    parsed = urlsplit(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "postgresql+psycopg2"
    assert query == {"sslmode": ["require"]}


def test_sync_database_url_preserves_existing_sslmode():
    url = sync_database_url(
        "postgresql+asyncpg://user:pass@example.com:5432/db?ssl=true&sslmode=verify-full"
    )

    parsed = urlsplit(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "postgresql+psycopg2"
    assert query == {"sslmode": ["verify-full"]}


def test_sync_database_url_keeps_non_ssl_query_params():
    url = sync_database_url("postgresql://user:pass@example.com:5432/db?connect_timeout=10")

    parsed = urlsplit(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "postgresql+psycopg2"
    assert query == {"connect_timeout": ["10"]}


def test_async_database_url_converts_plain_postgres_urls():
    assert async_database_url("postgres://user:pass@example.com:5432/db") == (
        "postgresql+asyncpg://user:pass@example.com:5432/db"
    )
    assert async_database_url("postgresql://user:pass@example.com:5432/db") == (
        "postgresql+asyncpg://user:pass@example.com:5432/db"
    )


def test_async_database_url_converts_psycopg2_urls_for_api_side():
    url = async_database_url("postgresql+psycopg2://user:pass@example.com:5432/db?sslmode=require")

    parsed = urlsplit(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "postgresql+asyncpg"
    assert query == {"ssl": ["require"]}


def test_async_database_url_prefers_existing_ssl_param():
    url = async_database_url("postgresql://user:pass@example.com:5432/db?ssl=true&sslmode=require")

    parsed = urlsplit(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "postgresql+asyncpg"
    assert query == {"ssl": ["true"]}
