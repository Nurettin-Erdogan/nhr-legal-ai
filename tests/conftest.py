"""Keep integration tests away from the live legal corpus.

Database tests opt in through an explicitly configured, isolated test DB.
They must never discover the application/admin URL or modify schema at
pytest startup. Schema setup belongs to the test-DB setup/CI workflow.
"""

from __future__ import annotations

import os

import pytest
from psycopg.conninfo import conninfo_to_dict


def validate_test_database_url(url: str) -> None:
    try:
        database = conninfo_to_dict(url).get("dbname", "")
    except Exception as exc:
        raise pytest.UsageError("NHR_TEST_DATABASE_URL geçerli PostgreSQL bağlantısı olmalıdır") from exc
    if not database.endswith("_test"):
        raise pytest.UsageError(
            "NHR_TEST_DATABASE_URL yalnız ayrı bir *_test PostgreSQL veritabanını "
            "göstermelidir; canlı nhr_legal_ai veritabanında test çalıştırılmaz."
        )


def pytest_configure() -> None:
    url = os.getenv("NHR_TEST_DATABASE_URL")
    if url:
        validate_test_database_url(url)


@pytest.fixture(autouse=True)
def no_implicit_fast_lookup(monkeypatch):
    # Pipeline unit tests must never discover the live application URL. Fast
    # lookup tests inject their own loader or override this pipeline boundary.
    monkeypatch.setattr('api.ai.pipeline.try_fast_statute', lambda **kwargs: [])
