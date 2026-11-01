"""100k HuggingFace 700k PoC import. Production satırlarını güncellemez; chunk/embed yok."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from ingestion.hf_700k import (  # noqa: E402
    CANONICAL_SOURCE_NAME,
    HF_DATASET,
    INGESTION_METHOD,
    PROVENANCE,
    PreparedRow,
    jsonable_id,
    prepare_row,
)

TARGET = 100_000
YARGITAY_TARGET = 90_400
DANISTAY_TARGET = 9_600
FULL_CORPUS_ROWS = 702_295
POC_BATCH = "hf700k-100k-20260918"
HF_PARQUET = (
    "https://huggingface.co/datasets/erdem-erdem/Turkish-Law-Documents-700k-clustered"
    "/resolve/main/data/train-{index:05d}-of-00009.parquet"
)
DATA_DIR = ROOT / "data" / "eval" / "700k-quality"
REPORT_PATH = DATA_DIR / "poc_100k_report.json"
USER_AGENT = "nhr-legal-ai-eval/0.1 (poc-import; no embed)"

_STAGING_SQL = """
CREATE TEMP TABLE hf_poc_staging (
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
COPY hf_poc_staging (
  dataset_id, source_code, court_name, chamber, docket_no, decision_no,
  decision_date, external_id, title, raw_text, content_hash, source_url,
  oversized, quarantine_code, quarantine_reason, metadata_json
) FROM STDIN
"""

_CLASSIFY_SQL = """
UPDATE hf_poc_staging
SET skip_reason = 'duplicate_external_id_batch'
WHERE quarantine_code IS NULL
  AND skip_reason IS NULL
  AND external_id <> ''
  AND batch_row NOT IN (
    SELECT min(batch_row) FROM hf_poc_staging
    WHERE quarantine_code IS NULL AND external_id <> ''
    GROUP BY external_id
  );

UPDATE hf_poc_staging
SET skip_reason = 'duplicate_natural_batch'
WHERE quarantine_code IS NULL
  AND skip_reason IS NULL
  AND docket_no <> '' AND decision_no <> ''
  AND batch_row NOT IN (
    SELECT min(batch_row) FROM hf_poc_staging
    WHERE quarantine_code IS NULL AND skip_reason IS NULL
      AND docket_no <> '' AND decision_no <> ''
    GROUP BY lower(court_name), lower(chamber), docket_no, decision_no
  );

UPDATE hf_poc_staging
SET skip_reason = 'duplicate_hash_batch'
WHERE quarantine_code IS NULL
  AND skip_reason IS NULL
  AND content_hash <> ''
  AND batch_row NOT IN (
    SELECT min(batch_row) FROM hf_poc_staging
    WHERE quarantine_code IS NULL AND skip_reason IS NULL AND content_hash <> ''
    GROUP BY content_hash
  );

UPDATE hf_poc_staging AS s
SET skip_reason = 'official_external_id'
WHERE s.quarantine_code IS NULL
  AND s.skip_reason IS NULL
  AND s.external_id <> ''
  AND EXISTS (
    SELECT 1 FROM legal_sources ls
    WHERE ls.source_type = 'court_decision'
      AND ls.is_current
      AND ls.deleted_at IS NULL
      AND ls.external_id = s.external_id
  );

UPDATE hf_poc_staging AS s
SET skip_reason = 'official_natural_key'
WHERE s.quarantine_code IS NULL
  AND s.skip_reason IS NULL
  AND s.docket_no <> '' AND s.decision_no <> ''
  AND EXISTS (
    SELECT 1
    FROM court_decision_details d
    JOIN legal_sources ls ON ls.id = d.legal_source_id
    WHERE ls.is_current AND ls.deleted_at IS NULL
      AND ls.source_type = 'court_decision'
      AND lower(d.court_name) = lower(s.court_name)
      AND d.docket_no = s.docket_no
      AND d.decision_no = s.decision_no
  );

UPDATE hf_poc_staging AS s
SET skip_reason = 'official_content_hash'
WHERE s.quarantine_code IS NULL
  AND s.skip_reason IS NULL
  AND s.content_hash <> ''
  AND EXISTS (
    SELECT 1 FROM legal_sources ls
    WHERE ls.is_current AND ls.deleted_at IS NULL
      AND ls.content_hash = s.content_hash
  );

UPDATE hf_poc_staging
SET source_id = gen_random_uuid()
WHERE quarantine_code IS NULL AND skip_reason IS NULL;
"""

_INSERT_SOURCES_SQL = f"""
INSERT INTO legal_sources (
  id, source_type, title, source_url, external_id, authority, jurisdiction,
  raw_text, metadata, published_at, content_hash, ingest_status, last_ingested_at,
  canonical_source_name, official_source_url, ingestion_method, fetched_at,
  last_verified_at, source_version, revision, is_current
)
SELECT
  source_id,
  'court_decision',
  title,
  source_url,
  external_id,
  court_name,
  'TR',
  raw_text,
  metadata_json::jsonb,
  decision_date,
  content_hash,
  'pending',
  NOW(),
  '{CANONICAL_SOURCE_NAME}',
  NULL,
  '{INGESTION_METHOD}',
  NOW(),
  NOW(),
  'hf-700k:' || dataset_id,
  1,
  TRUE
FROM hf_poc_staging
WHERE source_id IS NOT NULL
"""

_INSERT_DETAILS_SQL = """
INSERT INTO court_decision_details (
  legal_source_id, court_name, chamber, docket_no, decision_no, decision_date
)
SELECT
  source_id,
  court_name,
  NULLIF(chamber, ''),
  NULLIF(docket_no, ''),
  NULLIF(decision_no, ''),
  decision_date
FROM hf_poc_staging
WHERE source_id IS NOT NULL
"""

_INSERT_REVISIONS_SQL = f"""
INSERT INTO legal_source_revisions (
  legal_source_id, revision, source_version, content_hash, raw_text, metadata, provenance
)
SELECT
  source_id,
  1,
  'hf-700k:' || dataset_id,
  content_hash,
  raw_text,
  metadata_json::jsonb,
  jsonb_build_object(
    'provenance', '{PROVENANCE}',
    'ingestion_method', '{INGESTION_METHOD}',
    'hf_dataset', '{HF_DATASET}',
    'official_verified', false,
    'poc_batch', '{POC_BATCH}'
  )
FROM hf_poc_staging
WHERE source_id IS NOT NULL
"""

_INSERT_QUARANTINE_SQL = f"""
INSERT INTO legal_source_quarantine (
  source_adapter, external_id, reason_code, reason, raw_payload, content_hash
)
SELECT
  '{INGESTION_METHOD}',
  NULLIF(external_id, ''),
  quarantine_code,
  quarantine_reason,
  jsonb_strip_nulls(jsonb_build_object(
    'poc_batch', '{POC_BATCH}',
    'dataset_id', dataset_id,
    'source_code', source_code,
    'court_name', court_name,
    'esasNo', NULLIF(docket_no, ''),
    'kararNo', NULLIF(decision_no, ''),
    'text_len', length(raw_text)
  )),
  NULLIF(content_hash, '')
FROM hf_poc_staging
WHERE quarantine_code IS NOT NULL
"""


def download_http(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.stat().st_size if dest.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            mode = "ab" if existing and response.status == 206 else "wb"
            if response.status == 200:
                mode = "wb"
            print(f"download {dest.name} status={response.status} resume={existing}")
            with dest.open(mode) as handle:
                written = dest.stat().st_size if mode == "ab" else 0
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    handle.write(chunk)
                    written += len(chunk)
                    if written % (20 * 1024 * 1024) < 256 * 1024:
                        print(f"  {dest.name} {written / (1024 * 1024):.1f} MB")
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and dest.exists() and dest.stat().st_size > 0:
            return dest
        raise
    print(f"saved {dest} {dest.stat().st_size / (1024 * 1024):.1f} MB")
    return dest


def iter_parquet(path: Path):
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    for index in range(parquet.num_row_groups):
        for row in parquet.read_row_group(index).to_pylist():
            cleaned = {}
            for key, value in row.items():
                if key in {
                    "orig-e5_hdbscan_cluster_id",
                    "orig-e5_knn_cluster_id",
                    "tr-e5_hdbscan_cluster_id",
                    "tr-e5_knn_cluster_id",
                }:
                    continue
                if hasattr(value, "item"):
                    value = value.item()
                cleaned[key] = value
            cleaned["id"] = jsonable_id(cleaned.get("id"))
            yield cleaned


def collect_rows() -> list[PreparedRow]:
    shard0 = download_http(HF_PARQUET.format(index=0), DATA_DIR / "train-00000-of-00009.parquet")
    shard1 = download_http(HF_PARQUET.format(index=1), DATA_DIR / "train-00001-of-00009.parquet")
    shard8 = download_http(HF_PARQUET.format(index=8), DATA_DIR / "train-00008-of-00009.parquet")
    yargitay: list[PreparedRow] = []
    danistay: list[PreparedRow] = []
    for path, want_y, want_d in (
        (shard0, YARGITAY_TARGET, 0),
        (shard1, YARGITAY_TARGET, 0),
        (shard8, YARGITAY_TARGET, DANISTAY_TARGET),
    ):
        if len(yargitay) >= want_y and len(danistay) >= want_d:
            continue
        print(f"reading {path.name} y={len(yargitay)} d={len(danistay)}")
        for raw in iter_parquet(path):
            source = str(raw.get("source") or "")
            if source.startswith("ygty") and len(yargitay) < YARGITAY_TARGET:
                yargitay.append(prepare_row(raw))
            elif source.startswith("dnsy") and len(danistay) < DANISTAY_TARGET:
                danistay.append(prepare_row(raw))
            if len(yargitay) >= YARGITAY_TARGET and len(danistay) >= DANISTAY_TARGET:
                break
        if len(yargitay) >= YARGITAY_TARGET and len(danistay) >= DANISTAY_TARGET:
            break
    rows = yargitay[:YARGITAY_TARGET] + danistay[:DANISTAY_TARGET]
    print(f"prepared {len(rows)} yargitay={len(yargitay)} danistay={len(danistay)}")
    return rows[:TARGET]


def copy_staging(cursor: psycopg.Cursor, rows: list[PreparedRow]) -> None:
    with cursor.copy(_COPY_SQL) as copy:
        for index, row in enumerate(rows, start=1):
            metadata = dict(row.metadata)
            metadata["poc_batch"] = POC_BATCH
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
            if index % 10000 == 0:
                print(f"copied {index}")


def relation_bytes(cursor: psycopg.Cursor, names: tuple[str, ...]) -> dict[str, int]:
    sizes = {}
    for name in names:
        sizes[name] = int(
            cursor.execute("SELECT pg_total_relation_size(%s) AS n", (name,)).fetchone()["n"]
        )
    sizes["database"] = int(
        cursor.execute("SELECT pg_database_size(current_database()) AS n").fetchone()["n"]
    )
    return sizes


def quality_sample(cursor: psycopg.Cursor) -> list[dict]:
    rows = cursor.execute(
        """
        SELECT ls.external_id, ls.ingest_status, ls.ingestion_method,
               ls.metadata->>'provenance' AS provenance,
               ls.metadata->>'official_verified' AS official_verified,
               ls.metadata ? 'orig-e5_hdbscan_cluster_id' AS has_cluster,
               d.court_name, d.chamber, d.docket_no, d.decision_no, d.decision_date,
               length(ls.raw_text) AS text_len,
               left(ls.raw_text, 180) AS head,
               EXISTS (
                 SELECT 1 FROM legal_chunks c WHERE c.legal_source_id = ls.id
               ) AS has_chunk
        FROM legal_sources ls
        JOIN court_decision_details d ON d.legal_source_id = ls.id
        WHERE ls.ingestion_method = %s
          AND ls.metadata->>'poc_batch' = %s
        ORDER BY random()
        LIMIT 20
        """,
        (INGESTION_METHOD, POC_BATCH),
    ).fetchall()
    return [dict(row) for row in rows]


def main() -> None:
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL yok")
    t0 = time.perf_counter()
    rows = collect_rows()
    t1 = time.perf_counter()
    with psycopg.connect(url, autocommit=False) as connection:
        connection.execute("SET statement_timeout = 0")
        connection.execute("SET synchronous_commit = off")
        with connection.cursor(row_factory=dict_row) as cursor:
            before = relation_bytes(
                cursor,
                ("legal_sources", "court_decision_details", "legal_source_revisions", "legal_source_quarantine", "legal_chunks"),
            )
            official_before = cursor.execute(
                """
                SELECT
                  count(*) FILTER (WHERE coalesce(d.court_name, ls.authority)='Yargıtay') AS yargitay,
                  count(*) FILTER (WHERE coalesce(d.court_name, ls.authority)='Danıştay') AS danistay
                FROM legal_sources ls
                LEFT JOIN court_decision_details d ON d.legal_source_id = ls.id
                WHERE ls.source_type='court_decision' AND ls.is_current AND ls.deleted_at IS NULL
                  AND ls.ingest_status='ready'
                """
            ).fetchone()
            cursor.execute(_STAGING_SQL)
            print("COPY staging...")
            copy_staging(cursor, rows)
            print("classify...")
            for statement in _CLASSIFY_SQL.strip().split(";"):
                sql = statement.strip()
                if sql:
                    cursor.execute(sql)
            print("insert sources/details/revisions/quarantine...")
            inserted = cursor.execute(_INSERT_SOURCES_SQL).rowcount
            cursor.execute(_INSERT_DETAILS_SQL)
            cursor.execute(_INSERT_REVISIONS_SQL)
            quarantined = cursor.execute(_INSERT_QUARANTINE_SQL).rowcount
            print(f"quarantine rows inserted: {quarantined}")
            counts = cursor.execute(
                """
                SELECT
                  count(*) FILTER (WHERE quarantine_code IS NOT NULL) AS quarantine,
                  count(*) FILTER (WHERE skip_reason LIKE 'duplicate_%') AS duplicate_batch,
                  count(*) FILTER (WHERE skip_reason LIKE 'official_%') AS official_match,
                  count(*) FILTER (WHERE skip_reason = 'official_external_id') AS official_external_id,
                  count(*) FILTER (WHERE skip_reason = 'official_natural_key') AS official_natural_key,
                  count(*) FILTER (WHERE skip_reason = 'official_content_hash') AS official_content_hash,
                  count(*) FILTER (WHERE skip_reason = 'duplicate_external_id_batch') AS dup_ext,
                  count(*) FILTER (WHERE skip_reason = 'duplicate_natural_batch') AS dup_nat,
                  count(*) FILTER (WHERE skip_reason = 'duplicate_hash_batch') AS dup_hash,
                  count(*) FILTER (WHERE source_id IS NOT NULL AND court_name='Yargıtay') AS new_yargitay,
                  count(*) FILTER (WHERE source_id IS NOT NULL AND court_name='Danıştay') AS new_danistay,
                  count(*) FILTER (WHERE oversized) AS oversized,
                  count(*) FILTER (WHERE source_id IS NOT NULL) AS insertable
                FROM hf_poc_staging
                """
            ).fetchone()
            quarantine_codes = cursor.execute(
                """
                SELECT quarantine_code, count(*) AS count
                FROM hf_poc_staging
                WHERE quarantine_code IS NOT NULL
                GROUP BY 1 ORDER BY 2 DESC
                """
            ).fetchall()
            ready_changed = cursor.execute(
                """
                SELECT count(*) AS n FROM legal_sources
                WHERE ingestion_method = %s AND ingest_status = 'ready'
                  AND metadata->>'poc_batch' = %s
                """,
                (INGESTION_METHOD, POC_BATCH),
            ).fetchone()["n"]
            chunks_created = cursor.execute(
                """
                SELECT count(*) AS n FROM legal_chunks c
                JOIN legal_sources ls ON ls.id = c.legal_source_id
                WHERE ls.metadata->>'poc_batch' = %s
                """,
                (POC_BATCH,),
            ).fetchone()["n"]
            sample = quality_sample(cursor)
            after = relation_bytes(
                cursor,
                ("legal_sources", "court_decision_details", "legal_source_revisions", "legal_source_quarantine", "legal_chunks"),
            )
            cursor.execute(
                """
                INSERT INTO source_sync_runs (
                  source_adapter, filters, status, processed_count, created_count,
                  duplicate_count, failed_count, completed_at, metadata
                )
                VALUES (
                  %s, %s::jsonb, 'completed', %s, %s, %s, %s, NOW(), %s::jsonb
                )
                """,
                (
                    INGESTION_METHOD,
                    json.dumps({"poc_batch": POC_BATCH, "limit": TARGET}),
                    len(rows),
                    inserted,
                    int(counts["duplicate_batch"]) + int(counts["official_match"]),
                    int(counts["quarantine"]),
                    json.dumps({"official_verified": False, "chunks": False}),
                ),
            )
        connection.commit()
    t2 = time.perf_counter()
    elapsed = t2 - t0
    insert_elapsed = t2 - t1
    records_per_sec = len(rows) / elapsed if elapsed else 0
    insert_per_sec = inserted / insert_elapsed if insert_elapsed and inserted else 0
    growth = after["database"] - before["database"]
    full_hours = (FULL_CORPUS_ROWS / max(records_per_sec, 1)) / 3600
    report = {
        "poc_batch": POC_BATCH,
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prepared": len(rows),
        "elapsed_seconds": round(elapsed, 1),
        "prepare_seconds": round(t1 - t0, 1),
        "db_seconds": round(insert_elapsed, 1),
        "records_per_sec": round(records_per_sec, 1),
        "inserted_per_sec": round(insert_per_sec, 1),
        "inserted": inserted,
        "new_yargitay": int(counts["new_yargitay"]),
        "new_danistay": int(counts["new_danistay"]),
        "duplicate_batch": int(counts["duplicate_batch"]),
        "duplicate_external_id_batch": int(counts["dup_ext"]),
        "duplicate_natural_batch": int(counts["dup_nat"]),
        "duplicate_hash_batch": int(counts["dup_hash"]),
        "official_match": int(counts["official_match"]),
        "official_external_id": int(counts["official_external_id"]),
        "official_natural_key": int(counts["official_natural_key"]),
        "official_content_hash": int(counts["official_content_hash"]),
        "quarantine": int(counts["quarantine"]),
        "quarantine_codes": {row["quarantine_code"]: int(row["count"]) for row in quarantine_codes},
        "oversized_imported_no_chunk": int(counts["oversized"]),
        "ready_seed_rows": int(ready_changed),
        "chunks_created": int(chunks_created),
        "official_ready_before": {
            "yargitay": official_before["yargitay"],
            "danistay": official_before["danistay"],
        },
        "db_bytes_before": before,
        "db_bytes_after": after,
        "db_growth_bytes": growth,
        "db_growth_mb": round(growth / (1024 * 1024), 1),
        "estimated_700k_hours": round(full_hours, 2),
        "quality_sample": sample,
        "rollback": {
            "possible": True,
            "sql": (
                "BEGIN;\n"
                f"DELETE FROM legal_source_revisions WHERE legal_source_id IN ("
                f"SELECT id FROM legal_sources WHERE ingestion_method='{INGESTION_METHOD}' "
                f"AND metadata->>'poc_batch'='{POC_BATCH}');\n"
                f"DELETE FROM legal_sources WHERE ingestion_method='{INGESTION_METHOD}' "
                f"AND metadata->>'poc_batch'='{POC_BATCH}';\n"
                f"DELETE FROM legal_source_quarantine WHERE source_adapter='{INGESTION_METHOD}' "
                f"AND raw_payload->>'poc_batch'='{POC_BATCH}';\n"
                "COMMIT;"
            ),
        },
        "guards": {
            "no_overwrite": True,
            "ingest_status": "pending",
            "provenance": PROVENANCE,
            "official_verified": False,
            "chunks": False,
            "embeddings": False,
        },
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "quality_sample"}, ensure_ascii=False, indent=2, default=str))
    print("quality_sample", json.dumps(sample, ensure_ascii=False, indent=2, default=str))
    print("wrote", REPORT_PATH)


if __name__ == "__main__":
    main()
