"""Öncelikli resmî backfill kampanyası: tek kurul/daire için yıllık pencereler.

Genel backfill korpusu 2000'den bugüne aylık ve kronolojik tarar; Yargıtay'da
tek yıl ~300 bin karardır. Kampanya bir `chamber` filtresiyle yalnız o
kurul/daireyi, yıllık pencerelerle tarar (boş aylara arama isteği harcamaz).
Aynı worker altyapısı kullanılır (`run_sync`: kilit, checkpoint, kapsam,
karantina). Yalnız resmî portal adaptörleri; CAPTCHA aşılmaz, 429 ve CAPTCHA'da
beklenir. Orijinal imleç `data/campaign/<kaynak>-original.json` dosyasına bir
kez yedeklenir (genel backfill'e dönerken geri yüklenir).

Kullanım:
  python scripts/backfill_campaign.py --source yargitay --chamber "Hukuk Genel Kurulu"
  python scripts/backfill_campaign.py --source yargitay --chamber "9. Hukuk Dairesi" --from 2021-01-01
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

STATE_DIR = ROOT / "data" / "campaign"
STOP = False


def _cursor_key(chamber: str, year: int) -> str:
    return f"{chamber}|{year}"


def _ordered_years(start: date, today: date, *, newest_first: bool, priority_years: list[int]) -> list[int]:
    """Scan likely missing years first, then retain a complete historical sweep."""
    years = list(range(start.year, today.year + 1))
    if newest_first:
        years.reverse()
    priorities = list(dict.fromkeys(year for year in priority_years if year in years))
    return priorities + [year for year in years if year not in priorities]


def _park_partial_cursor(
    parked: dict[str, dict], chamber: str, cursor: dict, start: date, today: date
) -> str | None:
    """Keep a partially scanned year when switching the traversal direction."""
    if cursor.get("window_complete") is not False or str(cursor.get("chamber") or "") != chamber:
        return None
    try:
        window_from = date.fromisoformat(str(cursor["window_from"]))
        window_to = date.fromisoformat(str(cursor["window_to"]))
    except (KeyError, TypeError, ValueError):
        return None
    if not start <= window_from <= today or window_from.year != window_to.year:
        return None
    key = _cursor_key(chamber, window_from.year)
    parked[key] = cursor.copy()
    return key


def _saved_cursor(parked: dict[str, dict], chamber: str, window_from: date, window_to: date) -> dict | None:
    cursor = parked.get(_cursor_key(chamber, window_from.year))
    if not isinstance(cursor, dict):
        return None
    if cursor.get("window_from") != window_from.isoformat() or cursor.get("window_to") != window_to.isoformat():
        return None
    if str(cursor.get("chamber") or "") != chamber or cursor.get("window_complete") is not False:
        return None
    return cursor.copy()


def _handle_stop(signum: int, _frame: object) -> None:
    global STOP
    STOP = True
    print(f"durdurma sinyali alındı ({signum}); mevcut tur bitince çıkılıyor", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, choices=["yargitay", "danistay"])
    parser.add_argument("--chamber", default="", help="Kurul/daire adı; boşsa tüm daireler")
    parser.add_argument("--from", dest="date_from", default=None, help="YYYY-MM-DD; varsayılan kaynağın corpus başlangıcı")
    parser.add_argument("--newest-first", action="store_true", help="Yılları yeniden eskiye tara")
    parser.add_argument("--priority-years", nargs="+", type=int, default=[], help="Önce taranacak yıllar; kalan yıllar da sonra taranır")
    parser.add_argument("--max-records", type=int, default=200, help="Tur başına en fazla karar")
    parser.add_argument("--delay", type=float, default=None, help="Karar başına bekleme (sn); .env değerini ezer")
    parser.add_argument("--cooldown", type=float, default=60.0, help="429 sonrası bekleme (sn)")
    parser.add_argument("--captcha-wait", type=float, default=900.0, help="CAPTCHA sonrası bekleme (sn)")
    parser.add_argument("--pause", type=float, default=5.0, help="Turlar arası bekleme (sn)")
    args = parser.parse_args()

    if args.delay is not None:
        os.environ[f"{args.source.upper()}_DELAY_SECONDS"] = str(args.delay)

    from ingestion.source_errors import is_rate_limited
    from worker.backfill import HORIZON_AUDIT_VERSION, corpus_start_for
    from worker.checkpoints import CheckpointStore
    from worker.jobs import run_sync
    from worker.models import SyncRequest
    from worker.repository import SyncRepository

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL tanımlı değil")
    source = args.source
    chamber = args.chamber.strip()
    horizon = corpus_start_for(source)
    start = max(date.fromisoformat(args.date_from), horizon) if args.date_from else horizon
    today = datetime.now(UTC).date()
    years = _ordered_years(start, today, newest_first=args.newest_first, priority_years=args.priority_years)
    label = f"{source}/{chamber or 'tüm daireler'}"

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = STATE_DIR / "done.json"
    done: dict[str, str] = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    parked_path = STATE_DIR / f"{source}-paused-cursor.json"
    parked: dict[str, dict] = json.loads(parked_path.read_text(encoding="utf-8")) if parked_path.exists() else {}

    def save_parked() -> None:
        parked_path.write_text(json.dumps(parked, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def save_done(key: str) -> None:
        done[key] = datetime.now(UTC).isoformat()
        state_path.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")

    with psycopg.connect(url, autocommit=True) as connection:
        store = CheckpointStore(SyncRepository(connection))
        checkpoint = store.load(source)
        cursor = dict(checkpoint.last_cursor or {})

        # A changed priority order or chamber must not discard a partially
        # scanned year. The key also records its original chamber.
        parked_key = _park_partial_cursor(parked, str(cursor.get("chamber") or ""), cursor, start, today)
        if parked_key:
            save_parked()
            print(f"kısmi yıl imleci korundu: {parked_key}", flush=True)

        backup = STATE_DIR / f"{source}-original.json"
        if not backup.exists():
            backup.write_text(json.dumps(cursor, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(f"orijinal imleç yedeklendi: {backup}", flush=True)

        t0 = time.time()
        created_total = 0
        captcha_streak = 0
        failures = 0
        for year in years:
            key = f"{label}|{year}"
            if key in done:
                print(f"{year}: zaten tamam", flush=True)
                continue
            window_from = max(date(year, 1, 1), start)
            window_to = min(date(year, 12, 31), today)
            checkpoint = store.load(source)
            cursor = dict(checkpoint.last_cursor or {})
            same = (
                cursor.get("window_from") == window_from.isoformat()
                and cursor.get("window_to") == window_to.isoformat()
                and str(cursor.get("chamber") or "") == chamber
                and cursor.get("window_complete") is False
            )
            if not same:
                checkpoint.last_cursor = _saved_cursor(parked, chamber, window_from, window_to) or {
                    "full_horizon_start": horizon.isoformat(),
                    "horizon_audit_version": HORIZON_AUDIT_VERSION,
                    "next_window_start": window_from.isoformat(),
                    "window_complete": True,
                    "reconciled": False,
                    "chamber": chamber,
                    "page": 1,
                    "row_offset": 0,
                }
                checkpoint.last_page = int(checkpoint.last_cursor.get("page") or 1)
                checkpoint.last_date_from = window_from
                checkpoint.last_date_to = window_to
                checkpoint.next_run_at = datetime.now(UTC)
                store.save(checkpoint)
            print(f"== {label} {year}: {window_from}..{window_to} ({'devam' if same else 'başlıyor'})", flush=True)

            while not STOP:
                result = run_sync(
                    connection,
                    SyncRequest(
                        source=source,
                        date_from=window_from,
                        date_to=window_to,
                        chamber=chamber,
                        resume=True,
                        max_records=args.max_records,
                        lane="backfill",
                    ),
                    should_stop=lambda: STOP,
                )
                status = str(result.get("status"))
                error = result.get("error")
                counters = result.get("counters") or {}
                cur = (result.get("checkpoint") or {}).get("last_cursor") or {}
                created = int(counters.get("records_created") or 0)
                created_total += created
                print(
                    f"{datetime.now().strftime('%H:%M:%S')} {status:9s} yeni={created:>3} toplam={created_total:>6} "
                    f"sayfa={cur.get('page')} satır={cur.get('row_offset')} beklenen={cur.get('expected_count')} "
                    f"| {(time.time() - t0) / 60:.0f} dk" + (f" | {str(error)[:60]}" if error else ""),
                    flush=True,
                )
                if status == "captcha_required":
                    captcha_streak += 1
                    if captcha_streak >= 3:
                        print("üst üste 3 CAPTCHA; otomatik aşılmaz, kampanya durduruldu", flush=True)
                        return 3
                    print(f"CAPTCHA istendi; {args.captcha_wait:.0f} sn bekleniyor ({captcha_streak}/3)", flush=True)
                    time.sleep(args.captcha_wait)
                    continue
                captcha_streak = 0
                if cur.get("window_complete") is True and cur.get("window_from") == window_from.isoformat():
                    save_done(key)
                    if parked.pop(_cursor_key(chamber, year), None) is not None:
                        save_parked()
                    print(f"{year} tamam", flush=True)
                    break
                if error and is_rate_limited(str(error)):
                    failures = 0
                    time.sleep(args.cooldown)
                elif status == "failed":
                    failures += 1
                    if failures >= 20:
                        print("art arda 20 hata; kampanya durduruldu", flush=True)
                        return 2
                    time.sleep(max(args.cooldown, 15.0))
                else:
                    failures = 0
                    time.sleep(args.pause)
            if STOP:
                return 0
        print(f"KAMPANYA TAMAM: {label} | {created_total} yeni kayıt | {(time.time() - t0) / 60:.0f} dk", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
