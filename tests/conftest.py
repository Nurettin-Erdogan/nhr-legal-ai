"""Keep integration tests away from the live legal corpus.

Database tests opt in through an explicitly configured, isolated test DB.
They must never discover the application/admin URL or modify schema at
pytest startup. Schema setup belongs to the test-DB setup/CI workflow.
"""

from __future__ import annotations

import os
from pathlib import Path

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
    # Pytest creates/removes basetemp itself, but does not create its parents.
    # Keep generated files out of the repository root even on a fresh checkout.
    (Path(__file__).resolve().parents[1] / '.local' / 'tmp').mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
def no_implicit_fast_lookup(monkeypatch):
    # Pipeline unit tests must never discover the live application URL. Fast
    # lookup tests inject their own loader or override this pipeline boundary.
    monkeypatch.setattr('api.ai.pipeline.try_fast_statute', lambda **kwargs: [])


class _RecordingExecutor:
    """Arka plan indekslemeyi çalıştırmaz, yalnız istenen işleri kaydeder."""

    def __init__(self) -> None:
        self.submitted: list[tuple] = []

    def submit(self, function, *args, **kwargs) -> None:
        self.submitted.append((function.__name__, args, kwargs))


@pytest.fixture(autouse=True)
def scheduled_indexing(monkeypatch):
    # Yükleme uç noktaları belgeyi arka planda indeksler; testler bunu asla gerçek veritabanına
    # göndermemeli. Zamanlamayı doğrulamak isteyen test bu fixture'ı adıyla ister.
    recorder = _RecordingExecutor()
    monkeypatch.setattr("api.document_indexing._executor", recorder)
    # Kayıtçı iş bitirmediği için "işleniyor" işaretleri kalkmaz; testler birbirinin belgesini engellemesin.
    monkeypatch.setattr("api.document_indexing._inflight", set())
    return recorder.submitted


@pytest.fixture(autouse=True)
def session_revocation_disabled_by_default(request, monkeypatch):
    """Gerçek jetonla çağrılan uç nokta testleri veritabanına gitmesin.

    Oturum iptali (`users.sessions_valid_after`) tests/test_session_revocation.py içinde, kendi sahte
    bağlantısıyla ve `real_sessions` işaretiyle gerçek koduyla sınanır.
    """
    from api.auth import routes

    routes._session_cache.clear()
    if request.node.get_closest_marker("real_sessions") is None:
        monkeypatch.setattr(routes, "_session_state", lambda user_id: (0, True))
    yield
    routes._session_cache.clear()


@pytest.fixture(autouse=True)
def closed_seed_tier_breaker():
    # Sigorta süreç belleğindedir: zaman aşımı deneyen bir test onu açık bırakırsa sonraki testlerin arama sırası değişir.
    from api.ai.seed_tier import seed_tier

    seed_tier.reset()
    yield
    seed_tier.reset()


@pytest.fixture(autouse=True)
def no_implicit_uyap_record(request, monkeypatch):
    # Dava sohbeti UYAP dosya bilgisi belgesini veritabanından okur; sahte bağlantıyla çalışan pipeline testleri buna
    # girmemeli. Gerçek davranış tests/test_uyap_record_document.py içinde, test veritabanıyla sınanır.
    if request.module.__name__.rsplit(".", 1)[-1] != "test_uyap_record_document":
        monkeypatch.setattr("api.ai.pipeline.record_contexts", lambda *args, **kwargs: [])
