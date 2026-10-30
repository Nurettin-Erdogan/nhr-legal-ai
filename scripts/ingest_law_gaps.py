"""Sunucuların çektiği eksik mevzuat maddelerini (data/campaign/law_scan/fetch*.jsonl) veritabanına aktarır.

  python scripts/ingest_law_gaps.py [--apply]

Kanun düzeyindeki künye ve doğrulama bilgisi (MBS/Resmî Gazete bayrakları) aynı kanunun mevcut, doğrulanmış maddesinden alınır
(doğrulama kanun başına bir kez yapılır, madde başına değil: docs/ingestion-mevzuat.md). Madde metni portaldan sunucuda çekilmiştir;
PC portala istek atmaz. `--apply` verilmezse yalnız özet yazar. Doğrulanmış kardeş madde yoksa kanun atlanır.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from ingestion.mevzuat.parser import record_from_article  # noqa: E402
from ingestion.mevzuat.store import ingest_legislation  # noqa: E402

SIBLING = """
SELECT ls.source_url, ls.metadata, d.law_name, d.law_no, d.official_gazette_no, d.official_gazette_date, d.version_date
FROM legislation_details d JOIN legal_sources ls ON ls.id = d.legal_source_id
WHERE ls.metadata->>'mevzuat_id' = %s AND ls.deleted_at IS NULL AND ls.ingest_status = 'ready' AND ls.is_current
  AND ls.metadata->>'verified_against_gazette' = 'true' AND ls.metadata->>'verified_against_mbs' = 'true'
LIMIT 1
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    rows = []
    for path in sorted((ROOT / "data/campaign/law_scan").glob("fetch*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if "html_b64" in item:
                rows.append(item)
    by_law: dict[str, list[dict]] = defaultdict(list)
    for item in rows:
        by_law[item["mevzuat_id"]].append(item)
    records, skipped = [], []
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], row_factory=dict_row) as connection:
        for mevzuat_id, items in by_law.items():
            sibling = connection.execute(SIBLING, (mevzuat_id,)).fetchone()
            if sibling is None:
                skipped.append((mevzuat_id, len(items)))
                continue
            meta = sibling["metadata"]
            document = {"mevzuatNo": sibling["law_no"], "mevzuatAdi": sibling["law_name"], "mevzuatId": mevzuat_id, "url": sibling["source_url"],
                        "mevzuatTur": meta.get("mevzuat_tur"), "mevzuatTertip": meta.get("mevzuat_tertip"),
                        "resmiGazeteSayisi": sibling["official_gazette_no"],
                        "resmiGazeteTarihi": str(sibling["official_gazette_date"]) if sibling["official_gazette_date"] else None,
                        "guncellemeTarihi": str(sibling["version_date"]) if sibling["version_date"] else None}
            existing = {r["article_no"] for r in connection.execute(
                "SELECT d.article_no FROM legislation_details d JOIN legal_sources ls ON ls.id = d.legal_source_id "
                "WHERE d.law_no = %s AND ls.deleted_at IS NULL AND ls.is_current", (sibling["law_no"],))}
            for item in items:
                if item["article_no"] in existing:  # aynı kanun numarasıyla başka belge zaten bu maddeyi taşıyor: sürüm zincirini bozma
                    continue
                html = base64.b64decode(item["html_b64"]).decode("utf-8", errors="replace")
                record = record_from_article(document=document, article={"maddeNo": item["article_no"], "maddeId": item["madde_id"]},
                                             article_html=html, scraped_at=datetime.now(UTC))
                record = replace(record, metadata={**meta, "madde_id": item["madde_id"], "gap_fill": "2026-10-24"})
                records.append(record)
        from collections import Counter
        print(dict(Counter(r.law_no for r in records)))
        print(f"çekilen madde {len(rows)} | kanun {len(by_law)} | aktarılacak {len(records)} | atlanan kanun {skipped}")
        if records:
            sample = records[0]
            print(sample.external_id, sample.law_name, "|", sample.raw_text[:160].replace("\n", " "))
        if args.apply and records:
            with psycopg.connect(os.environ["DATABASE_ADMIN_URL"]) as plain:
                print(ingest_legislation(plain, records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
