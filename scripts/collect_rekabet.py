"""Rekabet Kurulu kararlarını (rekabet.gov.tr, PDF) çekip saklar.

Yeniden başlatılabilir/tekrarlanabilir: veritabanında olan kararlar atlanır.
  python scripts/collect_rekabet.py                 # tüm sayfalar (yeniden eskiye)
  python scripts/collect_rekabet.py --mode recent   # üstteki sayfalar (art arda 3 tam-mevcut sayfada durur)
  python scripts/collect_rekabet.py --limit 5       # deneme
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from ingestion.official_docs import SourceProfile, existing_external_ids, upsert_official_doc  # noqa: E402
from ingestion.rekabet.parser import build_doc  # noqa: E402
from ingestion.rekabet.portal import PAGE_SIZE, RekabetClient, RekabetError  # noqa: E402

PROFILE = SourceProfile(
    authority="Rekabet Kurumu",
    canonical_source_name="Rekabet Kurumu Kurul Kararları",
    ingestion_method="rekabet_public_pdf",
    chunk_source="rekabet",
)
STATE = ROOT / "data" / "campaign" / "rekabet-progress.json"
STOP = False


def _handle_stop(signum: int, _frame: object) -> None:
    global STOP
    STOP = True
    print(f"durdurma sinyali ({signum}); mevcut karardan sonra çıkılıyor", flush=True)


def main() -> int:
    global STOP
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["full", "recent"], default="full")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--from-page", type=int, default=1, help="Bu sayfadan başla (paralel işçiler için)")
    parser.add_argument("--to-page", type=int, default=0, help="Bu sayfada dur (0 = son sayfa)")
    parser.add_argument("--limit", type=int, default=0, help="Deneme: toplam bu kadar yeni karar")
    args = parser.parse_args()
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL yok")
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    client = RekabetClient(delay_seconds=args.delay)
    created = updated = failed = errors = complete_pages = 0
    page, total_pages = max(1, args.from_page), None
    with psycopg.connect(url, autocommit=True) as connection:
        while not STOP and (total_pages is None or page <= (min(total_pages, args.to_page) if args.to_page else total_pages)):
            try:
                rows, total = client.list_page(page)
            except RekabetError as exc:
                errors += 1
                wait = 900 if "429" in str(exc) else min(600, 30 * errors)
                print(f"{time.strftime('%H:%M:%S')} liste hatası ({exc}); {wait} sn", flush=True)
                time.sleep(wait)
                continue
            errors = 0
            total_pages = math.ceil(total / PAGE_SIZE)
            ids = [f"rekabet:{row.karar_id}" for row in rows]
            have = existing_external_ids(connection, ids)
            fresh = [row for row, external_id in zip(rows, ids, strict=True) if external_id not in have]
            for row in fresh:
                if STOP:
                    break
                try:
                    result = upsert_official_doc(connection, build_doc(row, client.fetch_pdf(row.karar_id)), PROFILE)
                except RekabetError as exc:
                    failed += 1
                    print(f"{time.strftime('%H:%M:%S')} atlandı {row.karar_sayisi}: {exc}", flush=True)
                    if "429" in str(exc):
                        time.sleep(900)
                    continue
                created += result.status == "created"
                updated += result.status != "created"
                if args.limit and created >= args.limit:
                    STOP = True
                    break
            complete_pages = complete_pages + 1 if not fresh else 0
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(
                json.dumps(
                    {"page": page, "total_pages": total_pages, "total": total, "created": created, "failed": failed,
                     "updated_at": datetime.now().isoformat(timespec="seconds")}
                ),
                encoding="utf-8",
            )
            print(f"{time.strftime('%H:%M:%S')} sayfa {page}/{total_pages} | yeni={created:,} hata={failed:,}", flush=True)
            if args.mode == "recent" and complete_pages >= 3:
                break
            if not rows:
                break
            page += 1
    print(f"BİTTİ: yeni={created:,} güncellenen={updated:,} hata={failed:,}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
