"""Envanterdeki fulltext-eksik document_id'ler için resumable kuyruk üretir. HTTP yok."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from ingestion.bulk_copy import load_bulk_checkpoint, save_bulk_checkpoint  # noqa: E402

CHECKPOINT = "bulk:fulltext_queue"
OUT = ROOT / "data" / "eval" / "ictihat-inventory" / "queue_report.json"
BUCKETS = 16


def main() -> None:
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL yok")
    with psycopg.connect(url) as connection:
        connection.execute("SET statement_timeout = 0")
        connection.execute("SET work_mem = '256MB'")
        connection.execute("SET synchronous_commit = off")
        print("building existing fulltext id set", flush=True)
        connection.execute(
            """
            CREATE TEMP TABLE existing_fulltext_doc_ids (
              document_id text PRIMARY KEY
            )
            """
        )
        connection.execute(
            """
            INSERT INTO existing_fulltext_doc_ids (document_id)
            SELECT DISTINCT split_part(ls.external_id, ':', 2)
            FROM legal_sources ls
            WHERE ls.is_current AND ls.deleted_at IS NULL
              AND ls.source_type = 'court_decision'
              AND ls.raw_text IS NOT NULL
              AND ls.external_id LIKE ANY (ARRAY['yargitay:%', 'bedesten:%'])
              AND split_part(ls.external_id, ':', 2) <> ''
            ON CONFLICT DO NOTHING
            """
        )
        print("building existing natural-key set", flush=True)
        connection.execute(
            """
            CREATE TEMP TABLE existing_fulltext_natural (
              docket_no text NOT NULL,
              decision_no text NOT NULL,
              PRIMARY KEY (docket_no, decision_no)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO existing_fulltext_natural (docket_no, decision_no)
            SELECT DISTINCT d.docket_no, d.decision_no
            FROM court_decision_details d
            JOIN legal_sources ls ON ls.id = d.legal_source_id
            WHERE ls.is_current AND ls.deleted_at IS NULL
              AND d.is_current
              AND lower(d.court_name) = 'yargıtay'
              AND d.docket_no IS NOT NULL AND d.decision_no IS NOT NULL
              AND ls.raw_text IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )
        connection.execute("ANALYZE existing_fulltext_doc_ids")
        connection.execute("ANALYZE existing_fulltext_natural")
        state = load_bulk_checkpoint(connection, CHECKPOINT)
        done = {int(item) for item in state.get("buckets_done") or []}
        inserted_total = int(state.get("inserted") or 0)
        print(f"resume buckets_done={sorted(done)} inserted={inserted_total}", flush=True)
        for bucket in range(BUCKETS):
            if bucket in done:
                continue
            inserted = connection.execute(
                """
                INSERT INTO bulk_seed_fulltext_queue (document_id, reason, status, next_run_at)
                SELECT
                  inv.document_id,
                  'missing_fulltext',
                  'pending',
                  NOW()
                FROM bulk_seed_inventory inv
                WHERE NOT inv.has_fulltext
                  AND (inv.document_id::bigint %% %s) = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM existing_fulltext_doc_ids e
                    WHERE e.document_id = inv.document_id
                  )
                  AND NOT (
                    inv.docket_no IS NOT NULL
                    AND inv.decision_no IS NOT NULL
                    AND EXISTS (
                      SELECT 1 FROM existing_fulltext_natural n
                      WHERE n.docket_no = inv.docket_no
                        AND n.decision_no = inv.decision_no
                    )
                  )
                ON CONFLICT (document_id) DO NOTHING
                """,
                (BUCKETS, bucket),
            ).rowcount
            inserted_total += int(inserted or 0)
            done.add(bucket)
            save_bulk_checkpoint(
                connection,
                CHECKPOINT,
                {
                    "buckets_done": sorted(done),
                    "inserted": inserted_total,
                    "buckets": BUCKETS,
                },
            )
            connection.commit()
            print(f"bucket {bucket}/{BUCKETS - 1} inserted={inserted} total={inserted_total}", flush=True)
        skipped_has_text = connection.execute(
            "SELECT count(*) FROM bulk_seed_inventory WHERE has_fulltext"
        ).fetchone()[0]
        already_in_db = connection.execute(
            """
            SELECT count(*) FROM bulk_seed_inventory inv
            WHERE NOT inv.has_fulltext
              AND (
                EXISTS (
                  SELECT 1 FROM existing_fulltext_doc_ids e
                  WHERE e.document_id = inv.document_id
                )
                OR (
                  inv.docket_no IS NOT NULL
                  AND inv.decision_no IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM existing_fulltext_natural n
                    WHERE n.docket_no = inv.docket_no
                      AND n.decision_no = inv.decision_no
                  )
                )
              )
            """
        ).fetchone()[0]
        pending = connection.execute(
            "SELECT count(*) FROM bulk_seed_fulltext_queue WHERE status='pending'"
        ).fetchone()[0]
        inventory_n = connection.execute("SELECT count(*) FROM bulk_seed_inventory").fetchone()[0]
        save_bulk_checkpoint(
            connection,
            CHECKPOINT,
            {
                "buckets_done": sorted(done),
                "inserted": inserted_total,
                "pending": int(pending),
                "inventory": int(inventory_n),
                "complete": True,
            },
        )
        connection.commit()
    report = {
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inventory_rows": int(inventory_n),
        "queue_inserted_this_run": inserted_total,
        "queue_pending": int(pending),
        "skipped_inventory_has_fulltext": int(skipped_has_text),
        "skipped_db_already_has_fulltext": int(already_in_db),
        "http_fetches": 0,
        "note": (
            "Kuyruk yalnızca fulltext eksik Bedesten document_id'leridir. "
            "Çekim yok; 429/CAPTCHA bypass yok. Mevcut scraper'lar current/gap-fill olarak kalır."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
