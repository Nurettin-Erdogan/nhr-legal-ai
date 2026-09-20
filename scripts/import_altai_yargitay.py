"""altaidevorg JSONL yıllarını checkpointli bulk_seed olarak yazar."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from ingestion.altai_yargitay import ALTAI_DATASET, CANONICAL_SOURCE_NAME, prepare_altai_row  # noqa: E402
from ingestion.bulk_copy import (  # noqa: E402
    BulkInsertStats,
    insert_pending_seed,
    load_bulk_checkpoint,
    save_bulk_checkpoint,
)
from ingestion.http_download import download_http  # noqa: E402

CHECKPOINT = "bulk:altai_yargitay"
BATCH_ID = "altai-yargitay-full"
YEARS = tuple(range(2015, 2024))
BATCH_ROWS = 5_000
DATA_DIR = ROOT / "data" / "eval" / "altai-yargitay"
HF_JSONL = (
    "https://huggingface.co/datasets/altaidevorg/yargitay-karar-data-raw"
    "/resolve/main/yargitay_data_{year}.jsonl"
)


def merge_stats(total: dict[str, int], stats: BulkInsertStats) -> None:
    for key in (
        "copied",
        "inserted",
        "quarantine",
        "duplicate_batch",
        "official_ready",
        "existing",
        "new_yargitay",
        "new_danistay",
        "oversized",
    ):
        total[key] += getattr(stats, key)


def iter_jsonl(path: Path, *, start_line: int):
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if index < start_line:
                continue
            line = line.strip()
            if not line:
                continue
            yield index + 1, prepare_altai_row(json.loads(line))


def main() -> None:
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL yok")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    totals = {key: 0 for key in (
        "copied", "inserted", "quarantine", "duplicate_batch",
        "official_ready", "existing", "new_yargitay", "new_danistay", "oversized",
    )}
    with psycopg.connect(url, autocommit=False) as connection:
        connection.execute("SET statement_timeout = 0")
        connection.execute("SET synchronous_commit = off")
        state = load_bulk_checkpoint(connection, CHECKPOINT)
        years_done = {int(item) for item in state.get("years_done") or []}
        year = int(state.get("year") or YEARS[0])
        line_no = int(state.get("line") or 0)
        print(f"resume years_done={sorted(years_done)} year={year} line={line_no}")
        for current in YEARS:
            if current in years_done:
                continue
            if current < year:
                continue
            start = line_no if current == year else 0
            dest = DATA_DIR / f"yargitay_data_{current}.jsonl"
            download_http(HF_JSONL.format(year=current), dest)
            batch: list = []
            last_line = start
            print(f"import year={current} from line {start}")
            for last_line, row in iter_jsonl(dest, start_line=start):
                batch.append(row)
                if len(batch) % 1000 == 0 and len(batch) < BATCH_ROWS:
                    print(f"  parsed {len(batch)} year={current} line={last_line}", flush=True)
                if len(batch) >= BATCH_ROWS:
                    stats = insert_pending_seed(
                        connection,
                        batch,
                        batch_id=BATCH_ID,
                        canonical_source_name=CANONICAL_SOURCE_NAME,
                        extra_metadata={"hf_dataset": ALTAI_DATASET, "year": current},
                    )
                    merge_stats(totals, stats)
                    save_bulk_checkpoint(
                        connection,
                        CHECKPOINT,
                        {
                            "years_done": sorted(years_done),
                            "year": current,
                            "line": last_line,
                            "totals": totals,
                        },
                    )
                    connection.commit()
                    print(
                        f"  year {current} line {last_line} inserted={stats.inserted}"
                        f" existing={stats.existing} official_ready={stats.official_ready}"
                        f" quarantine={stats.quarantine}",
                        flush=True,
                    )
                    batch = []
            if batch:
                stats = insert_pending_seed(
                    connection,
                    batch,
                    batch_id=BATCH_ID,
                    canonical_source_name=CANONICAL_SOURCE_NAME,
                    extra_metadata={"hf_dataset": ALTAI_DATASET, "year": current},
                )
                merge_stats(totals, stats)
                connection.commit()
            years_done.add(current)
            year = current
            line_no = 0
            save_bulk_checkpoint(
                connection,
                CHECKPOINT,
                {"years_done": sorted(years_done), "year": current, "line": 0, "totals": totals},
            )
            connection.commit()
            print(f"year {current} complete")
    elapsed = time.perf_counter() - t0
    report = {
        "batch_id": BATCH_ID,
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed, 1),
        **totals,
        "ingest_status": "pending",
        "official_verified": False,
        "chunks": False,
    }
    path = DATA_DIR / "full_import_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
