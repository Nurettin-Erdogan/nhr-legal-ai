"""UYAP Emsal (istinaf / ilk derece) kararlarından veritabanında OLMAYANLARI resmî portaldan çeker.

Üçüncü taraf veri seti Emsal portalının yalnız bir kısmını (~%75-80) kapsıyor. Bu betik aylık tarih
pencereleriyle resmî arama sonuçlarını gezer, `emsal:<id>` kimliği veritabanında olmayan kararların tam
metnini çekip resmî kayıt olarak (`ready`, official_verified) yazar. Mevcut (tohum) kayıtlara dokunmaz;
onları `verify_seeds.py --source emsal` doğrular. CAPTCHA aşılmaz: beklenir, üst üste 3 CAPTCHA'da çıkılır.

  python scripts/collect_emsal.py                       # bugünden 2018'e, aylık pencereler
  python scripts/collect_emsal.py --from 2024-01-01 --limit 5   # deneme
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import signal
import sys
import time
import urllib.error
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from ingestion.source_errors import is_rate_limited  # noqa: E402
from ingestion.text import html_to_text, normalize_text  # noqa: E402
from ingestion.yargitay.models import CourtDecision  # noqa: E402
from ingestion.yargitay.parser import build_title  # noqa: E402
from ingestion.yargitay.portal import (  # noqa: E402
    CaptchaRequiredError,
    PortalError,
    YargitayPortalClient,
    document_url,
    parse_portal_date,
)
from ingestion.yargitay.scraper import ScraperConfig, _search_filters  # noqa: E402
from ingestion.yargitay.store import upsert_decision  # noqa: E402

BASE_URL = "https://emsal.uyap.gov.tr/"
STATE = ROOT / "data" / "campaign" / "emsal-collect.json"
STOP = False
_NETWORK_ERRORS = (OSError, TimeoutError, http.client.HTTPException, urllib.error.URLError)


def _handle_stop(signum: int, _frame: object) -> None:
    global STOP
    STOP = True
    print(f"durdurma sinyali ({signum}); mevcut karardan sonra çıkılıyor", flush=True)


def _month_windows(start: date, end: date) -> list[tuple[date, date]]:
    """end'den start'a doğru (en yeni ay önce) aylık pencereler."""
    windows: list[tuple[date, date]] = []
    cursor = date(end.year, end.month, 1)
    while cursor >= date(start.year, start.month, 1):
        next_month = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
        windows.append((max(cursor, start), min(next_month - timedelta(days=1), end)))
        cursor = date(cursor.year - (cursor.month == 1), (cursor.month - 2) % 12 + 1, 1)
    return windows


def _decision(row, html: str) -> CourtDecision:
    body = normalize_text(html_to_text(html))
    if not body:
        raise PortalError(f"Karar metni boş: {row.document_id}")
    decision_date = parse_portal_date(row.decision_date)
    if decision_date is None:
        raise PortalError(f"Karar tarihi ayrıştırılamadı: {row.decision_date}")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return CourtDecision(
        court_name=row.chamber,
        chamber=None,
        docket_no=row.docket_no,
        decision_no=row.decision_no,
        decision_date=decision_date,
        title=build_title(row.chamber, None, row.docket_no, row.decision_no, decision_date),
        raw_text=body,
        external_id=f"emsal:{row.document_id}",
        content_hash=digest,
        source_url=document_url(row.document_id, base_url=BASE_URL),
        scraped_at=datetime.now(UTC),
        metadata={
            "source": "emsal.uyap.gov.tr",
            "source_document_id": row.document_id,
            "ingestion_method": "uyap_emsal_public_json_http",
            "canonical_source_name": "UYAP Emsal Karar Arama",
            "header": {
                "daire": row.chamber,
                "esas_no": row.docket_no,
                "karar_no": row.decision_no,
                "karar_tarihi": row.decision_date,
            },
        },
    )


def main() -> int:
    global STOP
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="date_from", default="2018-01-01")
    parser.add_argument("--to", dest="date_to", default=None)
    parser.add_argument("--delay", type=float, default=2.0, help="Karar metni istekleri arası bekleme (sn)")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--limit", type=int, default=0, help="Deneme: toplam bu kadar yeni karar")
    parser.add_argument("--cooldown", type=float, default=90.0, help="429 sonrası bekleme (sn)")
    parser.add_argument("--captcha-wait", type=float, default=900.0)
    args = parser.parse_args()
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL yok")
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    start = date.fromisoformat(args.date_from)
    end = date.fromisoformat(args.date_to) if args.date_to else datetime.now(UTC).date()
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    done_months: set[str] = set(state.get("done_months", []))
    created = state.get("created", 0)
    skipped = state.get("skipped", 0)
    captcha_streak = 0
    server_errors = 0
    client = YargitayPortalClient(base_url=BASE_URL, timeout_seconds=40, max_retries=2)

    def save(**extra: object) -> None:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(
            json.dumps(
                {"done_months": sorted(done_months), "created": created, "skipped": skipped,
                 "updated_at": datetime.now().isoformat(timespec="seconds"), **extra},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def wait_for(exc: Exception) -> bool:
        """True: beklendi, aynı işi yeniden dene. False: üst üste CAPTCHA, çık."""
        nonlocal captcha_streak, server_errors
        if isinstance(exc, CaptchaRequiredError) or "captcha" in str(exc).lower():
            captcha_streak += 1
            if captcha_streak >= 3:
                print("üst üste 3 CAPTCHA; otomatik aşılmaz, durduruldu", flush=True)
                return False
            print(f"{time.strftime('%H:%M:%S')} CAPTCHA istendi; {args.captcha_wait:.0f} sn bekleniyor ({captcha_streak}/3)", flush=True)
            time.sleep(args.captcha_wait)
            return True
        if is_rate_limited(str(exc)):
            print(f"{time.strftime('%H:%M:%S')} hız sınırı (429); {args.cooldown:.0f} sn bekleniyor", flush=True)
            time.sleep(args.cooldown)
            return True
        # Portalın geçici sunucu hatası ("Runtime exception ... Hata Oluştu"): bekle, yeniden dene; üst üste çok olursa dur.
        server_errors += 1
        if server_errors > 6:
            print(f"{time.strftime('%H:%M:%S')} portal art arda hata veriyor ({str(exc)[:70]}); durduruldu", flush=True)
            return False
        print(f"{time.strftime('%H:%M:%S')} portal hatası ({str(exc)[:60]}); 60 sn sonra yeniden denenecek ({server_errors}/6)", flush=True)
        time.sleep(60)
        return True

    with psycopg.connect(url, autocommit=True) as connection:
        for first, last in _month_windows(start, end):
            if STOP:
                break
            key = first.strftime("%Y-%m")
            # Güncel ay her çalıştırmada yeniden taranır; biten eski aylar atlanır.
            if key in done_months and first < date(end.year, end.month, 1):
                continue
            config = ScraperConfig(keyword="", chamber="", decision_date_from=first, decision_date_to=last)
            page, total_pages, month_new = 1, None, 0
            while not STOP and (total_pages is None or page <= total_pages):
                filters = _search_filters(config, page_number=page, page_size=args.page_size)
                try:
                    if page == 1:
                        client.begin_detailed_search(filters)
                    result = client.search_page(filters)
                except (CaptchaRequiredError, PortalError) as exc:
                    if wait_for(exc):
                        continue
                    save(month=key, page=page)
                    return 3
                except _NETWORK_ERRORS as exc:
                    print(f"{time.strftime('%H:%M:%S')} ağ hatası ({type(exc).__name__}); 45 sn sonra yeniden denenecek", flush=True)
                    time.sleep(45)
                    continue
                captcha_streak = 0
                server_errors = 0
                total_pages = max(1, -(-result.records_filtered // args.page_size))
                ids = [f"emsal:{row.document_id}" for row in result.rows if row.document_id]
                have = {
                    r[0]
                    for r in connection.execute(
                        "SELECT external_id FROM legal_sources WHERE source_type = 'court_decision' "
                        "AND is_current AND external_id = ANY(%s)",
                        (ids,),
                    ).fetchall()
                }
                for row in result.rows:
                    if STOP or (args.limit and created >= args.limit):
                        break
                    if not row.document_id or f"emsal:{row.document_id}" in have:
                        continue
                    while True:
                        try:
                            decision = _decision(row, client.fetch_document_html(row.document_id))
                            upsert_decision(connection, decision)
                            created += 1
                            month_new += 1
                            captcha_streak = 0
                            if created % 10 == 0:
                                save(month=key, page=page)  # sayaç tabloda gecikmesin
                            break
                        except _NETWORK_ERRORS as exc:
                            print(f"{time.strftime('%H:%M:%S')} ağ hatası ({type(exc).__name__}) {row.document_id}; 45 sn sonra yeniden denenecek", flush=True)
                            time.sleep(45)
                            continue
                        except (CaptchaRequiredError, PortalError) as exc:
                            message = str(exc)
                            if "captcha" in message.lower() or is_rate_limited(message):
                                if wait_for(exc):
                                    continue
                                save(month=key, page=page)
                                return 3
                            skipped += 1
                            print(f"{time.strftime('%H:%M:%S')} atlandı {row.document_id}: {message[:80]}", flush=True)
                            break
                    time.sleep(args.delay)
                print(
                    f"{time.strftime('%H:%M:%S')} {key} sayfa {page}/{total_pages} | ay içi yeni={month_new:,} toplam yeni={created:,} atlanan={skipped:,}",
                    flush=True,
                )
                save(month=key, page=page)
                if args.limit and created >= args.limit:
                    STOP = True
                page += 1
            if not STOP:
                done_months.add(key)
                save(month=key, page=page)
    print(f"BİTTİ: yeni={created:,} atlanan={skipped:,}", flush=True)
    return 0


def _run_forever() -> int:
    """Beklenmeyen hata işçiyi öldürmesin: nedeni kalıcı dosyaya yazılır, bekleyip kaldığı yerden (durum dosyası) sürer."""
    import traceback

    crash_log = ROOT / "data" / "logs" / "emsal-collect-crash.log"
    while True:
        try:
            return main()
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception:  # noqa: BLE001
            with crash_log.open("a", encoding="utf-8") as handle:
                handle.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{traceback.format_exc()}\n")
            print(f"{time.strftime('%H:%M:%S')} hata (crash logu yazıldı); 30 sn sonra yeniden başlıyor", flush=True)
            if STOP:
                return 1
            time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(_run_forever())
