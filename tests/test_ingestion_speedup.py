from __future__ import annotations

from datetime import date

from ingestion.chunk_store import replace_chunks
from ingestion.mevzuat.official_verify import stored_law_verification
from worker.models import SyncRequest


class _Cursor:
    def __init__(self) -> None:
        self.deleted = []
        self.inserted = []

    def execute(self, sql, params=None):
        if sql.strip().startswith("DELETE"):
            self.deleted.append(params)

    def executemany(self, sql, rows):
        self.inserted.extend(list(rows))


def test_replace_chunks_deletes_then_inserts_in_one_batch():
    cursor = _Cursor()
    rows = [
        ("sid", 0, "a", 0, 1, "h0", {"source": "yargitay"}),
        ("sid", 1, "b", 1, 2, "h1", {"source": "yargitay"}),
    ]
    assert replace_chunks(cursor, "sid", rows) == 2
    assert cursor.deleted == [("sid",)]
    assert cursor.inserted == rows


def test_replace_chunks_empty_only_deletes():
    cursor = _Cursor()
    assert replace_chunks(cursor, "sid", ()) == 0
    assert cursor.deleted == [("sid",)]
    assert cursor.inserted == []


def test_worker_page_size_and_delay_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.delenv("AYM_PAGE_SIZE", raising=False)
    monkeypatch.delenv("KDK_PAGE_SIZE", raising=False)
    monkeypatch.delenv("MEVZUAT_DISCOVERY_PAGE_SIZE", raising=False)
    monkeypatch.delenv("YARGITAY_DELAY_SECONDS", raising=False)
    monkeypatch.delenv("DANISTAY_DELAY_SECONDS", raising=False)
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    settings = get_worker_settings()
    assert settings.yargitay_delay_seconds == 1.5
    assert settings.danistay_delay_seconds == 2.0
    assert settings.aym_delay_seconds == 1.0
    assert settings.kdk_delay_seconds == 1.0
    assert settings.aym_page_size == 100
    assert settings.kdk_page_size == 100
    assert settings.mevzuat_discovery_page_size == 20
    get_worker_settings.cache_clear()


def test_mevzuat_discovery_passes_configured_page_size(monkeypatch, tmp_path):
    from ingestion.mevzuat.portal import SearchPage
    from worker.adapters.mevzuat import MevzuatSourceAdapter
    from worker.config import get_worker_settings

    class Client:
        def __init__(self):
            self.page_sizes = []

        def search_page(self, **kwargs):
            self.page_sizes.append(kwargs.get("page_size"))
            return SearchPage(documents=(), total=0, start=0)

        def fetch_article_tree(self, _mevzuat_id):
            raise AssertionError("boş katalogda madde ağacı istenmemeli")

        def fetch_article_html(self, _madde_id):
            raise AssertionError("boş katalogda madde HTML istenmemeli")

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("MEVZUAT_DELAY_SECONDS", "0")
    monkeypatch.setenv("MEVZUAT_DISCOVERY_PAGE_SIZE", "20")
    monkeypatch.setenv("MEVZUAT_DISCOVERY_TYPES", "KANUN")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()
    client = Client()
    adapter = MevzuatSourceAdapter(
        client=client, verify_gazette=False, verify_mbs=False
    )
    list(
        adapter.sync(
            SyncRequest(source="mevzuat", max_records=1, resume=False),
            cursor={},
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert client.page_sizes == [20]
    get_worker_settings.cache_clear()


def test_mevzuat_discovery_page_size_clamps_to_portal_max(monkeypatch, tmp_path):
    from ingestion.mevzuat.portal import SearchPage
    from worker.adapters.mevzuat import MevzuatSourceAdapter
    from worker.config import get_worker_settings

    class Client:
        def __init__(self):
            self.page_sizes = []

        def search_page(self, **kwargs):
            self.page_sizes.append(kwargs.get("page_size"))
            return SearchPage(documents=(), total=0, start=0)

        def fetch_article_tree(self, _mevzuat_id):
            raise AssertionError("boş katalogda madde ağacı istenmemeli")

        def fetch_article_html(self, _madde_id):
            raise AssertionError("boş katalogda madde HTML istenmemeli")

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("MEVZUAT_DELAY_SECONDS", "0")
    monkeypatch.setenv("MEVZUAT_DISCOVERY_PAGE_SIZE", "100")
    monkeypatch.setenv("MEVZUAT_DISCOVERY_TYPES", "KANUN")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()
    client = Client()
    adapter = MevzuatSourceAdapter(
        client=client, verify_gazette=False, verify_mbs=False
    )
    list(
        adapter.sync(
            SyncRequest(source="mevzuat", max_records=1, resume=False),
            cursor={},
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert client.page_sizes == [20]
    get_worker_settings.cache_clear()


def test_mevzuat_official_verification_is_cached_per_law(monkeypatch, tmp_path):
    from ingestion.mevzuat.portal import SearchPage
    from ingestion.mevzuat_bilgi_sistemi.portal import MbsVerification
    from ingestion.resmi_gazete.portal import GazetteVerification
    from worker.adapters.mevzuat import MevzuatSourceAdapter
    from worker.config import get_worker_settings

    class Client:
        def search_page(self, **_kwargs):
            return SearchPage(
                documents=(
                    {
                        "mevzuatId": "1",
                        "mevzuatNo": "4857",
                        "mevzuatAdi": "İş Kanunu",
                        "mevzuatTur": {"name": "KANUN"},
                        "resmiGazeteTarihi": None,
                        "resmiGazeteSayisi": "39999",
                    },
                ),
                total=1,
                start=0,
            )

        def fetch_article_tree(self, _mevzuat_id):
            return {
                "children": [
                    {"maddeNo": "1", "maddeId": "a1", "title": "Amaç"},
                    {"maddeNo": "2", "maddeId": "a2", "title": "Kapsam"},
                    {"maddeNo": "3", "maddeId": "a3", "title": "Tanımlar"},
                ]
            }

        def fetch_article_html(self, madde_id):
            return f"<p>Geçerli sentetik mevzuat metni {madde_id}.</p>"

    class Gazette:
        def __init__(self):
            self.calls = 0

        def verify_legislation(self, **_kwargs):
            self.calls += 1
            return GazetteVerification(
                verified=True,
                archive_url="https://www.resmigazete.gov.tr/eskiler/2099/01/20990102.htm",
                requested_date=None,
                observed_date="2099-01-02",
                requested_issue_no="39999",
                observed_issue_no="39999",
                law_no="4857",
                law_no_present=True,
                law_name_present=True,
                verified_at="2099-01-02T00:00:00+00:00",
                detail="cache test",
            )

    class Mbs:
        def __init__(self):
            self.calls = 0

        def verify_legislation(self, **_kwargs):
            self.calls += 1
            return MbsVerification(
                verified=True,
                law_no="4857",
                law_name="İş Kanunu",
                detail_url="https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=4857",
                pdf_url="https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4857.pdf",
                doc_url="https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4857.doc",
                requested_gazette_date=None,
                observed_gazette_date="2003-06-10",
                requested_gazette_no="39999",
                observed_gazette_no="39999",
                title_matches=True,
                verified_at="2099-01-02T00:00:00+00:00",
                detail="cache test",
            )

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("MEVZUAT_DELAY_SECONDS", "0")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()
    gazette = Gazette()
    mbs = Mbs()
    adapter = MevzuatSourceAdapter(
        client=Client(),
        gazette_client=gazette,  # type: ignore[arg-type]
        mbs_client=mbs,  # type: ignore[arg-type]
    )
    cursor = {}
    for _ in range(2):
        list(
            adapter.sync(
                SyncRequest(source="mevzuat", law_no="4857", max_records=1, resume=True),
                cursor=cursor,
                connection=None,
                dry_run=True,
                should_stop=lambda: False,
            )
        )
        cursor = adapter.last_cursor
    assert gazette.calls == 1
    assert mbs.calls == 1
    get_worker_settings.cache_clear()


class _StoredVerifyConnection:
    def execute(self, sql, params=None):
        assert "law_no" in sql or "%s" in sql

        class _Result:
            def fetchone(self_inner):
                return {
                    "metadata": {
                        "verified_against_gazette": True,
                        "verified_against_mbs": True,
                        "official_gazette_verification": {"verified": True, "law_no": "4857"},
                        "mbs_verification": {"verified": True, "law_no": "4857"},
                    }
                }

        return _Result()


def test_stored_law_verification_skips_http_when_both_flags_true():
    gazette, mbs, pending = stored_law_verification(_StoredVerifyConnection(), "4857")
    assert pending == 0
    assert gazette["verified"] is True
    assert mbs["verified"] is True


def test_mevzuat_verify_adapter_processes_pending_laws(monkeypatch):
    from worker.adapters.mevzuat_verify import MevzuatVerifyAdapter
    from worker.config import get_worker_settings

    class Gazette:
        def verify_legislation(self, **_kwargs):
            from ingestion.resmi_gazete.portal import GazetteVerification

            return GazetteVerification(
                verified=True,
                archive_url="https://www.resmigazete.gov.tr/eskiler/2099/01/20990102.htm",
                requested_date="2099-01-02",
                observed_date="2099-01-02",
                requested_issue_no="1",
                observed_issue_no="1",
                law_no="4857",
                law_no_present=True,
                law_name_present=True,
                verified_at="2099-01-02T00:00:00+00:00",
                detail="ok",
            )

    class Mbs:
        def verify_legislation(self, **_kwargs):
            from ingestion.mevzuat_bilgi_sistemi.portal import MbsVerification

            return MbsVerification(
                verified=True,
                law_no="4857",
                law_name="İş Kanunu",
                detail_url="https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=4857",
                pdf_url="https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4857.pdf",
                doc_url="https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4857.doc",
                requested_gazette_date="2099-01-02",
                observed_gazette_date="2099-01-02",
                requested_gazette_no="1",
                observed_gazette_no="1",
                title_matches=True,
                verified_at="2099-01-02T00:00:00+00:00",
                detail="ok",
            )

    class Connection:
        def __init__(self):
            self.updated = 0

        def execute(self, sql, params=None):
            class _Result:
                def fetchall(self_inner):
                    if "DISTINCT ON" in sql:
                        return [
                            {
                                "legislation_type": "KANUN",
                                "law_no": "4857",
                                "law_name": "İş Kanunu",
                                "official_gazette_date": date(2099, 1, 2),
                                "official_gazette_no": "1",
                                "metadata": {},
                            }
                        ]
                    return []

            if sql.strip().startswith("UPDATE"):
                self.updated += 1
            return _Result()

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    get_worker_settings.cache_clear()
    connection = Connection()
    adapter = MevzuatVerifyAdapter(gazette_client=Gazette(), mbs_client=Mbs())  # type: ignore[arg-type]
    events = list(
        adapter.sync(
            SyncRequest(source="mevzuat_verify", max_records=3, resume=False),
            cursor={},
            connection=connection,
            dry_run=False,
            should_stop=lambda: False,
        )
    )
    assert events[0][0] == "updated"
    assert connection.updated == 1
    get_worker_settings.cache_clear()
