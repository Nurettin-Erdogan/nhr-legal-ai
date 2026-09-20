"""Bekleyen bulk_seed kararlarını yerelde parçalar. Ağ yok, resmi ready'ye dokunmaz."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from ingestion.bulk_chunk import CHECKPOINT, ZERO_UUID, process_pending_seed_batch  # noqa: E402
from ingestion.bulk_copy import load_bulk_checkpoint, save_bulk_checkpoint  # noqa: E402

BATCH_SIZE = 400


def checkpoint_name(shard: int, shards: int) -> str:
    if shards <= 1:
        return CHECKPOINT
    return f"{CHECKPOINT}:{shard}/{shards}"


def run_shard(shard: int, shards: int) -> None:
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL yok")
    started = time.perf_counter()
    totals = {
        "seen": 0,
        "chunked": 0,
        "skipped_empty": 0,
        "skipped_existing": 0,
        "chunks_written": 0,
    }
    name = checkpoint_name(shard, shards)
    with psycopg.connect(url, autocommit=False, row_factory=dict_row) as connection:
        connection.execute("SET statement_timeout = 0")
        connection.execute("SET synchronous_commit = off")
        connection.execute("SET work_mem = '64MB'")
        state = load_bulk_checkpoint(connection, name)
        after = UUID(str(state.get("last_id") or ZERO_UUID))
        for key in totals:
            totals[key] = int(state.get(key) or 0)
        while True:
            batch = process_pending_seed_batch(
                connection,
                after_id=after,
                batch_size=BATCH_SIZE,
                shard=shard,
                shards=shards,
            )
            totals["seen"] += batch["seen"]
            totals["chunked"] += batch["chunked"]
            totals["skipped_empty"] += batch["skipped_empty"]
            totals["skipped_existing"] += batch["skipped_existing"]
            totals["chunks_written"] += batch["chunks_written"]
            after = UUID(batch["last_id"])
            payload = {
                **totals,
                "last_id": str(after),
                "complete": batch["done"],
                "shard": shard,
                "shards": shards,
            }
            save_bulk_checkpoint(connection, name, payload)
            connection.commit()
            print(json.dumps({**payload, "elapsed_s": round(time.perf_counter() - started, 1)}, ensure_ascii=False), flush=True)
            if batch["done"] or batch["seen"] == 0:
                break


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.shard is None and args.workers > 1:
        workers = []
        for shard in range(args.workers):
            workers.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--shard",
                        str(shard),
                        "--shards",
                        str(args.workers),
                    ],
                    cwd=str(ROOT),
                )
            )
        codes = [proc.wait() for proc in workers]
        if any(code != 0 for code in codes):
            raise SystemExit(max(codes))
        return
    run_shard(args.shard or 0, args.shards)


if __name__ == "__main__":
    main()
