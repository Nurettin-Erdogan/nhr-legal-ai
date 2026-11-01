"""Uyuşmazlık Mahkemesi kararlarını (kararlar.uyusmazlik.gov.tr, PDF) çekip saklar.

Yeniden başlatılabilir/tekrarlanabilir: veritabanında olan kararlar atlanır.
  python scripts/collect_uyusmazlik.py                 # tüm sayfalar (yeniden eskiye)
  python scripts/collect_uyusmazlik.py --mode recent   # yalnız üstteki sayfalar (art arda 3 tam-mevcut sayfada durur)
  python scripts/collect_uyusmazlik.py --limit 5       # deneme
"""

from __future__ import annotations

import argparse
import json
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
from ingestion.uyusmazlik.parser import build_doc, external_id_for  # noqa: E402
from ingestion.uyusmazlik.portal import UyusmazlikClient, UyusmazlikError  # noqa: E402

PROFILE = SourceProfile(
    authority="Uyuşmazlık Mahkemesi",
    canonical_source_name="Uyuşmazlık Mahkemesi Karar Arama",
    ingestion_method="uyusmazlik_public_pdf",
    chunk_source="uyusmazlik",
)
STATE = ROOT / "data" / "campaign" / "uyusmazlik-progress.json"
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
    parser.add_argument("--limit", type=int, default=0, help="Deneme: toplam bu kadar yeni karar")
    args = parser.parse_args()
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL yok")
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    client = UyusmazlikClient(delay_seconds=args.delay)
    created = updated = failed = 0
    complete_pages = 0
    errors = 0
    with psycopg.connect(url, autocommit=True) as connection:
        while True:
            try:
                rows, current = client.first_page()
                total_pages = client.goto("Page$Last")[1]
                rows, current = client.first_page()
                break
            except UyusmazlikError as exc:
                errors += 1
                wait = 900 if "429" in str(exc) else min(600, 30 * errors)
                print(f"{time.strftime('%H:%M:%S')} başlangıç hatası ({exc}); {wait} sn", flush=True)
                time.sleep(wait)
        page = 1
        while not STOP:
            ids = [external_id_for(row) for row in rows]
            have = existing_external_ids(connection, ids)
            fresh = [row for row, external_id in zip(rows, ids, strict=True) if external_id not in have]
            for row in fresh:
                if STOP:
                    break
                try:
                    result = upsert_official_doc(connection, build_doc(row, client.fetch_pdf(row.pdf_path)), PROFILE)
                except UyusmazlikError as exc:
                    failed += 1
                    print(f"{time.strftime('%H:%M:%S')} atlandı {row.esas_no}/{row.karar_no}: {exc}", flush=True)
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
                    {"page": page, "total_pages": total_pages, "created": created, "failed": failed,
                     "updated_at": datetime.now().isoformat(timespec="seconds")}
                ),
                encoding="utf-8",
            )
            print(f"{time.strftime('%H:%M:%S')} sayfa {page}/{total_pages} | yeni={created:,} hata={failed:,}", flush=True)
            if STOP or (args.mode == "recent" and complete_pages >= 3) or (total_pages and page >= total_pages):
                break
            try:
                rows, current = client.goto(f"Page${page + 1}")
            except UyusmazlikError as exc:
                errors += 1
                wait = 900 if "429" in str(exc) else min(600, 30 * errors)
                print(f"{time.strftime('%H:%M:%S')} sayfa geçiş hatası ({exc}); {wait} sn", flush=True)
                time.sleep(wait)
                try:
                    client.first_page()  # oturumu yenile ve aynı sayfaya zincirle yeniden git
                    for step in range(2, page + 2):
                        rows, current = client.goto(f"Page${step}")
                except UyusmazlikError:
                    continue
            if current is not None and current != page + 1:
                print(f"{time.strftime('%H:%M:%S')} beklenmeyen sayfa {current} (istenen {page + 1}); duruyorum", flush=True)
                break
            page += 1
    print(f"BİTTİ: yeni={created:,} güncellenen={updated:,} hata={failed:,}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
