from __future__ import annotations

from datetime import date

import pytest

from ingestion.yargitay.models import CourtDecision
from ingestion.yargitay.parser import content_hash
from ingestion.yargitay.portal import CaptchaRequiredError, PortalDecisionRow, SearchPage
from worker.adapters import get_adapter
from worker.adapters.planned import DanistaySourceAdapter
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


def test_planned_sources_are_blocked_not_fake_success():
    adapter = DanistaySourceAdapter()
    health = adapter.health_check()
    assert health.state == "blocked"
    assert health.active is False
    with pytest.raises(RuntimeError, match="ACTIVE değil"):
        next(
            adapter.sync(
                SyncRequest(source="danistay"),
                cursor={},
                connection=None,
                dry_run=True,
                should_stop=lambda: False,
            )
        )


def test_adapter_registry_exposes_active_sources():
    assert get_adapter("yargitay").source_name == "yargitay"
    assert get_adapter("mevzuat").source_name == "mevzuat"
    assert get_adapter("aym").active is False
    assert get_adapter("resmi_gazete").active is False


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
