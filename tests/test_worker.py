from __future__ import annotations

from datetime import date

import pytest

from ingestion.yargitay.models import CourtDecision
from ingestion.yargitay.parser import content_hash
from ingestion.yargitay.portal import CaptchaRequiredError, PortalDecisionRow, PortalError, SearchPage
from ingestion.danistay.portal import (
    DanistayPortalError,
    PortalDecisionRow as DanistayDecisionRow,
    SearchPage as DanistaySearchPage,
)
from worker.adapters import get_adapter
from worker.adapters.danistay import DanistaySourceAdapter
from worker.adapters.yargitay import YargitaySourceAdapter
from worker.locks import JobLockedError, source_job_lock
from worker.jobs import (
    _carry_backfill_horizon,
    _cursor_advanced,
    _interval_for,
    _quarantined_progress,
)
from worker.models import Checkpoint, RunCounters, SyncRequest
from worker.windows import iter_month_windows, month_window, next_month_start


def test_month_windows_cover_range_without_gaps():
    windows = iter_month_windows(date(2026, 1, 15), date(2026, 3, 10))
    assert windows[0] == (date(2026, 1, 15), date(2026, 1, 31))
    assert windows[1] == (date(2026, 2, 1), date(2026, 2, 28))
    assert windows[2] == (date(2026, 3, 1), date(2026, 3, 10))
    assert next_month_start(date(2026, 12, 1)) == date(2027, 1, 1)
    assert month_window(date(2026, 8, 20)) == (date(2026, 8, 1), date(2026, 8, 31))


def test_backfill_cadence_only_when_more_work_and_previous_run_succeeded(monkeypatch):
    from datetime import timedelta
    from worker.config import get_worker_settings

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("YARGITAY_BACKFILL_INTERVAL_MINUTES", "60")
    get_worker_settings.cache_clear()
    today = date(2026, 9, 16)
    pending = {"window_complete": False, "next_window_start": "2026-01-01"}
    assert _interval_for("yargitay", cursor=pending, today=today) == timedelta(minutes=60)
    assert _interval_for("yargitay", cursor=pending, status="partial", today=today) == timedelta(minutes=360)
    completed_old = {"window_complete": True, "next_window_start": "2026-02-01"}
    assert _interval_for("yargitay", cursor=completed_old, today=today) == timedelta(minutes=60)
    completed_current = {"window_complete": True, "next_window_start": "2026-10-01"}
    assert _interval_for("yargitay", cursor=completed_current, today=today) == timedelta(minutes=360)
    assert _interval_for("mevzuat", cursor={"complete": False}, today=today) == timedelta(minutes=120)
    assert _interval_for("danistay", cursor={}, today=today) == timedelta(minutes=720)


def test_only_progressing_quarantine_qualifies_for_short_backfill_interval():
    previous = {"page": 9, "row_offset": 0, "seen_count": 40}
    progressed = {"page": 11, "row_offset": 0, "seen_count": 40}
    assert _quarantined_progress(previous, progressed, failed=0, quarantined=1)
    assert not _quarantined_progress(previous, progressed, failed=1, quarantined=1)
    assert not _quarantined_progress(previous, previous, failed=0, quarantined=1)
    assert not _quarantined_progress(previous, progressed, failed=0, quarantined=0)
    assert _cursor_advanced(previous, progressed)
    assert not _cursor_advanced(previous, previous)
    assert _cursor_advanced({"offset": 0}, {"offset": 40})


def test_backfill_horizon_survives_adapter_cursor_replacement():
    previous = {
        "full_horizon_start": "1982-01-01",
        "horizon_audit_version": 1,
        "next_window_start": "1982-01-01",
    }
    next_page = {"window_from": "1982-01-01", "next_window_start": "1982-02-01"}
    carried = _carry_backfill_horizon(previous, dict(next_page), "backfill")
    assert carried["full_horizon_start"] == "1982-01-01"
    assert carried["horizon_audit_version"] == 1
    assert carried["next_window_start"] == "1982-02-01"
    assert _carry_backfill_horizon(previous, dict(next_page), "current") == next_page


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


def test_legacy_yargitay_cursor_restarts_window_without_skipping(monkeypatch, tmp_path):
    from worker.adapters import yargitay as adapter_module
    from worker.config import get_worker_settings

    class _Client:
        base_url = "https://karararama.yargitay.gov.tr/"

        def __init__(self):
            self.pages = []

        def begin_detailed_search(self, filters):
            pass

        def search_page(self, filters):
            self.pages.append(filters["pageNumber"])
            return SearchPage(rows=(), records_total=0, records_filtered=0)

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()
    client = _Client()
    adapter = YargitaySourceAdapter(client=client)
    list(
        adapter.sync(
            SyncRequest(source="yargitay", resume=True, max_records=1),
            cursor={
                "page": 4,
                "window_from": "2026-01-01",
                "window_to": "2026-01-31",
                "window_complete": False,
            },
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert client.pages == [1]


def test_yargitay_empty_page_with_reported_results_is_not_complete(monkeypatch, tmp_path):
    from worker.config import get_worker_settings

    class _Client:
        base_url = "https://karararama.yargitay.gov.tr/"

        def begin_detailed_search(self, filters):
            pass

        def search_page(self, filters):
            return SearchPage(rows=(), records_total=12, records_filtered=12)

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()
    adapter = YargitaySourceAdapter(client=_Client())
    with pytest.raises(PortalError, match="sayfa boş"):
        list(
            adapter.sync(
                SyncRequest(
                    source="yargitay",
                    date_from=date(2026, 1, 1),
                    date_to=date(2026, 1, 31),
                    max_records=1,
                ),
                cursor={},
                connection=None,
                dry_run=True,
                should_stop=lambda: False,
            )
        )


def test_danistay_empty_page_with_reported_results_is_not_complete(monkeypatch, tmp_path):
    from worker.config import get_worker_settings

    class _Client:
        def begin_detailed_search(self, filters):
            pass

        def search_page(self, filters):
            return DanistaySearchPage(rows=(), records_total=12, records_filtered=12)

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()
    adapter = DanistaySourceAdapter(client=_Client())
    with pytest.raises(DanistayPortalError, match="sayfa boş"):
        list(
            adapter.sync(
                SyncRequest(source="danistay", date_from=date(2026, 1, 1),
                            date_to=date(2026, 1, 31), max_records=1),
                cursor={}, connection=None, dry_run=True, should_stop=lambda: False,
            )
        )


def test_danistay_quarantined_row_is_retried_before_window_advances(monkeypatch, tmp_path):
    from worker.adapters import danistay as adapter_module
    from worker.config import get_worker_settings

    class _Client:
        base_url = "https://karararama.danistay.gov.tr/"

        def begin_detailed_search(self, filters):
            pass

        def search_page(self, filters):
            return DanistaySearchPage(
                rows=(
                    DanistayDecisionRow("1", "1. Daire", "2026/1", "2026/1", "01.01.2026"),
                    DanistayDecisionRow("2", "1. Daire", "2026/2", "2026/2", "01.01.2026"),
                ),
                records_total=2,
                records_filtered=2,
            )

        def fetch_document_html(self, document_id, *, keyword):
            return f"<p>{document_id}</p>"

    def make_decision(row, _html, *, base_url):
        return CourtDecision(
            court_name="Danıştay", chamber=row.chamber, docket_no=row.docket_no,
            decision_no=row.decision_no, decision_date=date(2026, 1, 1),
            title="Karar", raw_text="" if row.document_id == "1" else "Karar metni",
            external_id=f"danistay:{row.document_id}",
            content_hash=content_hash(row.document_id),
            source_url=f"{base_url}getDokuman?id={row.document_id}",
        )

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("DANISTAY_DELAY_SECONDS", "0")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()
    monkeypatch.setattr(adapter_module, "decision_from_portal_row", make_decision)
    adapter = DanistaySourceAdapter(client=_Client())
    outcomes = list(adapter.sync(
        SyncRequest(source="danistay", date_from=date(2026, 1, 1),
                    date_to=date(2026, 1, 31), max_records=2),
        cursor={}, connection=None, dry_run=True, should_stop=lambda: False,
    ))
    assert [status for status, _ in outcomes] == ["quarantined", "created"]
    assert adapter.last_cursor["reconciled"] is True
    assert adapter.last_cursor["window_complete"] is True


def test_adapter_registry_exposes_active_sources():
    assert get_adapter("yargitay").source_name == "yargitay"
    assert get_adapter("danistay").active is True
    assert get_adapter("mevzuat").source_name == "mevzuat"
    assert get_adapter("aym").active is True
    assert get_adapter("resmi_gazete").active is False
    assert get_adapter("mevzuat_bilgi_sistemi").active is False
    assert get_adapter("kdk").active is True
    assert get_adapter("kdk").authority == "Kamu Denetçiliği Kurumu"
    assert get_adapter("mevzuat_verify").source_name == "mevzuat_verify"


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


def test_yargitay_resume_keeps_fixed_page_size_and_row_offset(monkeypatch, tmp_path):
    from worker.adapters import yargitay as adapter_module
    from worker.config import get_worker_settings

    class _PagedClient:
        base_url = "https://karararama.yargitay.gov.tr/"

        def __init__(self):
            self.requests = []

        def begin_detailed_search(self, filters):
            self.requests.append(("begin", filters["pageSize"]))

        def search_page(self, filters):
            page = filters["pageNumber"]
            size = filters["pageSize"]
            self.requests.append((page, size, filters["birimYrgHukukDaire"]))
            start = (page - 1) * size
            rows = tuple(
                PortalDecisionRow(str(i), "9. Hukuk Dairesi", f"2026/{i}", f"2026/{i}", "01.01.2026")
                for i in range(start + 1, min(start + size, 25) + 1)
            )
            return SearchPage(rows=rows, records_total=25, records_filtered=25)

        def fetch_document_html(self, document_id):
            return f"<p>Karar {document_id}</p>"

    def make_decision(row, _html, *, base_url):
        return CourtDecision(
            court_name="Yargıtay",
            chamber="9. Hukuk Dairesi",
            docket_no=row.docket_no,
            decision_no=row.decision_no,
            decision_date=date(2026, 1, 1),
            title=f"Karar {row.document_id}",
            raw_text=f"Karar metni {row.document_id}",
            external_id=f"yargitay:{row.document_id}",
            content_hash=content_hash(row.document_id),
            source_url=f"{base_url}getDokuman?id={row.document_id}",
        )

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("YARGITAY_DELAY_SECONDS", "0")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()
    monkeypatch.setattr(adapter_module, "decision_from_portal_row", make_decision)
    client = _PagedClient()
    cursor = {}
    seen = []
    for _ in range(4):
        adapter = YargitaySourceAdapter(client=client)
        outcomes = list(
            adapter.sync(
                SyncRequest(
                    source="yargitay",
                    date_from=date(2026, 1, 1),
                    date_to=date(2026, 1, 31),
                    chamber="9. Hukuk Dairesi" if not cursor else "",
                    max_records=7,
                ),
                cursor=cursor,
                connection=None,
                dry_run=True,
                should_stop=lambda: False,
            )
        )
        seen.extend(payload["external_id"] for _, payload in outcomes)
        cursor = adapter.last_cursor

    assert seen == [f"yargitay:{i}" for i in range(1, 26)]
    assert cursor["window_complete"] is True
    page_requests = [request for request in client.requests if request[0] != "begin"]
    assert all(size == 20 for _, size, _ in page_requests)
    assert all(chamber == "9. Hukuk Dairesi" for _, _, chamber in page_requests)


def test_yargitay_failed_row_is_retried_before_window_advances(monkeypatch, tmp_path):
    from worker.adapters import yargitay as adapter_module
    from worker.config import get_worker_settings

    class _Client:
        base_url = "https://karararama.yargitay.gov.tr/"

        def begin_detailed_search(self, filters):
            pass

        def search_page(self, filters):
            return SearchPage(
                rows=(
                    PortalDecisionRow("1", "9. Hukuk Dairesi", "2026/1", "2026/1", "01.01.2026"),
                    PortalDecisionRow("2", "9. Hukuk Dairesi", "2026/2", "2026/2", "01.01.2026"),
                ),
                records_total=2,
                records_filtered=2,
            )

        def fetch_document_html(self, document_id):
            return f"<p>{document_id}</p>"

    def make_decision(row, _html, *, base_url):
        return CourtDecision(
            court_name="Yargıtay",
            chamber=row.chamber,
            docket_no=row.docket_no,
            decision_no=row.decision_no,
            decision_date=date(2026, 1, 1),
            title="Karar",
            raw_text="" if row.document_id == "1" else "Geçerli karar metni",
            external_id=f"yargitay:{row.document_id}",
            content_hash=content_hash(row.document_id),
            source_url=f"{base_url}getDokuman?id={row.document_id}",
        )

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("YARGITAY_DELAY_SECONDS", "0")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()
    monkeypatch.setattr(adapter_module, "decision_from_portal_row", make_decision)
    adapter = YargitaySourceAdapter(client=_Client())
    outcomes = list(
        adapter.sync(
            SyncRequest(
                source="yargitay",
                date_from=date(2026, 1, 1),
                date_to=date(2026, 1, 31),
                max_records=2,
            ),
            cursor={},
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert [status for status, _ in outcomes] == ["quarantined", "created"]
    assert adapter.last_cursor["quarantined_count"] == 1
    assert adapter.last_cursor["stored_count"] == 1
    assert adapter.last_cursor["reconciled"] is True
    assert adapter.last_cursor["window_complete"] is True


class _KnownSourcesConnection:
    def __init__(self, known):
        self.known = set(known)

    def execute(self, _sql, params=None):
        wanted = set(params[0]) if params else set()
        hits = [(eid,) for eid in sorted(self.known & wanted)]

        class _Result:
            def fetchall(self_inner):
                return hits

        return _Result()


def test_yargitay_skips_document_fetch_when_source_exists(monkeypatch, tmp_path):
    outcomes, client = _sync_yargitay_two_rows(
        monkeypatch,
        tmp_path,
        lane="backfill",
        known={"yargitay:1"},
    )
    assert [status for status, _ in outcomes] == ["unchanged", "created"]
    assert outcomes[0][1]["skipped_existing"] is True
    assert client.fetched == ["2"]
    assert outcomes[0][1]["external_id"] == "yargitay:1"


def test_yargitay_current_lane_refetches_existing_source(monkeypatch, tmp_path):
    outcomes, client = _sync_yargitay_two_rows(
        monkeypatch,
        tmp_path,
        lane="current",
        known={"yargitay:1", "yargitay:2"},
    )
    assert [status for status, _ in outcomes] == ["created", "created"]
    assert "skipped_existing" not in outcomes[0][1]
    assert client.fetched == ["1", "2"]


def _sync_yargitay_two_rows(monkeypatch, tmp_path, *, lane: str, known: set[str]):
    from worker.adapters import yargitay as adapter_module
    from worker.config import get_worker_settings

    class _Client:
        base_url = "https://karararama.yargitay.gov.tr/"

        def __init__(self):
            self.fetched = []

        def begin_detailed_search(self, filters):
            pass

        def search_page(self, filters):
            return SearchPage(
                rows=(
                    PortalDecisionRow("1", "9. Hukuk Dairesi", "2026/1", "2026/1", "01.01.2026"),
                    PortalDecisionRow("2", "9. Hukuk Dairesi", "2026/2", "2026/2", "01.01.2026"),
                ),
                records_total=2,
                records_filtered=2,
            )

        def fetch_document_html(self, document_id):
            self.fetched.append(document_id)
            return f"<p>Karar {document_id} yeterli metin.</p>"

    def make_decision(row, _html, *, base_url):
        return CourtDecision(
            court_name="Yargıtay",
            chamber=row.chamber,
            docket_no=row.docket_no,
            decision_no=row.decision_no,
            decision_date=date(2026, 1, 1),
            title="Karar",
            raw_text=f"Karar metni {row.document_id}",
            external_id=f"yargitay:{row.document_id}",
            content_hash=content_hash(row.document_id),
            source_url=f"{base_url}getDokuman?id={row.document_id}",
        )

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("YARGITAY_DELAY_SECONDS", "0")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()
    monkeypatch.setattr(adapter_module, "decision_from_portal_row", make_decision)
    client = _Client()
    adapter = YargitaySourceAdapter(client=client)
    outcomes = list(
        adapter.sync(
            SyncRequest(
                source="yargitay",
                date_from=date(2026, 1, 1),
                date_to=date(2026, 1, 31),
                max_records=2,
                lane=lane,
            ),
            cursor={},
            connection=_KnownSourcesConnection(known),
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    return outcomes, client


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


def _law_document(law_no: str, mevzuat_id: str, name: str) -> dict:
    return {
        "mevzuatId": mevzuat_id,
        "mevzuatNo": law_no,
        "mevzuatAdi": name,
        "mevzuatTur": {"name": "KANUN"},
    }


class _TwoLawCatalog(_MevzuatClientSuccessThenQuarantine):
    def search_page(self, **kwargs):
        from ingestion.mevzuat.portal import SearchPage

        laws = (
            _law_document("4857", "1", "İş Kanunu"),
            _law_document("4721", "2", "Türk Medeni Kanunu"),
        )
        law_no = kwargs.get("law_no")
        if law_no:
            match = next((item for item in laws if item["mevzuatNo"] == law_no), None)
            return SearchPage(
                documents=(match,) if match else (),
                total=1 if match else 0,
                start=0,
            )
        page_number = int(kwargs.get("page_number") or 1)
        page_size = int(kwargs.get("page_size") or 10)
        start = (page_number - 1) * page_size
        return SearchPage(
            documents=laws[start : start + page_size],
            total=len(laws),
            start=start,
        )

    def fetch_article_html(self, madde_id):
        return f"<p>Geçerli madde metni {madde_id}.</p>"


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


def test_mevzuat_refetches_article_html_when_source_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("MEVZUAT_DELAY_SECONDS", "0")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    from worker.adapters.mevzuat import MevzuatSourceAdapter
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()

    class _Client(_MevzuatClientSuccessThenQuarantine):
        def __init__(self):
            self.fetched = []

        def fetch_article_html(self, madde_id):
            self.fetched.append(madde_id)
            return f"<p>Geçerli madde metni {madde_id}.</p>"

    client = _Client()
    adapter = MevzuatSourceAdapter(
        client=client, verify_gazette=False, verify_mbs=False
    )
    outcomes = list(
        adapter.sync(
            SyncRequest(
                source="mevzuat",
                law_no="4857",
                max_records=10,
                resume=False,
                lane="backfill",
            ),
            cursor={},
            connection=_KnownSourcesConnection({"mevzuat:kanun:4857:m.1"}),
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert [status for status, _ in outcomes] == ["created", "created", "created"]
    assert all("skipped_existing" not in payload for _, payload in outcomes)
    assert client.fetched == ["a1", "a2", "a3"]
    assert adapter.last_cursor["complete"] is True


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
            cursor={"law_index": 0, "law_no": "4857", "last_article_no": "1"},
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    article_nos = [payload["article_no"] for _, payload in outcomes]
    assert "1" not in article_nos
    assert article_nos[0] == "2"
    assert adapter.last_cursor["last_article_no"] == ""
    assert adapter.last_cursor["complete"] is True


def test_mevzuat_limit_at_law_boundary_advances_without_skipping_next_law(
    monkeypatch, tmp_path
):
    from worker.adapters.mevzuat import MevzuatSourceAdapter
    from worker.config import get_worker_settings

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("MEVZUAT_DELAY_SECONDS", "0")
    monkeypatch.setenv("MEVZUAT_DISCOVERY_TYPES", "KANUN")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()
    adapter = MevzuatSourceAdapter(
        client=_TwoLawCatalog(), verify_gazette=False, verify_mbs=False
    )
    cursor = {}
    for expected_article in ("1", "2", "3"):
        outcomes = list(adapter.sync(
            SyncRequest(source="mevzuat", max_records=1),
            cursor=cursor,
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        ))
        assert [payload["article_no"] for _, payload in outcomes] == [expected_article]
        assert outcomes[0][1]["law_no"] == "4857"
        cursor = adapter.last_cursor

    assert cursor["mode"] == "discovery"
    assert cursor["catalog_offset"] == 1
    assert cursor["last_article_no"] == ""
    outcomes = list(adapter.sync(
        SyncRequest(source="mevzuat", max_records=1),
        cursor=cursor,
        connection=None,
        dry_run=True,
        should_stop=lambda: False,
    ))
    assert outcomes[0][1]["law_no"] == "4721"
    assert outcomes[0][1]["article_no"] == "1"


def test_mevzuat_legacy_cursor_restarts_law_instead_of_skipping(monkeypatch, tmp_path):
    from worker.adapters.mevzuat import MevzuatSourceAdapter
    from worker.config import get_worker_settings

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("MEVZUAT_DELAY_SECONDS", "0")
    monkeypatch.setenv("MEVZUAT_DISCOVERY_TYPES", "KANUN")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()
    adapter = MevzuatSourceAdapter(
        client=_TwoLawCatalog(), verify_gazette=False, verify_mbs=False
    )
    outcomes = list(adapter.sync(
        SyncRequest(source="mevzuat", max_records=1),
        cursor={"law_index": 1, "last_article_no": "31"},
        connection=None,
        dry_run=True,
        should_stop=lambda: False,
    ))
    assert outcomes[0][1]["law_no"] == "4857"
    assert outcomes[0][1]["article_no"] == "1"
    assert adapter.last_cursor["mode"] == "discovery"


def test_mevzuat_skips_missing_article_tree_and_continues_catalog(monkeypatch, tmp_path):
    from ingestion.mevzuat.portal import MevzuatPortalError
    from worker.adapters.mevzuat import MevzuatSourceAdapter
    from worker.config import get_worker_settings

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("MEVZUAT_DELAY_SECONDS", "0")
    monkeypatch.setenv("MEVZUAT_DISCOVERY_TYPES", "KANUN")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()

    class _MissingThenGood(_TwoLawCatalog):
        def fetch_article_tree(self, mevzuat_id):
            if str(mevzuat_id) == "1":
                raise MevzuatPortalError(
                    "İlgili mevzuata ait ağaç yapısı mevcut değildir."
                )
            return super().fetch_article_tree(mevzuat_id)

    adapter = MevzuatSourceAdapter(
        client=_MissingThenGood(), verify_gazette=False, verify_mbs=False
    )
    outcomes = list(
        adapter.sync(
            SyncRequest(source="mevzuat", max_records=1),
            cursor={},
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert outcomes[0][0] == "quarantined"
    assert outcomes[0][1]["reason_code"] == "missing_article_tree"
    assert outcomes[0][1]["law_no"] == "4857"
    assert outcomes[1][0] == "created"
    assert outcomes[1][1]["law_no"] == "4721"
    assert adapter.last_cursor["law_no"] == "4721"
    assert adapter.last_cursor.get("complete") is not True


def test_mevzuat_targeted_missing_tree_does_not_mark_complete(monkeypatch, tmp_path):
    from ingestion.mevzuat.portal import MevzuatPortalError
    from worker.adapters.mevzuat import MevzuatSourceAdapter
    from worker.config import get_worker_settings

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("MEVZUAT_DELAY_SECONDS", "0")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    get_worker_settings.cache_clear()

    class _NoTree(_MevzuatClientSuccessThenQuarantine):
        def fetch_article_tree(self, mevzuat_id):
            raise MevzuatPortalError("İlgili mevzuata ait ağaç yapısı mevcut değildir.")

    adapter = MevzuatSourceAdapter(
        client=_NoTree(), verify_gazette=False, verify_mbs=False
    )
    outcomes = list(
        adapter.sync(
            SyncRequest(source="mevzuat", law_no="4857", max_records=10, resume=False),
            cursor={},
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert len(outcomes) == 1
    assert outcomes[0][0] == "quarantined"
    assert outcomes[0][1]["reason_code"] == "missing_article_tree"
    assert adapter.last_cursor.get("complete") is not True


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
    assert calls[-1].health_state == "healthy"

    success = jobs.run_sync(
        _Conn(),
        SyncRequest(source="yargitay", dry_run=False, resume=False),
        adapter=_SuccessAdapter(),
    )
    assert success["status"] == "success"
    assert calls[-1].last_successful_sync_at is not None
    assert calls[-1].last_successful_sync_at != prior


def test_targeted_mevzuat_run_preserves_starter_checkpoint(monkeypatch):
    from contextlib import nullcontext
    from datetime import UTC, datetime
    from uuid import uuid4

    from worker import jobs
    from worker.models import IngestionRun

    next_run = datetime(2026, 9, 17, tzinfo=UTC)
    checkpoint = Checkpoint(
        source_name="mevzuat",
        last_cursor={"profile": "starter", "law_index": 1, "last_article_no": "31"},
        next_run_at=next_run,
    )
    saved = []
    finished = []
    seen_cursors = []

    class Repo:
        def get_checkpoint(self, source_name):
            return checkpoint

        def start_run(self, source_name, *, checkpoint_before, metadata=None):
            return IngestionRun(
                id=uuid4(), source_name=source_name, status="running",
                checkpoint_before=checkpoint_before,
            )

        def finish_run(self, *args, **kwargs):
            finished.append(kwargs)

        def save_checkpoint(self, value):
            saved.append(value)

    class Adapter:
        last_cursor = {"law_index": 0, "last_article_no": "14", "complete": True}

        def sync(self, request, *, cursor, connection, dry_run, should_stop):
            seen_cursors.append(cursor)
            yield "created", {"external_id": "mevzuat:1475:14", "requests_made": 1}

    monkeypatch.setattr(jobs, "SyncRepository", lambda connection: Repo())
    monkeypatch.setattr(jobs, "source_job_lock", lambda connection, source: nullcontext())
    result = jobs.run_sync(
        object(), SyncRequest(source="mevzuat", law_no="1475"), adapter=Adapter()
    )

    assert result["status"] == "success"
    assert seen_cursors == [{}]
    assert saved == []
    assert result["checkpoint"]["last_cursor"] == checkpoint.last_cursor
    assert checkpoint.next_run_at == next_run
    assert finished[0]["metadata"]["targeted_law"] == "1475"


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


def test_current_lane_windows_wrap_to_lookback_horizon():
    from worker.lanes import (
        advance_window_start,
        checkpoint_name,
        daemon_jobs,
        resolve_sync_window,
        wrap_current_next_start,
    )

    today = date(2026, 9, 16)
    request = SyncRequest(source="yargitay", lane="current")
    corpus = date(2020, 1, 1)
    assert checkpoint_name("yargitay", "current") == "yargitay:current"
    assert checkpoint_name("yargitay", "backfill") == "yargitay"
    jobs = daemon_jobs()
    assert jobs[0] == ("yargitay", "current")
    assert jobs[1] == ("yargitay", "backfill")
    assert ("mevzuat", "current") not in jobs
    assert resolve_sync_window(
        request,
        {},
        corpus_start=corpus,
        today=today,
        lookback_days=45,
    ) == (date(2026, 8, 1), date(2026, 8, 31))
    assert resolve_sync_window(
        request,
        {
            "window_from": "2026-09-01",
            "window_to": "2026-09-30",
            "window_complete": False,
        },
        corpus_start=corpus,
        today=today,
        lookback_days=45,
    ) == (date(2026, 9, 1), date(2026, 9, 30))
    assert wrap_current_next_start(
        date(2026, 9, 1), today=today, lookback_days=45
    ) == date(2026, 8, 1)
    assert advance_window_start(
        date(2026, 8, 1), True, request, today=today, lookback_days=45
    ) == date(2026, 9, 1)
    backfill = SyncRequest(source="yargitay", lane="backfill")
    assert resolve_sync_window(
        backfill,
        {"next_window_start": "2020-03-01", "window_complete": True},
        corpus_start=corpus,
        today=today,
    ) == (date(2020, 3, 1), date(2020, 3, 31))


def test_current_lane_cadence_and_coverage_never_complete(monkeypatch):
    from datetime import timedelta
    from uuid import uuid4

    from worker import jobs
    from worker.config import get_worker_settings
    from worker.models import Checkpoint

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("CURRENT_SYNC_INTERVAL_MINUTES", "180")
    monkeypatch.setenv("CURRENT_RETRY_INTERVAL_MINUTES", "60")
    get_worker_settings.cache_clear()
    pending = {"window_complete": False, "next_window_start": "2026-09-01"}
    assert _interval_for(
        "yargitay", cursor=pending, lane="current"
    ) == timedelta(minutes=60)
    advancing = {
        "window_complete": True,
        "window_from": "2026-08-01",
        "next_window_start": "2026-09-01",
    }
    assert _interval_for(
        "yargitay", cursor=advancing, lane="current"
    ) == timedelta(minutes=60)
    wrapped = {
        "window_complete": True,
        "window_from": "2026-09-01",
        "next_window_start": "2026-08-01",
    }
    assert _interval_for(
        "yargitay", cursor=wrapped, lane="current"
    ) == timedelta(minutes=180)
    assert _interval_for(
        "yargitay", cursor=pending, status="failed", lane="current"
    ) == timedelta(minutes=180)

    coverage_calls: list[dict] = []
    loaded: list[str] = []
    started: list[str] = []

    class _Repo:
        def get_checkpoint(self, source_name):
            loaded.append(source_name)
            return Checkpoint(source_name=source_name, last_cursor={})

        def start_run(self, source_name, *, checkpoint_before, metadata=None):
            from worker.models import IngestionRun

            started.append(source_name)
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

    class _Adapter:
        source_name = "yargitay"
        last_cursor = {
            "window_from": "2026-09-01",
            "window_to": "2026-09-30",
            "window_complete": True,
            "page": 1,
            "seen_count": 4,
            "stored_count": 3,
            "duplicate_count": 1,
            "failed_count": 0,
            "chamber": "",
        }

        def sync(self, request, *, cursor, connection, dry_run, should_stop):
            assert request.lane == "current"
            yield "created", {"external_id": "yargitay:1", "requests_made": 1}

    class _Conn:
        def cursor(self):
            return _LockCursor(True)

    monkeypatch.setattr(jobs, "SyncRepository", lambda _c: _Repo())
    monkeypatch.setattr(jobs, "CheckpointStore", _Store)
    result = jobs.run_sync(
        _Conn(),
        SyncRequest(source="yargitay", lane="current", dry_run=False, resume=True),
        adapter=_Adapter(),
    )
    assert result["status"] == "success"
    assert result["job"] == "yargitay:current"
    assert loaded == ["yargitay:current"]
    assert started == ["yargitay:current"]
    assert coverage_calls[0]["source"] == "yargitay"
    assert coverage_calls[0]["complete"] is False


def test_due_jobs_runs_current_before_backfill(monkeypatch):
    from datetime import UTC, datetime

    from worker.models import Checkpoint
    from worker.scheduler import due_jobs

    now = datetime(2026, 9, 16, tzinfo=UTC)
    due_names = {"yargitay:current", "yargitay", "mevzuat"}

    class Repo:
        def __init__(self, _connection):
            return None

        def get_checkpoint(self, source_name):
            checkpoint = Checkpoint(source_name=source_name)
            if source_name in due_names:
                checkpoint.next_run_at = None
            else:
                checkpoint.next_run_at = datetime(2099, 1, 1, tzinfo=UTC)
            return checkpoint

    monkeypatch.setattr("worker.scheduler.SyncRepository", Repo)
    jobs = due_jobs(object(), now=now)
    assert jobs[0] == ("yargitay", "current")
    assert jobs.index(("yargitay", "current")) < jobs.index(("yargitay", "backfill"))
    assert ("mevzuat", "backfill") in jobs
    assert ("mevzuat", "current") not in jobs
