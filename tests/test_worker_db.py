"""Worker checkpoint, lock ve run kayıtları — gerçek PostgreSQL."""

from __future__ import annotations

import os
from datetime import date
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")

from worker.jobs import run_sync
from worker.locks import JobLockedError, source_job_lock
from worker.models import Checkpoint, SyncRequest
from worker.repository import SyncRepository

DATABASE_URL = os.getenv("NHR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="NHR_TEST_DATABASE_URL tanımlı değil; veritabanı testleri atlandı.",
)


def _has_worker_tables(connection) -> bool:
    row = connection.execute(
        "SELECT to_regclass('public.source_sync_checkpoints') IS NOT NULL AS ok"
    ).fetchone()
    return bool(row[0] if not isinstance(row, dict) else row["ok"])


@pytest.fixture
def connection():
    with psycopg.connect(DATABASE_URL) as conn:
        if not _has_worker_tables(conn):
            pytest.skip("007_ingestion_worker.sql henüz uygulanmadı")
        with conn.transaction():
            yield conn
            raise psycopg.Rollback


def test_checkpoint_save_and_load(connection):
    repo = SyncRepository(connection)
    source = f"yargitay-test-{uuid4().hex[:8]}"
    checkpoint = Checkpoint(
        source_name=source,
        last_page=2,
        last_date_from=date(2026, 1, 1),
        last_date_to=date(2026, 1, 31),
        last_cursor={"page": 2},
        last_external_id="yargitay:1",
        consecutive_failures=0,
        health_state="healthy",
    )
    repo.save_checkpoint(checkpoint)
    loaded = repo.get_checkpoint(source)
    assert loaded.last_page == 2
    assert loaded.last_cursor["page"] == 2
    assert loaded.last_external_id == "yargitay:1"


def test_run_status_transitions_and_counters(connection):
    repo = SyncRepository(connection)
    run = repo.start_run("yargitay", checkpoint_before={"page": 1})
    from worker.models import RunCounters

    counters = RunCounters()
    counters.add("created")
    counters.add("duplicate")
    repo.finish_run(
        run,
        status="partial",
        counters=counters,
        last_error="quarantine",
        checkpoint_after={"page": 2},
    )
    rows = repo.list_runs(source_name="yargitay", limit=5)
    assert any(str(row["id"]) == str(run.id) and row["status"] == "partial" for row in rows)


def test_advisory_lock_blocks_second_session(connection):
    url = DATABASE_URL
    with source_job_lock(connection, "yargitay"):
        with psycopg.connect(url) as other:
            with pytest.raises(JobLockedError):
                with source_job_lock(other, "yargitay"):
                    pass


class _EmptyAdapter:
    source_name = "yargitay"
    last_cursor = {
        "window_from": "2026-01-01",
        "window_to": "2026-01-31",
        "window_complete": True,
        "page": 1,
        "seen_count": 1,
        "stored_count": 1,
        "duplicate_count": 0,
        "failed_count": 0,
        "chamber": "",
    }

    def sync(self, request, *, cursor, connection, dry_run, should_stop):
        yield "created", {"external_id": "yargitay:fixture-1", "requests_made": 1}


def test_run_sync_resume_and_coverage(connection, monkeypatch):
    monkeypatch.setenv("DATABASE_ADMIN_URL", DATABASE_URL)
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    result = run_sync(
        connection,
        SyncRequest(
            source="yargitay",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
            dry_run=True,
            resume=False,
        ),
        adapter=_EmptyAdapter(),
    )
    assert result["status"] in {"success", "partial"}
    assert result["counters"]["records_created"] == 1
