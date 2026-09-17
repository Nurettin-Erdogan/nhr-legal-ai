from __future__ import annotations

from datetime import date

from worker.backfill import apply_full_horizon, is_historical_complete, run_full_backfill
from worker.models import Checkpoint
from worker.runner import build_parser


def _healthy_repo(monkeypatch) -> None:
    class FakeRepo:
        def get_checkpoint(self, source):
            return Checkpoint(source_name=source, health_state="healthy")

    monkeypatch.setattr("worker.backfill.SyncRepository", lambda _c: FakeRepo())


def test_historical_complete_uses_next_window_and_catalog_flag():
    today = date(2026, 9, 16)
    assert (
        is_historical_complete(
            "yargitay",
            {"window_complete": True, "reconciled": True, "next_window_start": "2026-10-01"},
            today=today,
        )
        is True
    )
    assert (
        is_historical_complete(
            "yargitay",
            {"window_complete": True, "next_window_start": "2026-09-01"},
            today=today,
        )
        is False
    )
    assert is_historical_complete("mevzuat", {"complete": True}, today=today) is True
    assert is_historical_complete("aym", {"complete": False}, today=today) is False


def test_full_horizon_is_a_floor_and_migrates_mevzuat_off_starter():
    horizon = date(2020, 1, 1)
    jumped = apply_full_horizon(
        "yargitay",
        {
            "window_from": "1983-04-01",
            "window_complete": True,
            "next_window_start": "1983-05-01",
            "full_horizon_start": "1980-01-01",
        },
        horizon=horizon,
    )
    assert jumped["next_window_start"] == "2020-01-01"
    assert jumped["full_horizon_start"] == "2020-01-01"

    kept = apply_full_horizon(
        "yargitay",
        {
            "window_from": "2024-05-01",
            "window_complete": True,
            "next_window_start": "2024-06-01",
            "full_horizon_start": "2020-01-01",
            "horizon_audit_version": 1,
        },
        horizon=horizon,
    )
    assert kept["next_window_start"] == "2024-06-01"
    assert kept["full_horizon_start"] == "2020-01-01"
    assert apply_full_horizon("yargitay", kept, horizon=horizon) == kept

    unverified_gap = apply_full_horizon(
        "danistay",
        {
            "window_from": "2020-01-01",
            "window_complete": False,
            "next_window_start": "2020-01-01",
            "full_horizon_start": "1982-01-01",
        },
        horizon=date(1982, 1, 1),
    )
    assert unverified_gap["next_window_start"] == "1982-01-01"
    assert unverified_gap["horizon_audit_version"] == 1
    assert apply_full_horizon("danistay", unverified_gap, horizon=date(1982, 1, 1)) == unverified_gap

    empty = apply_full_horizon("kdk", {}, horizon=horizon)
    assert empty["next_window_start"] == "2020-01-01"

    migrated = apply_full_horizon(
        "mevzuat",
        {"profile": "starter", "law_index": 3, "law_no": "4857", "last_article_no": "12"},
        horizon=horizon,
    )
    assert migrated["mode"] == "discovery"
    assert migrated["law_no"] == "4857"
    assert migrated["last_article_no"] == "12"
    assert migrated["complete"] is False


def test_corpus_start_does_not_go_before_source_floor(monkeypatch):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("FULL_CORPUS_START", "1980-01-01")
    monkeypatch.setenv("YARGITAY_CORPUS_START", "2020-01-01")
    from worker.backfill import corpus_start_for
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    assert corpus_start_for("yargitay") == date(2020, 1, 1)
    assert corpus_start_for("aym") == date(1980, 1, 1)
    get_worker_settings.cache_clear()


def test_run_full_backfill_loops_embeds_and_switches_to_incremental(monkeypatch):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("BACKFILL_PAUSE_SECONDS", "0")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    _healthy_repo(monkeypatch)
    calls = {"sync": 0, "embed": 0, "daemon": 0}

    def fake_prepare(_connection, source):
        return {}

    def fake_sync(_connection, request, should_stop=None):
        calls["sync"] += 1
        complete = calls["sync"] >= 2
        return {
            "source": request.source,
            "status": "success",
            "run_id": str(calls["sync"]),
            "checkpoint": {
                "last_cursor": {
                    "window_complete": complete,
                    "reconciled": complete,
                    "next_window_start": "2099-01-01" if complete else "2020-01-01",
                    "complete": complete,
                }
            },
        }

    def fake_embed(_connection):
        calls["embed"] += 1
        return {"embedded": 3, "remaining": 0}

    def fake_daemon(_connection, should_stop=None, poll_seconds=None):
        calls["daemon"] += 1

    monkeypatch.setattr("worker.backfill.prepare_full_backfill", fake_prepare)
    summary = run_full_backfill(
        object(),
        ["yargitay"],
        embed=True,
        then_incremental=True,
        pause_seconds=0,
        sync=fake_sync,
        embed_fn=fake_embed,
        daemon=fake_daemon,
    )
    assert calls["sync"] == 2
    assert calls["embed"] == 2
    assert calls["daemon"] == 1
    assert summary["completed"] == ["yargitay"]
    assert summary["status"] == "incremental"


def test_run_full_backfill_stops_source_on_captcha(monkeypatch):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    _healthy_repo(monkeypatch)

    monkeypatch.setattr("worker.backfill.prepare_full_backfill", lambda *_: {})

    def fake_sync(_connection, request, should_stop=None):
        return {
            "source": request.source,
            "status": "captcha_required",
            "checkpoint": {"last_cursor": {"window_complete": False}},
        }

    summary = run_full_backfill(
        object(),
        ["danistay"],
        embed=False,
        then_incremental=False,
        pause_seconds=0,
        sync=fake_sync,
        daemon=lambda **_k: None,
    )
    assert summary["blocked"] == ["danistay"]
    assert summary["completed"] == []


def test_run_full_backfill_skips_captcha_blocked_source(monkeypatch):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    monkeypatch.setattr("worker.backfill.prepare_full_backfill", lambda *_: {})

    class FakeRepo:
        def get_checkpoint(self, source):
            return Checkpoint(
                source_name=source,
                health_state="blocked",
                last_error="CAPTCHA dogrulaması istiyor",
            )

    monkeypatch.setattr("worker.backfill.SyncRepository", lambda _c: FakeRepo())
    calls = {"sync": 0}

    def fake_sync(*_args, **_kwargs):
        calls["sync"] += 1
        return {"status": "success", "checkpoint": {"last_cursor": {}}}

    summary = run_full_backfill(
        object(),
        ["danistay"],
        embed=False,
        then_incremental=False,
        pause_seconds=0,
        sync=fake_sync,
        daemon=lambda **_k: None,
    )
    assert calls["sync"] == 0
    assert summary["blocked"] == ["danistay"]
    assert summary["remaining"] == []


def test_lock_contention_retries_in_seconds_not_hours(monkeypatch):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    _healthy_repo(monkeypatch)
    monkeypatch.setattr("worker.backfill.prepare_full_backfill", lambda *_: {})
    observed = []
    stopped = [False]

    def fake_sync(_connection, _request, should_stop=None):
        return {"status": "failed", "error": "aym sync zaten çalışıyor"}

    def fake_sleep(seconds):
        observed.append(seconds)
        stopped[0] = True

    monkeypatch.setattr("worker.backfill.sleep", fake_sleep)
    run_full_backfill(
        object(), ["aym"], should_stop=lambda: stopped[0],
        embed=False, then_incremental=False, pause_seconds=2, sync=fake_sync,
    )
    assert observed and observed[0] <= 15


def test_failed_source_cools_down_without_starving_other_sources(monkeypatch):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    _healthy_repo(monkeypatch)
    monkeypatch.setattr("worker.backfill.prepare_full_backfill", lambda *_: {})
    stopped = [False]
    calls: list[str] = []

    def fake_sync(_connection, request, should_stop=None):
        calls.append(request.source)
        if request.source == "yargitay":
            return {"status": "failed", "checkpoint": {"last_cursor": {}}}
        return {
            "status": "success",
            "checkpoint": {"last_cursor": {
                "window_complete": True, "reconciled": True,
                "next_window_start": "2099-01-01",
            }},
        }

    def stop_during_cooldown(_seconds):
        stopped[0] = True

    monkeypatch.setattr("worker.backfill.sleep", stop_during_cooldown)
    summary = run_full_backfill(
        object(), ["yargitay", "danistay"],
        should_stop=lambda: stopped[0], embed=False, then_incremental=False,
        pause_seconds=0, sync=fake_sync,
    )
    assert calls == ["yargitay", "danistay"]
    assert summary["completed"] == ["danistay"]
    assert summary["remaining"] == ["yargitay"]


def test_stationary_success_is_deferred_instead_of_spinning(monkeypatch):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    _healthy_repo(monkeypatch)
    monkeypatch.setattr("worker.backfill.prepare_full_backfill", lambda *_: {})
    stopped = [False]
    calls = [0]

    def fake_sync(_connection, _request, should_stop=None):
        calls[0] += 1
        return {"status": "success", "checkpoint": {"last_cursor": {}}}

    monkeypatch.setattr("worker.backfill.sleep", lambda _seconds: stopped.__setitem__(0, True))
    run_full_backfill(
        object(), ["aym"], should_stop=lambda: stopped[0],
        embed=False, then_incremental=False, pause_seconds=0, sync=fake_sync,
    )
    assert calls[0] == 1


def test_kdk_offset_progress_keeps_short_pause(monkeypatch):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    _healthy_repo(monkeypatch)
    monkeypatch.setattr("worker.backfill.prepare_full_backfill", lambda *_: {})
    stopped = [False]
    observed = []

    def fake_sync(_connection, _request, should_stop=None):
        return {
            "status": "success",
            "checkpoint": {
                "last_cursor": {
                    "offset": 40,
                    "window_from": "2017-11-01",
                    "window_complete": False,
                }
            },
        }

    def short_pause(seconds):
        observed.append(seconds)
        stopped[0] = True

    monkeypatch.setattr("worker.backfill.sleep", short_pause)
    run_full_backfill(
        object(), ["kdk"], should_stop=lambda: stopped[0],
        embed=False, then_incremental=False, pause_seconds=2, sync=fake_sync,
    )
    assert observed == [2]


def test_progressing_partial_with_failed_row_keeps_short_pause(monkeypatch):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    _healthy_repo(monkeypatch)
    monkeypatch.setattr("worker.backfill.prepare_full_backfill", lambda *_: {})
    stopped = [False]
    observed = []

    def fake_sync(_connection, _request, should_stop=None):
        return {
            "status": "partial",
            "counters": {"records_failed": 1, "records_quarantined": 0},
            "checkpoint": {"last_cursor": {"page": 3, "window_complete": False}},
        }

    def short_pause(seconds):
        observed.append(seconds)
        stopped[0] = True

    monkeypatch.setattr("worker.backfill.sleep", short_pause)
    run_full_backfill(
        object(), ["yargitay"], should_stop=lambda: stopped[0],
        embed=False, then_incremental=False, pause_seconds=2, sync=fake_sync,
    )
    assert observed == [2]


def test_degraded_checkpoint_does_not_block_full_backfill(monkeypatch):
    from datetime import UTC, datetime, timedelta

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    monkeypatch.setattr("worker.backfill.prepare_full_backfill", lambda *_: {})

    class FakeRepo:
        def get_checkpoint(self, source):
            return Checkpoint(
                source_name=source,
                health_state="degraded",
                next_run_at=datetime.now(UTC) + timedelta(hours=12),
            )

    monkeypatch.setattr("worker.backfill.SyncRepository", lambda _c: FakeRepo())
    calls = [0]
    stopped = [False]

    def fake_sync(_connection, _request, should_stop=None):
        calls[0] += 1
        return {
            "status": "partial",
            "counters": {"records_failed": 1, "records_created": 40},
            "checkpoint": {"last_cursor": {"page": 2, "window_complete": False}},
        }

    monkeypatch.setattr(
        "worker.backfill.sleep", lambda _seconds: stopped.__setitem__(0, True)
    )
    run_full_backfill(
        object(), ["kdk"], should_stop=lambda: stopped[0],
        embed=False, then_incremental=False, pause_seconds=2, sync=fake_sync,
    )
    assert calls[0] == 1


def test_progressing_quarantine_uses_backfill_cadence_without_spinning(monkeypatch):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    _healthy_repo(monkeypatch)
    monkeypatch.setattr("worker.backfill.prepare_full_backfill", lambda *_: {})
    stopped = [False]
    observed = []

    def fake_sync(_connection, _request, should_stop=None):
        return {
            "status": "partial",
            "counters": {"records_failed": 0, "records_quarantined": 1},
            "checkpoint": {"last_cursor": {"page": 2, "window_complete": False}},
        }

    def short_pause(seconds):
        observed.append(seconds)
        stopped[0] = True

    monkeypatch.setattr("worker.backfill.sleep", short_pause)
    run_full_backfill(
        object(), ["aym"], should_stop=lambda: stopped[0],
        embed=False, then_incremental=False, pause_seconds=2, sync=fake_sync,
    )
    assert observed == [2]


def test_danistay_success_has_minimum_inter_run_pause(monkeypatch):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("DANISTAY_BACKFILL_PAUSE_SECONDS", "30")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    _healthy_repo(monkeypatch)
    monkeypatch.setattr("worker.backfill.prepare_full_backfill", lambda *_: {})
    stopped = [False]
    pauses = []

    def fake_sync(_connection, _request, should_stop=None):
        return {
            "status": "success",
            "checkpoint": {"last_cursor": {"page": 2, "window_complete": False}},
        }

    def fake_sleep(seconds):
        pauses.append(seconds)
        stopped[0] = True

    monkeypatch.setattr("worker.backfill.sleep", fake_sleep)
    run_full_backfill(
        object(), ["danistay"], should_stop=lambda: stopped[0],
        embed=False, then_incremental=False, pause_seconds=2, sync=fake_sync,
    )
    assert pauses == [30]


def test_backfill_cli_is_registered():
    parser = build_parser()
    args = parser.parse_args(["backfill", "--source", "all", "--no-incremental", "--no-embed"])
    assert args.command == "backfill"
    assert args.source == "all"
    assert args.no_incremental is True
    assert args.no_embed is True
    assert args.serial is False
    serial = parser.parse_args(["backfill", "--source", "all", "--serial"])
    assert serial.serial is True
