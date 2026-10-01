from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from worker.models import Checkpoint, IngestionRun, RunCounters, RunStatus


def _as_checkpoint(row: dict[str, Any]) -> Checkpoint:
    return Checkpoint(
        source_name=row["source_name"],
        last_successful_sync_at=row.get("last_successful_sync_at"),
        last_attempt_at=row.get("last_attempt_at"),
        last_cursor=dict(row.get("last_cursor") or {}),
        last_page=row.get("last_page"),
        last_date_from=row.get("last_date_from"),
        last_date_to=row.get("last_date_to"),
        last_external_id=row.get("last_external_id"),
        last_error=row.get("last_error"),
        consecutive_failures=row.get("consecutive_failures") or 0,
        next_run_at=row.get("next_run_at"),
        health_state=row.get("health_state") or "healthy",
        health_detail=row.get("health_detail"),
        updated_at=row.get("updated_at"),
    )


class SyncRepository:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def get_checkpoint(self, source_name: str) -> Checkpoint:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM source_sync_checkpoints WHERE source_name = %s",
                (source_name,),
            )
            row = cursor.fetchone()
        if row:
            return _as_checkpoint(row)
        checkpoint = Checkpoint(source_name=source_name)
        self.save_checkpoint(checkpoint)
        return checkpoint

    def cancel_stale_runs(self, *, older_than_hours: float = 2) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE source_sync_runs
                SET status = 'cancelled',
                    completed_at = COALESCE(completed_at, NOW()),
                    error_message = COALESCE(error_message, 'stale running row')
                WHERE status = 'running'
                  AND started_at < NOW() - (%s * INTERVAL '1 hour')
                """,
                (older_than_hours,),
            )
            return int(cursor.rowcount or 0)

    def list_checkpoints(self) -> list[Checkpoint]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM source_sync_checkpoints ORDER BY source_name"
            )
            return [_as_checkpoint(row) for row in cursor.fetchall()]

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO source_sync_checkpoints (
                    source_name, last_successful_sync_at, last_attempt_at,
                    last_cursor, last_page, last_date_from, last_date_to,
                    last_external_id, last_error, consecutive_failures,
                    next_run_at, health_state, health_detail, updated_at
                )
                VALUES (
                    %(source_name)s, %(last_successful_sync_at)s, %(last_attempt_at)s,
                    %(last_cursor)s, %(last_page)s, %(last_date_from)s, %(last_date_to)s,
                    %(last_external_id)s, %(last_error)s, %(consecutive_failures)s,
                    %(next_run_at)s, %(health_state)s, %(health_detail)s, NOW()
                )
                ON CONFLICT (source_name) DO UPDATE SET
                    last_successful_sync_at = EXCLUDED.last_successful_sync_at,
                    last_attempt_at = EXCLUDED.last_attempt_at,
                    last_cursor = EXCLUDED.last_cursor,
                    last_page = EXCLUDED.last_page,
                    last_date_from = EXCLUDED.last_date_from,
                    last_date_to = EXCLUDED.last_date_to,
                    last_external_id = EXCLUDED.last_external_id,
                    last_error = EXCLUDED.last_error,
                    consecutive_failures = EXCLUDED.consecutive_failures,
                    next_run_at = EXCLUDED.next_run_at,
                    health_state = EXCLUDED.health_state,
                    health_detail = EXCLUDED.health_detail,
                    updated_at = NOW()
                """,
                {
                    "source_name": checkpoint.source_name,
                    "last_successful_sync_at": checkpoint.last_successful_sync_at,
                    "last_attempt_at": checkpoint.last_attempt_at,
                    "last_cursor": Jsonb(checkpoint.last_cursor),
                    "last_page": checkpoint.last_page,
                    "last_date_from": checkpoint.last_date_from,
                    "last_date_to": checkpoint.last_date_to,
                    "last_external_id": checkpoint.last_external_id,
                    "last_error": checkpoint.last_error,
                    "consecutive_failures": checkpoint.consecutive_failures,
                    "next_run_at": checkpoint.next_run_at,
                    "health_state": checkpoint.health_state,
                    "health_detail": checkpoint.health_detail,
                },
            )

    def start_run(
        self,
        source_name: str,
        *,
        checkpoint_before: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> IngestionRun:
        run_id = uuid4()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO source_sync_runs (
                    id, source_adapter, status, started_at, checkpoint_before, metadata
                )
                VALUES (%s, %s, 'running', NOW(), %s, %s)
                """,
                (str(run_id), source_name, Jsonb(checkpoint_before), Jsonb(metadata or {})),
            )
        return IngestionRun(
            id=run_id,
            source_name=source_name,
            status="running",
            started_at=datetime.now(UTC),
            checkpoint_before=checkpoint_before,
            metadata=metadata or {},
        )

    def finish_run(
        self,
        run: IngestionRun,
        *,
        status: RunStatus,
        counters: RunCounters,
        last_error: str | None = None,
        checkpoint_after: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        merged = dict(run.metadata)
        if metadata:
            merged.update(metadata)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE source_sync_runs SET
                    status = %(status)s,
                    completed_at = NOW(),
                    processed_count = %(seen)s,
                    created_count = %(created)s,
                    updated_count = %(updated)s,
                    unchanged_count = %(unchanged)s,
                    duplicate_count = %(duplicate)s,
                    failed_count = %(failed)s,
                    records_quarantined = %(quarantined)s,
                    requests_made = %(requests)s,
                    retry_count = %(retries)s,
                    error_message = %(error)s,
                    checkpoint_after = %(checkpoint_after)s,
                    last_cursor = %(last_cursor)s,
                    metadata = %(metadata)s
                WHERE id = %(id)s
                """,
                {
                    "status": status,
                    "seen": counters.records_seen,
                    "created": counters.records_created,
                    "updated": counters.records_updated,
                    "unchanged": counters.records_unchanged,
                    "duplicate": counters.records_duplicate,
                    "failed": counters.records_failed,
                    "quarantined": counters.records_quarantined,
                    "requests": counters.requests_made,
                    "retries": counters.retry_count,
                    "error": last_error,
                    "checkpoint_after": Jsonb(checkpoint_after or {}),
                    "last_cursor": Jsonb((checkpoint_after or {}).get("last_cursor") or {}),
                    "metadata": Jsonb(merged),
                    "id": str(run.id),
                },
            )

    def list_runs(self, *, source_name: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        sql = """
            SELECT id, source_adapter, status, started_at, completed_at,
                   processed_count, created_count, updated_count, unchanged_count,
                   duplicate_count, failed_count, records_quarantined,
                   requests_made, retry_count, error_message, metadata
            FROM source_sync_runs
        """
        params: list[Any] = []
        if source_name:
            sql += " WHERE source_adapter = %s"
            params.append(source_name)
        sql += " ORDER BY started_at DESC LIMIT %s"
        params.append(max(1, min(limit, 100)))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())

    def list_coverage(
        self, *, source_name: str | None = None, limit: int = 80
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT source_name, date_from, date_to, chamber, expected_count,
                   seen_count, stored_count, duplicate_count, failed_count,
                   complete, completed_at, updated_at
            FROM source_coverage_windows
        """
        params: list[Any] = []
        if source_name:
            sql += " WHERE source_name = %s"
            params.append(source_name)
        sql += " ORDER BY source_name, date_from DESC, chamber LIMIT %s"
        params.append(max(1, min(limit, 500)))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())

    def quarantine(
        self,
        source_name: str,
        *,
        external_id: str | None,
        reason_code: str,
        reason: str,
        raw_payload: dict[str, Any],
        content_hash: str | None = None,
    ) -> None:
        with self.connection.cursor() as cursor:
            if external_id:
                # Rescans revisit the same unavailable records every cycle.
                cursor.execute(
                    """
                    UPDATE legal_source_quarantine
                    SET reason = %s, raw_payload = %s, content_hash = %s,
                        quarantined_at = NOW()
                    WHERE source_adapter = %s AND external_id = %s
                      AND reason_code = %s AND resolved_at IS NULL
                    """,
                    (
                        reason,
                        Jsonb(raw_payload),
                        content_hash,
                        source_name,
                        external_id,
                        reason_code,
                    ),
                )
                if cursor.rowcount:
                    return
            cursor.execute(
                """
                INSERT INTO legal_source_quarantine (
                    source_adapter, external_id, reason_code, reason,
                    raw_payload, content_hash
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    source_name,
                    external_id,
                    reason_code,
                    reason,
                    Jsonb(raw_payload),
                    content_hash,
                ),
            )

    def upsert_coverage(
        self,
        source_name: str,
        date_from: date,
        date_to: date,
        *,
        chamber: str = "",
        expected_count: int | None = None,
        seen_count: int = 0,
        stored_count: int = 0,
        duplicate_count: int = 0,
        failed_count: int = 0,
        complete: bool = False,
    ) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO source_coverage_windows (
                    source_name, date_from, date_to, chamber, expected_count,
                    seen_count, stored_count, duplicate_count, failed_count,
                    complete, completed_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s THEN NOW() ELSE NULL END, NOW()
                )
                ON CONFLICT (source_name, date_from, date_to, chamber) DO UPDATE SET
                    expected_count = COALESCE(EXCLUDED.expected_count, source_coverage_windows.expected_count),
                    seen_count = source_coverage_windows.seen_count + EXCLUDED.seen_count,
                    stored_count = source_coverage_windows.stored_count + EXCLUDED.stored_count,
                    duplicate_count = source_coverage_windows.duplicate_count + EXCLUDED.duplicate_count,
                    failed_count = source_coverage_windows.failed_count + EXCLUDED.failed_count,
                    complete = source_coverage_windows.complete OR EXCLUDED.complete,
                    completed_at = CASE
                        WHEN source_coverage_windows.complete OR EXCLUDED.complete
                        THEN COALESCE(source_coverage_windows.completed_at, NOW())
                        ELSE NULL
                    END,
                    updated_at = NOW()
                """,
                (
                    source_name,
                    date_from,
                    date_to,
                    chamber,
                    expected_count,
                    seen_count,
                    stored_count,
                    duplicate_count,
                    failed_count,
                    complete,
                    complete,
                ),
            )
