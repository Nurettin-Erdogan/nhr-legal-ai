"""bulk_seed_fulltext_queue'dan resmi getDokuman çeker. Chunk üretmez."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from ingestion.fulltext_queue import (  # noqa: E402
    CaptchaRequiredError,
    YargitayPortalClient,
    claim_due_ids,
    process_claimed_batch,
    requeue_stale_in_progress,
)
from worker.config import get_worker_settings  # noqa: E402

BATCH_SIZE = 20


def run_shard(shard: int, shards: int) -> None:
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL yok")
    settings = get_worker_settings()
    delay = max(float(settings.yargitay_delay_seconds), 0.4)
    from datetime import date

    client = YargitayPortalClient(
        timeout_seconds=45,
        max_retries=2,
        retry_backoff_seconds=max(1.0, delay),
    )
    today = date.today()
    filters = {
        "arananKelime": "",
        "birimYrgKurulDaire": "",
        "birimYrgHukukDaire": "",
        "birimYrgCezaDaire": "",
        "esasYil": "",
        "esasIlkSiraNo": "",
        "esasSonSiraNo": "",
        "kararYil": "",
        "kararIlkSiraNo": "",
        "kararSonSiraNo": "",
        "baslangicTarihi": today.replace(day=1).strftime("%d.%m.%Y"),
        "bitisTarihi": today.strftime("%d.%m.%Y"),
        "siralama": 3,
        "siralamaDirection": "desc",
        "pageSize": 1,
        "pageNumber": 1,
    }
    try:
        client.begin_detailed_search(filters)
        print(json.dumps({"session": "ok"}, ensure_ascii=False), flush=True)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"session": str(exc)}, ensure_ascii=False), flush=True)
    started = time.perf_counter()
    totals = {"seen": 0, "inserted": 0, "duplicate": 0, "failed": 0, "captcha": 0, "rate_limited": 0}
    with psycopg.connect(url, autocommit=False, row_factory=dict_row) as connection:
        connection.execute("SET statement_timeout = 0")
        stale = requeue_stale_in_progress(connection, minutes=15)
        connection.commit()
        print(json.dumps({"shard": shard, "shards": shards, "stale_requeued": stale}, ensure_ascii=False), flush=True)
        while True:
            ids = claim_due_ids(connection, limit=BATCH_SIZE, shard=shard, shards=shards)
            connection.commit()
            if not ids:
                print(
                    json.dumps(
                        {
                            **totals,
                            "shard": shard,
                            "empty": True,
                            "elapsed_s": round(time.perf_counter() - started, 1),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                time.sleep(5)
                continue
            try:
                batch = process_claimed_batch(
                    connection, client, ids, delay_seconds=delay
                )
            except CaptchaRequiredError as exc:
                totals["captcha"] += 1
                print(
                    json.dumps(
                        {
                            **totals,
                            "shard": shard,
                            "captcha": str(exc),
                            "sleep_s": 45,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                time.sleep(45)
                continue
            except Exception as exc:  # noqa: BLE001
                print(
                    json.dumps(
                        {
                            **totals,
                            "shard": shard,
                            "crash": str(exc),
                            "sleep_s": 10,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                time.sleep(10)
                continue
            for key in totals:
                totals[key] += int(batch.get(key) or 0)
            print(
                json.dumps(
                    {
                        **totals,
                        "shard": shard,
                        "batch": len(ids),
                        "elapsed_s": round(time.perf_counter() - started, 1),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    args = parser.parse_args()
    run_shard(args.shard, args.shards)


if __name__ == "__main__":
    main()
