"""Worker checkpoint, lock ve run kayıtları — gerçek PostgreSQL."""

from __future__ import annotations

import os
from datetime import date
from uuid import uuid4

import pytest

from worker.jobs import run_sync
from worker.locks import JobLockedError, source_job_lock
from worker.models import Checkpoint, SyncRequest
from worker.repository import SyncRepository

psycopg = pytest.importorskip("psycopg")

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


def test_coverage_counters_accumulate_across_runs(connection):
    repo = SyncRepository(connection)
    source = f"yargitay-cov-{uuid4().hex[:8]}"
    window_from = date(2026, 3, 1)
    window_to = date(2026, 3, 31)

    repo.upsert_coverage(
        source,
        window_from,
        window_to,
        seen_count=10,
        stored_count=8,
        duplicate_count=1,
        failed_count=1,
        complete=False,
    )
    repo.upsert_coverage(
        source,
        window_from,
        window_to,
        seen_count=5,
        stored_count=4,
        duplicate_count=1,
        failed_count=0,
        complete=True,
    )

    row = connection.execute(
        """
        SELECT seen_count, stored_count, duplicate_count, failed_count, complete
        FROM source_coverage_windows
        WHERE source_name = %s AND date_from = %s AND date_to = %s AND chamber = ''
        """,
        (source, window_from, window_to),
    ).fetchone()
    if isinstance(row, dict):
        seen, stored, dup, failed, complete = (
            row["seen_count"],
            row["stored_count"],
            row["duplicate_count"],
            row["failed_count"],
            row["complete"],
        )
    else:
        seen, stored, dup, failed, complete = row
    assert seen == 15
    assert stored == 12
    assert dup == 2
    assert failed == 1
    assert complete is True


def test_last_successful_sync_at_unchanged_on_partial(connection, monkeypatch):
    from datetime import UTC, datetime

    monkeypatch.setenv("DATABASE_ADMIN_URL", DATABASE_URL)
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()

    repo = SyncRepository(connection)
    prior = datetime(2026, 2, 1, tzinfo=UTC)
    checkpoint = Checkpoint(
        source_name="yargitay",
        last_successful_sync_at=prior,
        last_cursor={},
        health_state="healthy",
    )
    repo.save_checkpoint(checkpoint)

    class _PartialAdapter:
        source_name = "yargitay"
        last_cursor = {
            "window_from": "2026-01-01",
            "window_to": "2026-01-31",
            "window_complete": False,
            "page": 1,
            "seen_count": 1,
            "stored_count": 0,
            "duplicate_count": 0,
            "failed_count": 0,
            "chamber": "",
        }

        def sync(self, request, *, cursor, connection, dry_run, should_stop):
            yield "quarantined", {
                "external_id": "yargitay:q",
                "reason": "missing",
                "raw": {},
                "requests_made": 1,
            }

    result = run_sync(
        connection,
        SyncRequest(source="yargitay", dry_run=False, resume=False),
        adapter=_PartialAdapter(),
    )
    assert result["status"] == "partial"
    loaded = repo.get_checkpoint("yargitay")
    assert loaded.last_successful_sync_at == prior
