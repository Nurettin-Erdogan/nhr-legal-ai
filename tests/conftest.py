from __future__ import annotations

import os

from urllib.parse import quote

from dotenv import dotenv_values


def _owner_url(values: dict[str, str | None]) -> str | None:
    required = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    if not all(values.get(name) for name in required):
        return None
    user = quote(values["POSTGRES_USER"], safe="")
    password = quote(values["POSTGRES_PASSWORD"], safe="")
    database = quote(values["POSTGRES_DB"], safe="")
    port = values.get("POSTGRES_PORT") or "5433"
    return f"postgresql://{user}:{password}@localhost:{port}/{database}"


def pytest_configure() -> None:
    """Point database tests at the local stack when one is reachable.

    Keeps `NHR_TEST_DATABASE_URL` as the explicit override while letting the
    suite exercise real SQL during local development. The probe means a stopped
    Docker daemon still skips these tests instead of failing them.
    """
    url = os.getenv("NHR_TEST_DATABASE_URL")
    if not url:
        values = dotenv_values(".env")
        url = values.get("DATABASE_ADMIN_URL") or _owner_url(values)
        if not url:
            return
        try:
            import psycopg

            with psycopg.connect(url, connect_timeout=2):
                pass
        except Exception:
            return
        os.environ["NHR_TEST_DATABASE_URL"] = url

    _align_legal_schema(url)


def _align_legal_schema(url: str) -> None:
    """006 sonrası DEFAULT/unique index kalıntılarını test DB'sinde tamamlar."""
    try:
        import psycopg

        with psycopg.connect(url, autocommit=True, connect_timeout=2) as connection:
            connection.execute("DROP INDEX IF EXISTS uq_court_decision_natural")
            connection.execute(
                """
                ALTER TABLE legal_sources
                  ALTER COLUMN canonical_source_name SET DEFAULT 'Unspecified official source',
                  ALTER COLUMN ingestion_method SET DEFAULT 'legacy_import',
                  ALTER COLUMN fetched_at SET DEFAULT NOW(),
                  ALTER COLUMN last_verified_at SET DEFAULT NOW(),
                  ALTER COLUMN source_version SET DEFAULT '1'
                """
            )
    except Exception:
        return
