"""muhammedturan 9.8M document_id envanterini staging tabloya alır. HTTP yok."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from ingestion.bulk_copy import load_bulk_checkpoint, save_bulk_checkpoint  # noqa: E402
from ingestion.hf_700k import parse_case_no, parse_date_field, jsonable_id  # noqa: E402
from ingestion.http_download import download_http  # noqa: E402

CHECKPOINT = "bulk:ictihat_inventory"
DATASET = "muhammedturan/turk-ictihat-kararlari-fulltext"
SHARD_COUNT = 99
HF_PARQUET = (
    "https://huggingface.co/datasets/muhammedturan/turk-ictihat-kararlari-fulltext"
    "/resolve/main/data/train-{index:05d}-of-00099.parquet"
)
DATA_DIR = ROOT / "data" / "eval" / "ictihat-inventory"


def valid_document_id(value: str) -> bool:
    return value.isdigit() and int(value) > 0


def main() -> None:
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL yok")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    copied = 0
    with psycopg.connect(url, autocommit=False) as connection:
        connection.execute("SET statement_timeout = 0")
        connection.execute("SET synchronous_commit = off")
        state = load_bulk_checkpoint(connection, CHECKPOINT)
        done = {int(item) for item in state.get("shards_done") or []}
        print(f"resume shards_done={sorted(done)[:8]}... n={len(done)}")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TEMP TABLE inv_staging (
                  document_id text,
                  chamber text,
                  docket_no text,
                  decision_no text,
                  decision_date date,
                  has_fulltext boolean,
                  text_length int,
                  metadata_json text
                )
                """
            )
            for shard in range(SHARD_COUNT):
                if shard in done:
                    continue
                dest = DATA_DIR / f"train-{shard:05d}-of-00099.parquet"
                download_http(HF_PARQUET.format(index=shard), dest)
                table = pq.read_table(
                    dest,
                    columns=[
                        "document_id",
                        "karar_no",
                        "esas_no",
                        "daire",
                        "karar_tarihi",
                        "text",
                    ],
                )
                text_col = table.column("text")
                lengths = pc.utf8_length(pc.fill_null(text_col, ""))
                has_text = pc.and_(pc.is_valid(text_col), pc.greater(lengths, 80))
                cursor.execute("TRUNCATE inv_staging")
                with cursor.copy(
                    """
                    COPY inv_staging (
                      document_id, chamber, docket_no, decision_no, decision_date,
                      has_fulltext, text_length, metadata_json
                    ) FROM STDIN
                    """
                ) as copy:
                    ids = table.column("document_id").to_pylist()
                    karar = table.column("karar_no").to_pylist()
                    esas = table.column("esas_no").to_pylist()
                    daire = table.column("daire").to_pylist()
                    tarih = table.column("karar_tarihi").to_pylist()
                    has_list = has_text.to_pylist()
                    len_list = lengths.to_pylist()
                    for index, document_id in enumerate(ids):
                        ident = jsonable_id(document_id)
                        if not valid_document_id(ident):
                            continue
                        copy.write_row(
                            (
                                ident,
                                str(daire[index] or ""),
                                parse_case_no(esas[index]) or "",
                                parse_case_no(karar[index]) or "",
                                parse_date_field(tarih[index]),
                                bool(has_list[index]),
                                int(len_list[index] or 0),
                                json.dumps({"shard": shard, "hf_dataset": DATASET}, ensure_ascii=False),
                            )
                        )
                inserted = cursor.execute(
                    """
                    INSERT INTO bulk_seed_inventory (
                      document_id, source_dataset, court_hint, chamber, docket_no,
                      decision_no, decision_date, has_fulltext, text_length, metadata
                    )
                    SELECT DISTINCT ON (document_id)
                      document_id, %s, 'Yargıtay', NULLIF(chamber, ''),
                      NULLIF(docket_no, ''), NULLIF(decision_no, ''), decision_date,
                      has_fulltext, text_length, metadata_json::jsonb
                    FROM inv_staging
                    WHERE document_id <> ''
                    ORDER BY document_id, has_fulltext DESC, text_length DESC
                    ON CONFLICT (document_id) DO UPDATE SET
                      chamber = COALESCE(EXCLUDED.chamber, bulk_seed_inventory.chamber),
                      docket_no = COALESCE(EXCLUDED.docket_no, bulk_seed_inventory.docket_no),
                      decision_no = COALESCE(EXCLUDED.decision_no, bulk_seed_inventory.decision_no),
                      decision_date = COALESCE(EXCLUDED.decision_date, bulk_seed_inventory.decision_date),
                      has_fulltext = bulk_seed_inventory.has_fulltext OR EXCLUDED.has_fulltext,
                      text_length = GREATEST(bulk_seed_inventory.text_length, EXCLUDED.text_length),
                      metadata = bulk_seed_inventory.metadata || EXCLUDED.metadata,
                      ingested_at = NOW()
                    """,
                    (DATASET,),
                ).rowcount
                copied += int(inserted or 0)
                done.add(shard)
                save_bulk_checkpoint(
                    connection,
                    CHECKPOINT,
                    {"shards_done": sorted(done), "last_shard": shard, "upserted": copied},
                )
                connection.commit()
                print(f"shard {shard} upserted~={inserted} total_ops={copied}")
                cursor.execute("TRUNCATE inv_staging")
    report = {
        "dataset": DATASET,
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.perf_counter() - t0, 1),
        "upsert_operations": copied,
        "http_fetches": 0,
    }
    path = DATA_DIR / "inventory_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
