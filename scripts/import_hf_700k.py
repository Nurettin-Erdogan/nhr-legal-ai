"""Checkpointli 700k HuggingFace full import. Official ready overwrite yok; chunk yok."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from ingestion.bulk_copy import (  # noqa: E402
    BulkInsertStats,
    insert_pending_seed,
    load_bulk_checkpoint,
    save_bulk_checkpoint,
)
from ingestion.hf_700k import (  # noqa: E402
    CANONICAL_SOURCE_NAME,
    HF_DATASET,
    jsonable_id,
    prepare_row,
)
from ingestion.http_download import download_http  # noqa: E402

CHECKPOINT = "bulk:hf700k"
BATCH_ID = "hf700k-full"
SHARD_COUNT = 9
HF_PARQUET = (
    "https://huggingface.co/datasets/erdem-erdem/Turkish-Law-Documents-700k-clustered"
    "/resolve/main/data/train-{index:05d}-of-00009.parquet"
)
DATA_DIR = ROOT / "data" / "eval" / "700k-quality"
REPORT_PATH = DATA_DIR / "full_import_report.json"


def iter_shard(path: Path):
    parquet = pq.ParquetFile(path)
    for index in range(parquet.num_row_groups):
        for row in parquet.read_row_group(index).to_pylist():
            cleaned = {}
            for key, value in row.items():
                if key.startswith("orig-e5") or key.startswith("tr-e5"):
                    continue
                if hasattr(value, "item"):
                    value = value.item()
                cleaned[key] = value
            cleaned["id"] = jsonable_id(cleaned.get("id"))
            yield prepare_row(cleaned)


def merge_stats(total: dict[str, int], stats: BulkInsertStats) -> None:
    total["copied"] += stats.copied
    total["inserted"] += stats.inserted
    total["quarantine"] += stats.quarantine
    total["duplicate_batch"] += stats.duplicate_batch
    total["official_ready"] += stats.official_ready
    total["existing"] += stats.existing
    total["new_yargitay"] += stats.new_yargitay
    total["new_danistay"] += stats.new_danistay
    total["oversized"] += stats.oversized


def main() -> None:
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL yok")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    totals = {
        "copied": 0,
        "inserted": 0,
        "quarantine": 0,
        "duplicate_batch": 0,
        "official_ready": 0,
        "existing": 0,
        "new_yargitay": 0,
        "new_danistay": 0,
        "oversized": 0,
    }
    shards_done: list[int] = []
    with psycopg.connect(url, autocommit=False) as connection:
        connection.execute("SET statement_timeout = 0")
        connection.execute("SET synchronous_commit = off")
        cursor_state = load_bulk_checkpoint(connection, CHECKPOINT)
        done = {int(item) for item in cursor_state.get("shards_done") or []}
        print(f"resume shards_done={sorted(done)}")
        for shard in range(SHARD_COUNT):
            if shard in done:
                print(f"skip shard {shard} (checkpoint)")
                continue
            dest = DATA_DIR / f"train-{shard:05d}-of-00009.parquet"
            download_http(HF_PARQUET.format(index=shard), dest)
            print(f"import shard {shard}")
            stats = insert_pending_seed(
                connection,
                iter_shard(dest),
                batch_id=BATCH_ID,
                canonical_source_name=CANONICAL_SOURCE_NAME,
                extra_metadata={"hf_dataset": HF_DATASET, "hf_shard": shard},
            )
            merge_stats(totals, stats)
            done.add(shard)
            save_bulk_checkpoint(
                connection,
                CHECKPOINT,
                {"shards_done": sorted(done), "last_shard": shard, "totals": totals},
            )
            connection.commit()
            shards_done.append(shard)
            print(
                f"shard {shard} inserted={stats.inserted} skip_official={stats.official_ready} "
                f"existing={stats.existing} quarantine={stats.quarantine}"
            )
    elapsed = time.perf_counter() - t0
    report = {
        "batch_id": BATCH_ID,
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed, 1),
        "records_per_sec": round(totals["copied"] / elapsed, 1) if elapsed else 0,
        "shards_imported_this_run": shards_done,
        **totals,
        "ingest_status": "pending",
        "official_verified": False,
        "chunks": False,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("wrote", REPORT_PATH)


if __name__ == "__main__":
    main()
