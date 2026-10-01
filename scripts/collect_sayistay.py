"""Sayıştay yargı kararlarını (Genel Kurul, Temyiz Kurulu, Daire) resmî siteden çekip saklar.

Yeniden başlatılabilir ve tekrar çalıştırılabilir: veritabanında olan kararlar atlanır, yalnız
listeyi gezer. CAPTCHA/429 aşılmaz; 429'da bekler, art arda hatada uzun mola verir.

  python scripts/collect_sayistay.py                  # üç tür, tümü
  python scripts/collect_sayistay.py --kind genelkurul --limit 5   # deneme
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
from ingestion.sayistay.parser import build_doc  # noqa: E402
from ingestion.sayistay.portal import KINDS, SayistayClient, SayistayError  # noqa: E402

PROFILE = SourceProfile(
    authority="Sayıştay",
    canonical_source_name="Sayıştay Yargı Kararları",
    ingestion_method="sayistay_public_datatables_html",
    chunk_source="sayistay",
)
STATE = ROOT / "data" / "campaign" / "sayistay-progress.json"
STOP = False


def _handle_stop(signum: int, _frame: object) -> None:
    global STOP
    STOP = True
    print(f"durdurma sinyali ({signum}); mevcut karardan sonra çıkılıyor", flush=True)


def _save(progress: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    global STOP
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kind", choices=sorted(KINDS), action="append", help="Varsayılan: genelkurul, temyiz, daire")
    parser.add_argument("--delay", type=float, default=1.5, help="İstekler arası saniye")
    parser.add_argument("--limit", type=int, default=0, help="Deneme: toplam bu kadar yeni karar")
    args = parser.parse_args()
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL yok")
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    client = SayistayClient(delay_seconds=args.delay)
    progress: dict = {}
    created = updated = failed = 0
    kinds = args.kind or ["genelkurul", "temyiz", "daire"]
    consecutive_errors = 0
    with psycopg.connect(url, autocommit=True) as connection:
        for key in kinds:
            kind = KINDS[key]
            start, total = 0, None
            progress[key] = {"seen": 0, "total": None, "created": 0}
            while not STOP and (total is None or start < total):
                try:
                    rows, total = client.list_page(kind, start=start, length=100)
                except SayistayError as exc:
                    consecutive_errors += 1
                    wait = 900 if "429" in str(exc) else min(600, 30 * consecutive_errors)
                    print(f"{time.strftime('%H:%M:%S')} liste hatası ({exc}); {wait} sn bekleniyor", flush=True)
                    time.sleep(wait)
                    continue
                consecutive_errors = 0
                progress[key]["total"] = total
                ids = [f"sayistay:{key}:{row['Id']}" for row in rows]
                have = existing_external_ids(connection, ids)
                for row, external_id in zip(rows, ids, strict=True):
                    if STOP:
                        break
                    if external_id in have:
                        continue
                    try:
                        html = client.detail_html(kind, int(row["Id"]))
                        result = upsert_official_doc(connection, build_doc(key, row, html), PROFILE)
                    except SayistayError as exc:
                        failed += 1
                        print(f"{time.strftime('%H:%M:%S')} atlandı {external_id}: {exc}", flush=True)
                        if "429" in str(exc):
                            time.sleep(900)
                        continue
                    if result.status == "created":
                        created += 1
                        progress[key]["created"] += 1
                    else:
                        updated += 1
                    if args.limit and created >= args.limit:
                        STOP = True
                        break
                start += len(rows) if rows else 100
                progress[key]["seen"] = min(start, total or start)
                progress["updated_at"] = datetime.now().isoformat(timespec="seconds")
                _save(progress)
                print(
                    f"{time.strftime('%H:%M:%S')} {kind.label}: {progress[key]['seen']:,}/{total:,} | yeni={created:,} "
                    f"güncel={updated:,} hata={failed:,}",
                    flush=True,
                )
            if STOP:
                break
    print(f"BİTTİ: yeni={created:,} güncellenen={updated:,} hata={failed:,}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
