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
        },
        horizon=horizon,
    )
    assert kept["next_window_start"] == "2024-06-01"
    assert kept["full_horizon_start"] == "2020-01-01"
    assert apply_full_horizon("yargitay", kept, horizon=horizon) == kept

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
