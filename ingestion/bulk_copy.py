"""Üçüncü taraf karar tohumu: PostgreSQL COPY + staging. Chunk/embed yok."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from ingestion.hf_700k import (
    CANONICAL_SOURCE_NAME,
    INGESTION_METHOD,
    PROVENANCE,
    PreparedRow,
)

_STAGING_SQL = """
CREATE TEMP TABLE bulk_seed_staging (
  batch_row bigserial PRIMARY KEY,
  dataset_id text NOT NULL,
  source_code text NOT NULL,
  court_name text NOT NULL,
  chamber text NOT NULL DEFAULT '',
  docket_no text NOT NULL DEFAULT '',
  decision_no text NOT NULL DEFAULT '',
  decision_date date,
  external_id text NOT NULL DEFAULT '',
  title text NOT NULL DEFAULT '',
  raw_text text NOT NULL DEFAULT '',
  content_hash text NOT NULL DEFAULT '',
  source_url text,
  oversized boolean NOT NULL DEFAULT false,
  quarantine_code text,
  quarantine_reason text,
  metadata_json text NOT NULL DEFAULT '{}',
  skip_reason text,
  source_id uuid
)
"""

_COPY_SQL = """
COPY bulk_seed_staging (
  dataset_id, source_code, court_name, chamber, docket_no, decision_no,
  decision_date, external_id, title, raw_text, content_hash, source_url,
  oversized, quarantine_code, quarantine_reason, metadata_json
) FROM STDIN
"""

_CLASSIFY = (
    """
    UPDATE bulk_seed_staging
    SET skip_reason = 'duplicate_external_id_batch'
    WHERE quarantine_code IS NULL AND skip_reason IS NULL AND external_id <> ''
      AND batch_row NOT IN (
        SELECT min(batch_row) FROM bulk_seed_staging
        WHERE quarantine_code IS NULL AND external_id <> ''
        GROUP BY external_id
      )
    """,
    """
    UPDATE bulk_seed_staging
    SET skip_reason = 'duplicate_natural_batch'
    WHERE quarantine_code IS NULL AND skip_reason IS NULL
      AND docket_no <> '' AND decision_no <> ''
      AND batch_row NOT IN (
        SELECT min(batch_row) FROM bulk_seed_staging
        WHERE quarantine_code IS NULL AND skip_reason IS NULL
          AND docket_no <> '' AND decision_no <> ''
        GROUP BY lower(court_name), lower(chamber), docket_no, decision_no
      )
    """,
    """
    UPDATE bulk_seed_staging
    SET skip_reason = 'duplicate_hash_batch'
    WHERE quarantine_code IS NULL AND skip_reason IS NULL AND content_hash <> ''
      AND batch_row NOT IN (
        SELECT min(batch_row) FROM bulk_seed_staging
        WHERE quarantine_code IS NULL AND skip_reason IS NULL AND content_hash <> ''
        GROUP BY content_hash
      )
    """,
    """
    UPDATE bulk_seed_staging AS s
    SET skip_reason = CASE
      WHEN ls.ingest_status = 'ready' THEN 'official_ready_external_id'
      ELSE 'existing_external_id'
    END
    FROM legal_sources ls
    WHERE s.quarantine_code IS NULL AND s.skip_reason IS NULL AND s.external_id <> ''
      AND ls.source_type = 'court_decision' AND ls.is_current AND ls.deleted_at IS NULL
      AND ls.external_id = s.external_id
    """,
    """
    UPDATE bulk_seed_staging AS s
    SET skip_reason = CASE
      WHEN ls.ingest_status = 'ready' THEN 'official_ready_natural_key'
      ELSE 'existing_natural_key'
    END
    FROM court_decision_details d
    JOIN legal_sources ls ON ls.id = d.legal_source_id
    WHERE s.quarantine_code IS NULL AND s.skip_reason IS NULL
      AND s.docket_no <> '' AND s.decision_no <> ''
      AND ls.is_current AND ls.deleted_at IS NULL AND ls.source_type = 'court_decision'
      AND d.docket_no = s.docket_no
      AND d.decision_no = s.decision_no
      AND lower(d.court_name) = lower(s.court_name)
      AND lower(COALESCE(d.chamber, '')) = lower(COALESCE(s.chamber, ''))
    """,
    """
    UPDATE bulk_seed_staging AS s
    SET skip_reason = 'existing_content_hash'
    FROM legal_sources ls
    WHERE s.quarantine_code IS NULL AND s.skip_reason IS NULL AND s.content_hash <> ''
      AND ls.is_current AND ls.deleted_at IS NULL
      AND ls.content_hash = s.content_hash
    """,
    """
    UPDATE bulk_seed_staging
    SET source_id = gen_random_uuid()
    WHERE quarantine_code IS NULL AND skip_reason IS NULL
    """,
)


@dataclass(frozen=True, slots=True)
class BulkInsertStats:
    copied: int = 0
    inserted: int = 0
    quarantine: int = 0
    duplicate_batch: int = 0
    official_ready: int = 0
    existing: int = 0
    new_yargitay: int = 0
    new_danistay: int = 0
    oversized: int = 0
    skip_reasons: dict[str, int] | None = None
    quarantine_codes: dict[str, int] | None = None


def copy_prepared_rows(
    cursor: psycopg.Cursor,
    rows: Iterable[PreparedRow],
    *,
    batch_id: str,
    canonical_source_name: str = CANONICAL_SOURCE_NAME,
    extra_metadata: dict[str, Any] | None = None,
) -> int:
    copied = 0
    with cursor.copy(_COPY_SQL) as copy:
        for row in rows:
            metadata = dict(row.metadata)
            metadata["poc_batch"] = batch_id
            metadata["provenance"] = PROVENANCE
            metadata["official_verified"] = False
            if extra_metadata:
                metadata.update(extra_metadata)
            copy.write_row(
                (
                    row.dataset_id,
                    row.source_code,
                    row.court_name,
                    row.chamber,
                    row.docket_no,
                    row.decision_no,
                    row.decision_date,
                    row.external_id,
                    row.title,
                    row.raw_text,
                    row.content_hash,
                    row.source_url,
                    row.oversized,
                    row.quarantine_code,
                    row.quarantine_reason,
                    json.dumps(metadata, ensure_ascii=False),
                )
            )
            copied += 1
    return copied


def insert_pending_seed(
    connection: psycopg.Connection,
    rows: Iterable[PreparedRow],
    *,
    batch_id: str,
    canonical_source_name: str = CANONICAL_SOURCE_NAME,
    extra_metadata: dict[str, Any] | None = None,
) -> BulkInsertStats:
    """Staging COPY + INSERT. Mevcut current satırları güncellemez; chunk yazmaz."""
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("DROP TABLE IF EXISTS bulk_seed_staging")
        cursor.execute(_STAGING_SQL)
        copied = copy_prepared_rows(
            cursor,
            rows,
            batch_id=batch_id,
            extra_metadata=extra_metadata,
        )
        print(f"    copied {copied} rows", flush=True)
        if copied == 0:
            return BulkInsertStats()
        for index, statement in enumerate(_CLASSIFY, start=1):
            started = time.perf_counter()
            cursor.execute(statement)
            print(
                f"    classify {index}/{len(_CLASSIFY)} {(time.perf_counter() - started):.1f}s",
                flush=True,
            )
        started = time.perf_counter()
        inserted = cursor.execute(
            f"""
            INSERT INTO legal_sources (
              id, source_type, title, source_url, external_id, authority, jurisdiction,
              raw_text, metadata, published_at, content_hash, ingest_status, last_ingested_at,
              canonical_source_name, official_source_url, ingestion_method, fetched_at,
              last_verified_at, source_version, revision, is_current
            )
            SELECT
              source_id, 'court_decision', title, source_url, external_id, court_name, 'TR',
              raw_text, metadata_json::jsonb, decision_date, content_hash, 'pending', NOW(),
              %s, NULL, %s, NOW(), NOW(), %s || dataset_id, 1, TRUE
            FROM bulk_seed_staging
            WHERE source_id IS NOT NULL
            """,
            (canonical_source_name, INGESTION_METHOD, f"{batch_id}:"),
        ).rowcount
        print(f"    insert legal_sources {inserted} {(time.perf_counter() - started):.1f}s", flush=True)
        cursor.execute(
            """
            INSERT INTO court_decision_details (
              legal_source_id, court_name, chamber, docket_no, decision_no, decision_date
            )
            SELECT source_id, court_name, NULLIF(chamber, ''), NULLIF(docket_no, ''),
                   NULLIF(decision_no, ''), decision_date
            FROM bulk_seed_staging
            WHERE source_id IS NOT NULL
            """
        )
        cursor.execute(
            """
            INSERT INTO legal_source_quarantine (
              source_adapter, external_id, reason_code, reason, raw_payload, content_hash
            )
            SELECT
              %s::text, NULLIF(external_id, ''), quarantine_code, quarantine_reason,
              jsonb_strip_nulls(jsonb_build_object(
                'poc_batch', %s::text, 'dataset_id', dataset_id, 'source_code', source_code,
                'court_name', court_name, 'esasNo', NULLIF(docket_no, ''),
                'kararNo', NULLIF(decision_no, ''), 'text_len', length(raw_text)
              )),
              NULLIF(content_hash, '')
            FROM bulk_seed_staging
            WHERE quarantine_code IS NOT NULL
            """,
            (INGESTION_METHOD, batch_id),
        )
        counts = cursor.execute(
            """
            SELECT
              count(*) FILTER (WHERE quarantine_code IS NOT NULL) AS quarantine,
              count(*) FILTER (WHERE skip_reason LIKE 'duplicate_%') AS duplicate_batch,
              count(*) FILTER (WHERE skip_reason LIKE 'official_ready_%') AS official_ready,
              count(*) FILTER (WHERE skip_reason LIKE 'existing_%') AS existing,
              count(*) FILTER (WHERE source_id IS NOT NULL AND court_name='Yargıtay') AS new_yargitay,
              count(*) FILTER (WHERE source_id IS NOT NULL AND court_name='Danıştay') AS new_danistay,
              count(*) FILTER (WHERE oversized) AS oversized
            FROM bulk_seed_staging
            """
        ).fetchone()
        skips = cursor.execute(
            """
            SELECT skip_reason, count(*) AS n FROM bulk_seed_staging
            WHERE skip_reason IS NOT NULL GROUP BY 1
            """
        ).fetchall()
        qcodes = cursor.execute(
            """
            SELECT quarantine_code, count(*) AS n FROM bulk_seed_staging
            WHERE quarantine_code IS NOT NULL GROUP BY 1
            """
        ).fetchall()
    return BulkInsertStats(
        copied=copied,
        inserted=int(inserted or 0),
        quarantine=int(counts["quarantine"]),
        duplicate_batch=int(counts["duplicate_batch"]),
        official_ready=int(counts["official_ready"]),
        existing=int(counts["existing"]),
        new_yargitay=int(counts["new_yargitay"]),
        new_danistay=int(counts["new_danistay"]),
        oversized=int(counts["oversized"]),
        skip_reasons={row["skip_reason"]: int(row["n"]) for row in skips},
        quarantine_codes={row["quarantine_code"]: int(row["n"]) for row in qcodes},
    )


def save_bulk_checkpoint(
    connection: psycopg.Connection,
    source_name: str,
    cursor_payload: dict[str, Any],
    *,
    error: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO source_sync_checkpoints (
          source_name, last_cursor, last_attempt_at, last_successful_sync_at,
          last_error, consecutive_failures, health_state, updated_at
        )
        VALUES (%s, %s::jsonb, NOW(), CASE WHEN %s THEN NULL ELSE NOW() END,
                %s, CASE WHEN %s THEN 1 ELSE 0 END,
                CASE WHEN %s THEN 'degraded' ELSE 'healthy' END, NOW())
        ON CONFLICT (source_name) DO UPDATE SET
          last_cursor = EXCLUDED.last_cursor,
          last_attempt_at = NOW(),
          last_successful_sync_at = CASE
            WHEN %s THEN source_sync_checkpoints.last_successful_sync_at
            ELSE NOW()
          END,
          last_error = EXCLUDED.last_error,
          consecutive_failures = CASE
            WHEN %s THEN source_sync_checkpoints.consecutive_failures + 1
            ELSE 0
          END,
          health_state = EXCLUDED.health_state,
          updated_at = NOW()
        """,
        (
            source_name,
            json.dumps(cursor_payload, ensure_ascii=False),
            error is not None,
            error,
            error is not None,
            error is not None,
            error is not None,
            error is not None,
        ),
    )


def load_bulk_checkpoint(connection: psycopg.Connection, source_name: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT last_cursor FROM source_sync_checkpoints WHERE source_name = %s",
        (source_name,),
    ).fetchone()
    if not row:
        return {}
    payload = row[0] if not isinstance(row, dict) else row["last_cursor"]
    return dict(payload or {})
