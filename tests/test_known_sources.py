from __future__ import annotations

import os
from uuid import uuid4

import pytest

from worker.known_sources import SKIPPABLE_SQL, skippable_external_ids, skipped_existing

DATABASE_URL = os.getenv("NHR_TEST_DATABASE_URL")


class _KnownConnection:
    def __init__(self, known: set[str]) -> None:
        self.known = set(known)
        self.sql: list[str] = []
        self.params: list[object] = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self.params.append(params)
        wanted = set(params[0]) if params else set()
        hits = [(eid,) for eid in sorted(self.known & wanted)]

        class _Result:
            def fetchall(self_inner):
                return hits

        return _Result()


def test_skippable_sql_requires_ready_current_chunks_and_not_deleted():
    assert "ingest_status = 'ready'" in SKIPPABLE_SQL
    assert "ls.is_current" in SKIPPABLE_SQL
    assert "ls.deleted_at IS NULL" in SKIPPABLE_SQL
    assert "legal_chunks" in SKIPPABLE_SQL


def test_skippable_external_ids_empty_without_connection_or_ids():
    assert skippable_external_ids(None, ["yargitay:1"], lane="backfill") == set()
    assert skippable_external_ids(_KnownConnection({"yargitay:1"}), [], lane="backfill") == set()


def test_skippable_external_ids_empty_on_current_lane():
    connection = _KnownConnection({"yargitay:1"})
    assert skippable_external_ids(connection, ["yargitay:1"], lane="current") == set()
    assert connection.params == []


def test_skippable_external_ids_looks_up_on_backfill_lane():
    connection = _KnownConnection({"yargitay:1", "yargitay:9"})
    assert skippable_external_ids(
        connection, ["yargitay:1", "yargitay:2", ""], lane="backfill"
    ) == {"yargitay:1"}
    assert skipped_existing({"requests_made": 1}, "yargitay:1")["skipped_existing"] is True
    assert "ingest_status = 'ready'" in connection.sql[0]


@pytest.mark.skipif(not DATABASE_URL, reason="NHR_TEST_DATABASE_URL tanımlı değil")
def test_skippable_ids_only_ready_chunked_current_rows():
    psycopg = pytest.importorskip("psycopg")
    token = uuid4().hex[:10]
    ready = f"skip-ready-{token}"
    pending = f"skip-pending-{token}"
    failed = f"skip-failed-{token}"
    chunkless = f"skip-chunkless-{token}"
    deleted = f"skip-deleted-{token}"
    historical = f"skip-old-{token}"
    with psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row) as conn:
        with conn.transaction():
            ids = {
                ready: _insert_source(conn, ready, ingest_status="ready", with_chunk=True),
                pending: _insert_source(conn, pending, ingest_status="pending", with_chunk=True),
                failed: _insert_source(conn, failed, ingest_status="failed", with_chunk=True),
                chunkless: _insert_source(
                    conn, chunkless, ingest_status="ready", with_chunk=False
                ),
                deleted: _insert_source(
                    conn, deleted, ingest_status="ready", with_chunk=True, deleted=True
                ),
                historical: _insert_source(
                    conn, historical, ingest_status="ready", with_chunk=True, is_current=False
                ),
            }
            del ids
            found = skippable_external_ids(
                conn,
                [ready, pending, failed, chunkless, deleted, historical],
                lane="backfill",
            )
            assert found == {ready}
            assert skippable_external_ids(conn, [ready], lane="current") == set()
            raise psycopg.Rollback


def _insert_source(
    connection,
    external_id: str,
    *,
    ingest_status: str,
    with_chunk: bool,
    deleted: bool = False,
    is_current: bool = True,
) -> str:
    source_id = connection.execute(
        """
        INSERT INTO legal_sources (
            source_type, title, external_id, authority, raw_text, ingest_status,
            canonical_source_name, ingestion_method, source_version,
            fetched_at, last_verified_at, is_current, deleted_at
        )
        VALUES (
            'court_decision', %s, %s, 'Yargıtay', %s, %s,
            'Yargıtay Karar Arama', 'test_fixture', '1',
            NOW(), NOW(), %s, CASE WHEN %s THEN NOW() ELSE NULL END
        )
        RETURNING id
        """,
        (
            f"Skip fixture {external_id}",
            external_id,
            f"Skip fixture metni {external_id}",
            ingest_status,
            is_current,
            deleted,
        ),
    ).fetchone()["id"]
    if with_chunk:
        connection.execute(
            "INSERT INTO legal_chunks (legal_source_id, chunk_index, content) VALUES (%s, 0, %s)",
            (source_id, f"Skip chunk {external_id}"),
        )
    return str(source_id)
