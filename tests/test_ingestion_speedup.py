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
    assert settings.yargitay_delay_seconds == 0.25
    assert settings.danistay_delay_seconds == 0.35
    assert settings.aym_delay_seconds == 0.25
    assert settings.kdk_delay_seconds == 0.25
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


def test_pending_laws_rotate_by_last_attempt():
    from ingestion.mevzuat.official_verify import _PENDING_LAWS_SQL

    assert "verify_last_attempt_at" in _PENDING_LAWS_SQL
    assert "DISTINCT ON" in _PENDING_LAWS_SQL
    assert "INTERVAL '20 minutes'" in _PENDING_LAWS_SQL
    assert "verified_against_gazette" in _PENDING_LAWS_SQL
    assert "<> (pending.metadata->>'verified_against_mbs' = 'true')" in _PENDING_LAWS_SQL


def test_verify_law_uses_success_cache():
    from ingestion.mevzuat.official_verify import (
        clear_verification_cache,
        verify_law_against_portals,
    )
    from ingestion.resmi_gazete.portal import GazetteVerification
    from ingestion.mevzuat_bilgi_sistemi.portal import MbsVerification

    clear_verification_cache()
    gazette_calls = []
    mbs_calls = []

    class Gazette:
        def verify_legislation(self, **kwargs):
            gazette_calls.append(kwargs)
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
        def verify_legislation(self, **kwargs):
            mbs_calls.append(kwargs)
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

    law = {
        "legislation_type": "KANUN",
        "law_no": "4857",
        "law_name": "İş Kanunu",
        "official_gazette_date": date(2099, 1, 2),
        "official_gazette_no": "1",
        "metadata": {},
    }
    first = verify_law_against_portals(
        law, gazette_client=Gazette(), mbs_client=Mbs()
    )
    second = verify_law_against_portals(
        {**law, "metadata": {}}, gazette_client=Gazette(), mbs_client=Mbs()
    )
    assert first[0]["verified_against_gazette"] is True
    assert second[0]["verified_against_mbs"] is True
    assert len(gazette_calls) == 1
    assert len(mbs_calls) == 1
    clear_verification_cache()


def test_iter_pending_aborts_on_mbs_non_json_without_stamping():
    from ingestion.mevzuat.official_verify import (
        clear_verification_cache,
        iter_pending_verifications,
    )
    from ingestion.mevzuat_bilgi_sistemi.portal import MbsError
    from ingestion.resmi_gazete.portal import GazetteVerification

    clear_verification_cache()

    class Gazette:
        def verify_legislation(self, **_kwargs):
            return GazetteVerification(
                verified=True,
                archive_url="https://www.resmigazete.gov.tr/eskiler/2099/01/20990102.htm",
                requested_date="2099-01-02",
                observed_date="2099-01-02",
                requested_issue_no="1",
                observed_issue_no="1",
                law_no="1",
                law_no_present=True,
                law_name_present=True,
                verified_at="2099-01-02T00:00:00+00:00",
                detail="ok",
            )

    class Mbs:
        def verify_legislation(self, **_kwargs):
            raise MbsError("MBS arama ucu JSON olmayan yanıt döndürdü")

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
                                "law_no": law_no,
                                "law_name": "Kanun",
                                "official_gazette_date": date(2099, 1, 2),
                                "official_gazette_no": "1",
                                "metadata": {"verified_against_gazette": True},
                            }
                            for law_no in ("1111", "2222")
                        ]
                    return []

            if sql.strip().startswith("UPDATE"):
                self.updated += 1
            return _Result()

    events = list(
        iter_pending_verifications(
            Connection(),
            limit=50,
            gazette_client=Gazette(),
            mbs_client=Mbs(),
            dry_run=False,
        )
    )
    assert len(events) == 1
    assert events[0]["cooldown"] == "mbs"
    assert events[0]["ready"] is False
    connection = Connection()
    list(
        iter_pending_verifications(
            connection,
            limit=50,
            gazette_client=Gazette(),
            mbs_client=Mbs(),
        )
    )
    assert connection.updated == 0
    clear_verification_cache()


def test_iter_pending_continues_after_mbs_content_miss():
    from ingestion.mevzuat.official_verify import (
        clear_verification_cache,
        iter_pending_verifications,
    )
    from ingestion.mevzuat_bilgi_sistemi.portal import MbsError
    from ingestion.resmi_gazete.portal import GazetteVerification

    clear_verification_cache()
    mbs_calls = []

    class Gazette:
        def verify_legislation(self, **_kwargs):
            return GazetteVerification(
                verified=True,
                archive_url="https://www.resmigazete.gov.tr/eskiler/2099/01/20990102.htm",
                requested_date="2099-01-02",
                observed_date="2099-01-02",
                requested_issue_no="1",
                observed_issue_no="1",
                law_no="1",
                law_no_present=True,
                law_name_present=True,
                verified_at="2099-01-02T00:00:00+00:00",
                detail="ok",
            )

    class Mbs:
        def verify_legislation(self, **kwargs):
            mbs_calls.append(kwargs["law_no"])
            raise MbsError("MBS detay sayfasında tekil resmî PDF/DOC bağlantısı bulunamadı")

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
                                "law_no": law_no,
                                "law_name": "Kanun",
                                "official_gazette_date": date(2099, 1, 2),
                                "official_gazette_no": "1",
                                "metadata": {"verified_against_gazette": True},
                            }
                            for law_no in ("1111", "2222")
                        ]
                    return []

            if sql.strip().startswith("UPDATE"):
                self.updated += 1
            return _Result()

    connection = Connection()
    events = list(
        iter_pending_verifications(
            connection,
            limit=50,
            gazette_client=Gazette(),
            mbs_client=Mbs(),
        )
    )
    assert [item["law_no"] for item in events] == ["1111", "2222"]
    assert all(item["ready"] is False for item in events)
    assert all("cooldown" not in item for item in events)
    assert mbs_calls == ["1111", "2222"]
    assert connection.updated == 2
    clear_verification_cache()


def test_mevzuat_verify_skips_cooling_source_and_keeps_window_open(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from worker.adapters.mevzuat_verify import MevzuatVerifyAdapter
    from worker.config import get_worker_settings

    class Gazette:
        def verify_legislation(self, **_kwargs):
            raise AssertionError("soğuyan MBS beklerken gaz_only MBS'e gidilmemeli")

    class Mbs:
        def verify_legislation(self, **_kwargs):
            raise AssertionError("MBS soğumadayken çağrılmamalı")

    class Connection:
        def execute(self, sql, params=None):
            class _Result:
                def fetchall(self_inner):
                    if "DISTINCT ON" in sql:
                        return [
                            {
                                "legislation_type": "KANUN",
                                "law_no": "5302",
                                "law_name": "İl Özel İdaresi Kanunu",
                                "official_gazette_date": date(2005, 3, 4),
                                "official_gazette_no": "25745",
                                "metadata": {"verified_against_gazette": True},
                            }
                        ]
                    return []

            return _Result()

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    get_worker_settings.cache_clear()
    until = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    adapter = MevzuatVerifyAdapter(gazette_client=Gazette(), mbs_client=Mbs())  # type: ignore[arg-type]
    events = list(
        adapter.sync(
            SyncRequest(source="mevzuat_verify", max_records=10, resume=True),
            cursor={"mbs_retry_at": until},
            connection=Connection(),
            dry_run=False,
            should_stop=lambda: False,
        )
    )
    assert events == []
    assert adapter.last_cursor.get("complete") is False
    assert adapter.last_cursor.get("mbs_retry_at") == until
    get_worker_settings.cache_clear()


def test_rate_limit_interval_is_two_minutes(monkeypatch):
    from datetime import timedelta

    from worker.config import get_worker_settings
    from worker.jobs import _interval_for

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.delenv("INGESTION_RATE_LIMIT_RETRY_MINUTES", raising=False)
    get_worker_settings.cache_clear()
    assert _interval_for(
        "mevzuat",
        cursor={"complete": False},
        status="failed",
        error="Bedesten HTTP 429; kaynak hız sınırı",
    ) == timedelta(minutes=2)
    assert _interval_for(
        "mevzuat_verify",
        cursor={"complete": False},
        status="failed",
        error="doğrulama kaynakları soğumada until=2099-01-01T00:00:00+00:00",
    ) == timedelta(minutes=2)
    get_worker_settings.cache_clear()

