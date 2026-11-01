"""Parquet fulltext eksiğini legal_sources'a pending bulk_seed olarak yazar. HTTP yok."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq
import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from ingestion.bulk_copy import (  # noqa: E402
    BulkInsertStats,
    insert_pending_seed,
    load_bulk_checkpoint,
    save_bulk_checkpoint,
)
from ingestion.hf_700k import jsonable_id  # noqa: E402
from ingestion.ictihat_parquet_fulltext import (  # noqa: E402
    CANONICAL_SOURCE_NAME,
    DATASET,
    IMPORT_TYPE,
    MIN_TEXT_CHARS,
    prepare_parquet_fulltext_row,
    valid_document_id,
)

CHECKPOINT = "bulk:ictihat_parquet_fulltext"
BATCH_ID = "ictihat-parquet-fulltext"
DATA_DIR = ROOT / "data" / "eval" / "ictihat-inventory"
BATCH_ROWS = 2_000
SHARD_COUNT = 99


def _before_sql(connection: psycopg.Connection) -> dict:
    connection.execute("SET work_mem = '512MB'")
    return connection.execute(
        """
        WITH db_ids AS (
          SELECT DISTINCT split_part(ls.external_id, ':', 2) AS document_id,
                 bool_or(ls.raw_text IS NOT NULL AND ls.raw_text <> '') AS has_text
          FROM legal_sources ls
          WHERE ls.deleted_at IS NULL AND ls.is_current
            AND (ls.external_id LIKE 'yargitay:%' OR ls.external_id LIKE 'bedesten:%')
            AND split_part(ls.external_id, ':', 2) <> ''
          GROUP BY 1
        )
        SELECT json_build_object(
          'inventory', (SELECT count(*) FROM bulk_seed_inventory),
          'db_fulltext', (
            SELECT count(*) FROM bulk_seed_inventory inv
            JOIN db_ids d ON d.document_id = inv.document_id WHERE d.has_text
          ),
          'parquet_fulltext', (SELECT count(*) FROM bulk_seed_inventory WHERE has_fulltext),
          'parquet_already_in_db', (
            SELECT count(*) FROM bulk_seed_inventory inv
            JOIN db_ids d ON d.document_id = inv.document_id
            WHERE inv.has_fulltext AND d.has_text
          ),
          'parquet_missing', (
            SELECT count(*) FROM bulk_seed_inventory inv
            WHERE inv.has_fulltext
              AND NOT EXISTS (SELECT 1 FROM db_ids d WHERE d.document_id = inv.document_id AND d.has_text)
          ),
          'parquet_db_empty_text', (
            SELECT count(*) FROM bulk_seed_inventory inv
            JOIN db_ids d ON d.document_id = inv.document_id
            WHERE inv.has_fulltext AND NOT d.has_text
          ),
          'bulk_total', (
            SELECT count(*) FROM legal_sources
            WHERE deleted_at IS NULL AND is_current AND ingestion_method = 'bulk_seed'
          ),
          'bulk_pending', (
            SELECT count(*) FROM legal_sources
            WHERE deleted_at IS NULL AND is_current AND ingestion_method = 'bulk_seed'
              AND ingest_status = 'pending'
          ),
          'bulk_ready', (
            SELECT count(*) FROM legal_sources
            WHERE deleted_at IS NULL AND is_current AND ingestion_method = 'bulk_seed'
              AND ingest_status = 'ready'
          ),
          'bulk_official_verified', (
            SELECT count(*) FROM legal_sources
            WHERE deleted_at IS NULL AND is_current AND ingestion_method = 'bulk_seed'
              AND metadata->>'official_verified' = 'true'
          ),
          'queue_pending', (SELECT count(*) FROM bulk_seed_fulltext_queue WHERE status = 'pending'),
          'bulk_chunks', (
            SELECT count(*) FROM legal_chunks c
            JOIN legal_sources ls ON ls.id = c.legal_source_id
            WHERE ls.ingestion_method = 'bulk_seed'
          ),
          'ready_court', (
            SELECT count(*) FROM legal_sources
            WHERE deleted_at IS NULL AND is_current AND ingest_status = 'ready'
              AND source_type = 'court_decision'
          )
        ) AS payload
        """
    ).fetchone()["payload"]


def load_existing_fulltext_ids(connection: psycopg.Connection) -> set[str]:
    rows = connection.execute(
        """
        SELECT DISTINCT split_part(ls.external_id, ':', 2) AS document_id
        FROM legal_sources ls
        WHERE ls.deleted_at IS NULL AND ls.is_current
          AND (ls.external_id LIKE 'yargitay:%' OR ls.external_id LIKE 'bedesten:%')
          AND ls.raw_text IS NOT NULL AND ls.raw_text <> ''
          AND split_part(ls.external_id, ':', 2) <> ''
        """
    ).fetchall()
    return {row["document_id"] for row in rows}


def load_inventory_fulltext(connection: psycopg.Connection) -> dict[str, dict]:
    rows = connection.execute(
        """
        SELECT document_id, chamber, docket_no, decision_no, decision_date
        FROM bulk_seed_inventory
        WHERE has_fulltext
        """
    ).fetchall()
    return {
        row["document_id"]: {
            "chamber": row["chamber"],
            "docket_no": row["docket_no"],
            "decision_no": row["decision_no"],
            "decision_date": row["decision_date"],
        }
        for row in rows
    }


def iter_shard_rows(path: Path, shard: int, inventory: dict[str, dict]):
    table = pq.read_table(
        path,
        columns=["document_id", "karar_no", "esas_no", "daire", "karar_tarihi", "karar_turu", "text"],
    )
    text = table.column("text")
    lengths = pc.utf8_length(pc.fill_null(text, ""))
    keep = pc.and_(pc.is_valid(text), pc.greater(lengths, MIN_TEXT_CHARS))
    filtered = table.filter(keep)
    ids = filtered.column("document_id").to_pylist()
    esas = filtered.column("esas_no").to_pylist()
    karar = filtered.column("karar_no").to_pylist()
    daire = filtered.column("daire").to_pylist()
    tarih = filtered.column("karar_tarihi").to_pylist()
    turu = filtered.column("karar_turu").to_pylist()
    texts = filtered.column("text").to_pylist()
    for index, document_id in enumerate(ids):
        ident = jsonable_id(document_id)
        yield {
            "document_id": ident,
            "esas_no": esas[index],
            "karar_no": karar[index],
            "daire": daire[index],
            "karar_tarihi": tarih[index],
            "karar_turu": turu[index],
            "text": texts[index],
            "inventory": inventory.get(ident) or {},
            "shard": shard,
        }


def merge_stats(total: dict[str, int], stats: BulkInsertStats) -> None:
    total["inserted"] += stats.inserted
    total["official_ready"] += stats.official_ready
    total["existing"] += stats.existing
    total["duplicate_batch"] += stats.duplicate_batch
    total["quarantine"] += stats.quarantine
    total["copied"] += stats.copied


def main() -> None:
    dry_run = "--apply" not in sys.argv
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL yok")
    t0 = time.perf_counter()
    with psycopg.connect(url, autocommit=False, row_factory=dict_row) as connection:
        connection.execute("SET statement_timeout = 0")
        connection.execute("SET synchronous_commit = off")
        before = _before_sql(connection)
        print("BEFORE " + json.dumps(before, ensure_ascii=False, default=str), flush=True)
        existing_ids = load_existing_fulltext_ids(connection)
        inventory = load_inventory_fulltext(connection)
        connection.commit()
        dry = {
            "scanned": 0,
            "eligible": 0,
            "existing": 0,
            "invalid": 0,
            "failed": 0,
            "official_ready_skip": 0,
            "duplicate": 0,
        }
        shards_with_text: list[int] = []
        for shard in range(SHARD_COUNT):
            path = DATA_DIR / f"train-{shard:05d}-of-{SHARD_COUNT:05d}.parquet"
            if not path.exists():
                continue
            shard_eligible = 0
            for raw in iter_shard_rows(path, shard, inventory):
                dry["scanned"] += 1
                ident = raw["document_id"]
                if not valid_document_id(ident):
                    dry["invalid"] += 1
                    continue
                if ident in existing_ids:
                    dry["existing"] += 1
                    continue
                dry["eligible"] += 1
                shard_eligible += 1
            if shard_eligible:
                shards_with_text.append(shard)
        print("DRY_RUN " + json.dumps({**dry, "shards": shards_with_text}, ensure_ascii=False), flush=True)
        expected_missing = int(before["parquet_missing"])
        if abs(dry["eligible"] - expected_missing) > 50:
            print(
                f"DRY_RUN mismatch eligible={dry['eligible']} sql_missing={expected_missing}",
                flush=True,
            )
            if dry_run:
                return
            raise SystemExit("DRY RUN farkı büyük; import iptal")
        if dry_run:
            print("DRY RUN tamam. Import için --apply", flush=True)
            return

        state = load_bulk_checkpoint(connection, CHECKPOINT)
        shards_done = {int(item) for item in state.get("shards_done") or []}
        totals = {
            "inserted": int(state.get("inserted") or 0),
            "official_ready": int(state.get("official_ready") or 0),
            "existing": int(state.get("existing") or 0),
            "duplicate_batch": int(state.get("duplicate_batch") or 0),
            "quarantine": int(state.get("quarantine") or 0),
            "copied": int(state.get("copied") or 0),
            "failed": int(state.get("failed") or 0),
        }
        extra = {
            "dataset": DATASET,
            "import_type": IMPORT_TYPE,
        }
        for shard in shards_with_text:
            if shard in shards_done:
                continue
            path = DATA_DIR / f"train-{shard:05d}-of-{SHARD_COUNT:05d}.parquet"
            chunk: list = []
            for raw in iter_shard_rows(path, shard, inventory):
                ident = raw["document_id"]
                if not valid_document_id(ident) or ident in existing_ids:
                    continue
                prepared = prepare_parquet_fulltext_row(
                    raw, inventory=raw.get("inventory") or {}, shard=shard
                )
                if prepared is None:
                    totals["failed"] += 1
                    continue
                chunk.append(prepared)
                if len(chunk) >= BATCH_ROWS:
                    stats = insert_pending_seed(
                        connection,
                        chunk,
                        batch_id=BATCH_ID,
                        canonical_source_name=CANONICAL_SOURCE_NAME,
                        extra_metadata=extra,
                    )
                    merge_stats(totals, stats)
                    existing_ids.update(
                        prepared.dataset_id for prepared in chunk if prepared.quarantine_code is None
                    )
                    connection.commit()
                    chunk = []
            if chunk:
                stats = insert_pending_seed(
                    connection,
                    chunk,
                    batch_id=BATCH_ID,
                    canonical_source_name=CANONICAL_SOURCE_NAME,
                    extra_metadata=extra,
                )
                merge_stats(totals, stats)
                existing_ids.update(
                    prepared.dataset_id for prepared in chunk if prepared.quarantine_code is None
                )
                connection.commit()
            shards_done.add(shard)
            save_bulk_checkpoint(
                connection,
                CHECKPOINT,
                {
                    "shards_done": sorted(shards_done),
                    "last_shard": shard,
                    **totals,
                    "dry": dry,
                },
            )
            connection.commit()
            print(f"shard {shard} inserted_total={totals['inserted']}", flush=True)
        after = _before_sql(connection)
        connection.commit()
    elapsed = time.perf_counter() - t0
    report = {
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed, 1),
        "before": before,
        "dry": dry,
        "totals": totals,
        "after": after,
        "http_requests": 0,
        "chunks_created": False,
        "queue_rebuilt": False,
    }
    (DATA_DIR / "parquet_fulltext_import_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print("AFTER " + json.dumps(after, ensure_ascii=False, default=str), flush=True)
    print("TOTALS " + json.dumps(totals, ensure_ascii=False), flush=True)
    print(f"duration_s={elapsed:.1f}", flush=True)


if __name__ == "__main__":
    main()
