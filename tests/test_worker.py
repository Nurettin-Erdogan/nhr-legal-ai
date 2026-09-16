from __future__ import annotations

from datetime import date

import pytest

from ingestion.yargitay.models import CourtDecision
from ingestion.yargitay.parser import content_hash
from ingestion.yargitay.portal import CaptchaRequiredError, PortalDecisionRow, SearchPage
from worker.adapters import get_adapter
from worker.adapters.danistay import DanistaySourceAdapter
from worker.adapters.yargitay import YargitaySourceAdapter
from worker.locks import JobLockedError, source_job_lock
from worker.models import Checkpoint, RunCounters, SyncRequest
from worker.windows import iter_month_windows, month_window, next_month_start


def test_month_windows_cover_range_without_gaps():
    windows = iter_month_windows(date(2026, 1, 15), date(2026, 3, 10))
    assert windows[0] == (date(2026, 1, 15), date(2026, 1, 31))
    assert windows[1] == (date(2026, 2, 1), date(2026, 2, 28))
    assert windows[2] == (date(2026, 3, 1), date(2026, 3, 10))
    assert next_month_start(date(2026, 12, 1)) == date(2027, 1, 1)
    assert month_window(date(2026, 8, 20)) == (date(2026, 8, 1), date(2026, 8, 31))


def test_run_counters_classify_outcomes():
    counters = RunCounters()
    for outcome in ("created", "unchanged", "updated", "new_version", "duplicate", "quarantined", "failed"):
        counters.add(outcome)  # type: ignore[arg-type]
    assert counters.records_seen == 7
    assert counters.records_created == 1
    assert counters.records_updated == 2
    assert counters.records_unchanged == 1
    assert counters.records_duplicate == 1
    assert counters.records_quarantined == 1
    assert counters.records_failed == 1


def test_yargitay_validate_quarantines_missing_fields():
    adapter = YargitaySourceAdapter()
    record = CourtDecision(
        court_name="Yargıtay",
        chamber="9. Hukuk Dairesi",
        docket_no="",
        decision_no="",
        decision_date=date(2026, 1, 1),
        title="x",
        raw_text="",
        external_id="yargitay:1",
        content_hash=content_hash("x"),
        source_url="https://karararama.yargitay.gov.tr/getDokuman?id=1",
    )
    missing = adapter.validate(record)
    assert "docket_no" in missing
    assert "decision_no" in missing
    assert "raw_text" in missing


def test_yargitay_resume_uses_incomplete_window_cursor():
    adapter = YargitaySourceAdapter()
    request = SyncRequest(source="yargitay", resume=True)
    window = adapter.resolve_window(
        request,
        {
            "window_from": "2026-02-01",
            "window_to": "2026-02-28",
            "window_complete": False,
            "page": 4,
        },
    )
    assert window == (date(2026, 2, 1), date(2026, 2, 28))


def test_adapter_registry_exposes_active_sources():
    assert get_adapter("yargitay").source_name == "yargitay"
    assert get_adapter("danistay").active is True
    assert get_adapter("mevzuat").source_name == "mevzuat"
    assert get_adapter("aym").active is True
    assert get_adapter("resmi_gazete").active is False
    assert get_adapter("mevzuat_bilgi_sistemi").active is False
    assert get_adapter("kdk").active is True
    assert get_adapter("kdk").authority == "Kamu Denetçiliği Kurumu"


def test_checkpoint_json_round_trip_fields():
    checkpoint = Checkpoint(
        source_name="yargitay",
        last_page=3,
        last_date_from=date(2026, 1, 1),
        last_date_to=date(2026, 1, 31),
        last_external_id="yargitay:9",
        last_cursor={"page": 3},
        consecutive_failures=2,
        health_state="degraded",
    )
    payload = checkpoint.as_json()
    assert payload["last_page"] == 3
    assert payload["last_external_id"] == "yargitay:9"
    assert payload["last_cursor"]["page"] == 3


class _LockCursor:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired

    def execute(self, _sql, _params=None):
        return None

    def fetchone(self):
        return (self.acquired,)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _LockConnection:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.calls = 0

    def cursor(self):
        self.calls += 1
        # first call is try_lock, later unlock
        return _LockCursor(self.acquired)


def test_job_lock_rejects_second_source_run():
    connection = _LockConnection(acquired=False)
    with pytest.raises(JobLockedError, match="zaten çalışıyor"):
        with source_job_lock(connection, "yargitay"):
            pass


def test_job_lock_allows_when_acquired():
    connection = _LockConnection(acquired=True)
    with source_job_lock(connection, "yargitay"):
        pass
    assert connection.calls == 2


class _CaptchaClient:
    base_url = "https://karararama.yargitay.gov.tr/"

    def begin_detailed_search(self, filters):
        return None

    def search_page(self, filters):
        return SearchPage(
            rows=(
                PortalDecisionRow(
                    "1", "9. Hukuk Dairesi", "2026/1", "2026/1", "01.01.2026"
                ),
            ),
            records_total=1,
            records_filtered=1,
        )

    def fetch_document_html(self, document_id):
        raise CaptchaRequiredError("CAPTCHA")


def test_yargitay_captcha_stops_sync(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("YARGITAY_DELAY_SECONDS", "0")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    adapter = YargitaySourceAdapter(client=_CaptchaClient())
    with pytest.raises(CaptchaRequiredError):
        list(
            adapter.sync(
                SyncRequest(
                    source="yargitay",
                    date_from=date(2026, 1, 1),
                    date_to=date(2026, 1, 31),
                    max_records=1,
                    resume=False,
                ),
                cursor={},
                connection=None,
                dry_run=True,
                should_stop=lambda: False,
            )
        )


def test_malformed_schema_health_is_failed():
    class _BadClient:
        def _request(self, path):
            return b"{}"

        def begin_detailed_search(self, filters):
            raise RuntimeError("schema")

        def search_page(self, filters):
            raise RuntimeError("schema")

    health = YargitaySourceAdapter(client=_BadClient()).health_check()
    assert health.state == "failed"


class _MevzuatClientSuccessThenQuarantine:
    """İlk madde geçerli HTML, ikinci madde boş → quarantine."""

    def search_page(self, **kwargs):
        from ingestion.mevzuat.portal import SearchPage

        return SearchPage(
            documents=(
                {
                    "mevzuatId": "1",
                    "mevzuatNo": "4857",
                    "mevzuatAdi": "İş Kanunu",
                    "mevzuatTur": {"name": "KANUN"},
                },
            ),
            total=1,
            start=0,
        )

    def fetch_article_tree(self, mevzuat_id):
        return {
            "children": [
                {"maddeNo": "1", "maddeId": "a1", "title": "Amaç"},
                {"maddeNo": "2", "maddeId": "a2", "title": "Kapsam"},
                {"maddeNo": "3", "maddeId": "a3", "title": "Tanımlar"},
            ]
        }

    def fetch_article_html(self, madde_id):
        if madde_id == "a2":
            return "<p></p>"  # boş metin → validate/raw_text fail veya ValueError
        return f"<p>Madde gövdesi {madde_id} yeterli uzunlukta metin.</p>"


def test_mevzuat_checkpoint_does_not_advance_past_quarantined_article(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("MEVZUAT_DELAY_SECONDS", "0")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    from worker.adapters.mevzuat import MevzuatSourceAdapter
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()

    class _AllHtml(_MevzuatClientSuccessThenQuarantine):
        def fetch_article_html(self, madde_id):
            return f"<p>Geçerli madde metni {madde_id}.</p>"

    adapter = MevzuatSourceAdapter(
        client=_AllHtml(), verify_gazette=False, verify_mbs=False
    )
    real_validate = adapter.validate

    def validate_second_quarantine(record):
        if record.article_no == "2":
            return ["raw_text"]
        return real_validate(record)

    adapter.validate = validate_second_quarantine  # type: ignore[method-assign]
    outcomes = list(
        adapter.sync(
            SyncRequest(
                source="mevzuat",
                law_no="4857",
                max_records=10,
                resume=False,
            ),
            cursor={},
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert outcomes[0][0] == "created"
    assert outcomes[1][0] == "quarantined"
    assert adapter.last_cursor["last_article_no"] == "1"
    assert adapter.last_cursor.get("complete") is not True


def test_mevzuat_checkpoint_does_not_advance_past_failed_article(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("MEVZUAT_DELAY_SECONDS", "0")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    from worker.adapters.mevzuat import MevzuatSourceAdapter
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    adapter = MevzuatSourceAdapter(
        client=_MevzuatClientSuccessThenQuarantine(),
        verify_gazette=False,
        verify_mbs=False,
    )
    outcomes = list(
        adapter.sync(
            SyncRequest(
                source="mevzuat",
                law_no="4857",
                max_records=10,
                resume=False,
            ),
            cursor={},
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert outcomes[0][0] == "created"
    assert outcomes[1][0] == "failed"
    assert adapter.last_cursor["last_article_no"] == "1"
    assert adapter.last_cursor.get("complete") is not True


def test_mevzuat_resume_retries_after_last_successful_article(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("MEVZUAT_DELAY_SECONDS", "0")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    from worker.adapters.mevzuat import MevzuatSourceAdapter
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()

    class _AllGood(_MevzuatClientSuccessThenQuarantine):
        def fetch_article_html(self, madde_id):
            return f"<p>Geçerli madde metni {madde_id}.</p>"

    adapter = MevzuatSourceAdapter(
        client=_AllGood(), verify_gazette=False, verify_mbs=False
    )
    outcomes = list(
        adapter.sync(
            SyncRequest(
                source="mevzuat",
                law_no="4857",
                max_records=10,
                resume=True,
            ),
            cursor={"law_index": 0, "last_article_no": "1"},
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    article_nos = [payload["article_no"] for _, payload in outcomes]
    assert "1" not in article_nos
    assert article_nos[0] == "2"
    assert adapter.last_cursor["last_article_no"] == "3"


def test_mevzuat_sync_attaches_official_gazette_verification(monkeypatch, tmp_path):
    from ingestion.mevzuat.archive import LegislationArchive
    from ingestion.mevzuat_bilgi_sistemi.portal import MbsVerification
    from ingestion.resmi_gazete.portal import GazetteVerification
    from worker.adapters.mevzuat import MevzuatSourceAdapter
    from worker.config import get_worker_settings

    class _DocumentWithGazette(_MevzuatClientSuccessThenQuarantine):
        def search_page(self, **kwargs):
            page = super().search_page(**kwargs)
            document = {
                **page.documents[0],
                "resmiGazeteTarihi": None,
                "resmiGazeteSayisi": "39999",
            }
            return type(page)(documents=(document,), total=1, start=0)

        def fetch_article_html(self, madde_id):
            return f"<p>Geçerli sentetik mevzuat metni {madde_id}.</p>"

    class _GazetteVerifier:
        def verify_legislation(self, **kwargs):
            assert kwargs["issue_no"] == "39999"
            assert kwargs["law_no"] == "4857"
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
                detail="sentetik doğrulama",
            )

    class _MbsVerifier:
        def verify_legislation(self, **kwargs):
            assert kwargs["law_no"] == "4857"
            assert kwargs["issue_no"] == "39999"
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
                detail="sentetik MBS doğrulaması",
            )

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("MEVZUAT_DELAY_SECONDS", "0")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()
    adapter = MevzuatSourceAdapter(
        client=_DocumentWithGazette(),
        gazette_client=_GazetteVerifier(),  # type: ignore[arg-type]
        mbs_client=_MbsVerifier(),  # type: ignore[arg-type]
    )
    list(
        adapter.sync(
            SyncRequest(source="mevzuat", law_no="4857", max_records=1, resume=False),
            cursor={},
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )

    record = next(LegislationArchive(tmp_path / "mevzuat").iter_records())
    assert record.official_gazette_date == date(2099, 1, 2)
    assert record.metadata["verified_against_gazette"] is True
    assert record.metadata["official_gazette_url"].endswith("20990102.htm")
    assert record.metadata["verified_against_mbs"] is True
    assert record.metadata["mbs_pdf_url"].endswith("1.5.4857.pdf")


def test_last_successful_sync_at_only_on_success(monkeypatch):
    from datetime import UTC, datetime
    from uuid import uuid4

    from worker import jobs
    from worker.models import Checkpoint

    prior = datetime(2026, 1, 1, tzinfo=UTC)
    calls: list[Checkpoint] = []

    class _Repo:
        def get_checkpoint(self, source_name):
            return Checkpoint(
                source_name=source_name,
                last_successful_sync_at=prior,
                last_cursor={},
            )

        def start_run(self, source_name, *, checkpoint_before, metadata=None):
            from worker.models import IngestionRun

            return IngestionRun(
                id=uuid4(),
                source_name=source_name,
                status="running",
                checkpoint_before=checkpoint_before,
                metadata=metadata or {},
            )

        def finish_run(self, *args, **kwargs):
            return None

        def quarantine(self, *args, **kwargs):
            return None

        def upsert_coverage(self, *args, **kwargs):
            return None

        def save_checkpoint(self, checkpoint):
            calls.append(checkpoint)

    class _Store:
        def __init__(self, repo):
            self.repo = repo

        def load(self, source_name):
            return self.repo.get_checkpoint(source_name)

        def save(self, checkpoint):
            self.repo.save_checkpoint(checkpoint)

    class _PartialAdapter:
        source_name = "yargitay"
        last_cursor = {
            "window_from": "2026-01-01",
            "window_to": "2026-01-31",
            "window_complete": False,
            "page": 2,
            "seen_count": 1,
            "stored_count": 0,
            "duplicate_count": 0,
            "failed_count": 0,
            "chamber": "",
        }

        def sync(self, request, *, cursor, connection, dry_run, should_stop):
            yield "quarantined", {
                "external_id": "yargitay:bad",
                "reason": "missing",
                "raw": {},
                "requests_made": 1,
            }

    class _SuccessAdapter(_PartialAdapter):
        last_cursor = {
            **_PartialAdapter.last_cursor,
            "window_complete": True,
            "stored_count": 1,
            "failed_count": 0,
        }

        def sync(self, request, *, cursor, connection, dry_run, should_stop):
            yield "created", {"external_id": "yargitay:ok", "requests_made": 1}

    class _Conn:
        def cursor(self):
            return _LockCursor(True)

    monkeypatch.setattr(jobs, "SyncRepository", lambda _c: _Repo())
    monkeypatch.setattr(jobs, "CheckpointStore", _Store)
    monkeypatch.setattr(jobs, "source_job_lock", source_job_lock)
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()

    partial = jobs.run_sync(
        _Conn(),
        SyncRequest(source="yargitay", dry_run=False, resume=False),
        adapter=_PartialAdapter(),
    )
    assert partial["status"] == "partial"
    assert calls[-1].last_successful_sync_at == prior

    success = jobs.run_sync(
        _Conn(),
        SyncRequest(source="yargitay", dry_run=False, resume=False),
        adapter=_SuccessAdapter(),
    )
    assert success["status"] == "success"
    assert calls[-1].last_successful_sync_at is not None
    assert calls[-1].last_successful_sync_at != prior


def test_yargitay_coverage_deltas_are_written_every_run(monkeypatch):
    """Incomplete window run'ları da coverage delta yazar; complete yalnız bayrak."""
    from uuid import uuid4

    from worker import jobs
    from worker.models import Checkpoint

    coverage_calls: list[dict] = []

    class _Repo:
        def get_checkpoint(self, source_name):
            return Checkpoint(source_name=source_name, last_cursor={})

        def start_run(self, source_name, *, checkpoint_before, metadata=None):
            from worker.models import IngestionRun

            return IngestionRun(
                id=uuid4(),
                source_name=source_name,
                status="running",
                checkpoint_before=checkpoint_before,
                metadata=metadata or {},
            )

        def finish_run(self, *args, **kwargs):
            return None

        def save_checkpoint(self, checkpoint):
            return None

        def upsert_coverage(self, source_name, date_from, date_to, **kwargs):
            coverage_calls.append({"source": source_name, **kwargs})

    class _Store:
        def __init__(self, repo):
            self.repo = repo

        def load(self, source_name):
            return self.repo.get_checkpoint(source_name)

        def save(self, checkpoint):
            self.repo.save_checkpoint(checkpoint)

    class _IncompleteAdapter:
        source_name = "yargitay"
        last_cursor = {
            "window_from": "2026-02-01",
            "window_to": "2026-02-28",
            "window_complete": False,
            "page": 2,
            "seen_count": 10,
            "stored_count": 7,
            "duplicate_count": 2,
            "failed_count": 1,
            "chamber": "9. Hukuk Dairesi",
            "expected_count": 100,
        }

        def sync(self, request, *, cursor, connection, dry_run, should_stop):
            yield "created", {"external_id": "yargitay:1", "requests_made": 1}

    class _Conn:
        def cursor(self):
            return _LockCursor(True)

    monkeypatch.setattr(jobs, "SyncRepository", lambda _c: _Repo())
    monkeypatch.setattr(jobs, "CheckpointStore", _Store)
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()

    result = jobs.run_sync(
        _Conn(),
        SyncRequest(source="yargitay", dry_run=False, resume=True),
        adapter=_IncompleteAdapter(),
    )
    assert result["status"] == "success"
    assert len(coverage_calls) == 1
    assert coverage_calls[0]["seen_count"] == 10
    assert coverage_calls[0]["stored_count"] == 7
    assert coverage_calls[0]["complete"] is False
