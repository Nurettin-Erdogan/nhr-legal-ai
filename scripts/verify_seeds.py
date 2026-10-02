"""Üçüncü taraf (bulk_seed, pending) Yargıtay/Danıştay kararlarını resmî portaldan doğrular.

Kampanyalar arama sayfalarını gezip kararları bulur; burada kararların kimliği zaten
veritabanında olduğundan her karar doğrudan kimlikle (`getDokuman?id=`) çekilir, arama isteği
harcanmaz. Karar tarihine göre en yeniden eskiye gidilir.

Doğrulama kuralı: resmî metin ile kayıtlı metin, boşluk farkları yok sayılarak aynıysa kayıt
`ready` + resmî `ingestion_method` olur ve resmî metin yazılır. Farklıysa kayıt DEĞİŞTİRİLMEZ,
`metadata.verify_status = 'mismatch'` ile işaretlenir; bunları resmî kampanya (aramadan gelen
üst verisiyle) ele alır. Portal açılmıyorsa `unavailable` işaretlenir. CAPTCHA'da beklenir,
aşılmaz. Kaldığı yerden devam eder (`data/campaign/verify-<kaynak>.json`).

Kullanım:
  python scripts/verify_seeds.py --source danistay --max-docs 30 --dry-run   # deneme, yazmaz
  python scripts/verify_seeds.py --source yargitay
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

STATE_DIR = ROOT / "data" / "campaign"
STOP = False

SOURCES = {
    "yargitay": {
        "prefix": "yargitay:",
        "method": "yargitay_public_json_http",
        "canonical": "Yargıtay Karar Arama",
    },
    "danistay": {
        "prefix": "danistay:",
        "method": "danistay_public_json_http",
        "canonical": "Danıştay Karar Arama",
    },
    # UYAP Emsal (istinaf / ilk derece): Yargıtay ile aynı API ailesi, ayrı sunucu (kendi hız sınırı).
    "emsal": {
        "prefix": "emsal:",
        "method": "uyap_emsal_public_json_http",
        "canonical": "UYAP Emsal Karar Arama",
    },
}

_SELECT_BATCH = """
SELECT ls.id, ls.external_id, ls.raw_text, d.decision_date
FROM court_decision_details d
JOIN legal_sources ls ON ls.id = d.legal_source_id
WHERE d.decision_date IS NOT NULL
  AND (%(cdate)s::date IS NULL OR (d.decision_date, d.legal_source_id) < (%(cdate)s::date, %(cid)s::uuid))
  AND ls.ingestion_method = 'bulk_seed'
  AND ls.ingest_status = 'pending'
  AND ls.is_current
  AND ls.deleted_at IS NULL
  AND ls.source_type = 'court_decision'
  AND ls.external_id LIKE %(prefix)s
  AND ls.metadata->>'verify_status' IS NULL
ORDER BY d.decision_date DESC, d.legal_source_id DESC
LIMIT %(batch)s
"""

# Atıf yapılan kayıtlar (seed_verification_queue) tarih taramasının önüne geçer.
_SELECT_QUEUE = """
SELECT ls.id, ls.external_id, ls.raw_text, d.decision_date
FROM seed_verification_queue q
JOIN legal_sources ls ON ls.id = q.legal_source_id
LEFT JOIN court_decision_details d ON d.legal_source_id = ls.id
WHERE q.picked_at IS NULL
  AND ls.ingestion_method = 'bulk_seed'
  AND ls.ingest_status = 'pending'
  AND ls.is_current
  AND ls.deleted_at IS NULL
  AND ls.external_id LIKE %(prefix)s
ORDER BY q.request_count DESC, q.requested_at
LIMIT %(batch)s
"""

_QUEUE_DONE = "DELETE FROM seed_verification_queue WHERE legal_source_id = ANY(%s)"

_VERIFY = """
UPDATE legal_sources
SET ingest_status = 'ready',
    ingestion_method = %(method)s,
    canonical_source_name = %(canonical)s,
    official_source_url = %(url)s,
    source_url = COALESCE(%(url)s, source_url),
    raw_text = %(text)s,
    content_hash = %(hash)s,
    source_version = %(version)s,
    metadata = metadata || %(metadata)s,
    last_ingested_at = NOW(),
    fetched_at = NOW(),
    last_verified_at = NOW()
WHERE id = %(id)s AND ingestion_method = 'bulk_seed' AND ingest_status = 'pending'
"""

_MARK = """
UPDATE legal_sources SET metadata = metadata || %(metadata)s
WHERE id = %(id)s AND ingestion_method = 'bulk_seed' AND ingest_status = 'pending'
"""


# Görünmez biçim karakterleri (yön denetimi, sıfır genişlikli, yumuşak tire, BOM). Resmî
# metinde bulunup üçüncü taraf derlemede temizlenmiş olabilirler; hukuki anlam taşımazlar.
_INVISIBLE = re.compile(r"[­​-‏‪-‮⁠-⁤⁦-⁩﻿]")


def _canon(text: str) -> str:
    return re.sub(r"\s+", " ", _INVISIBLE.sub("", text)).strip().casefold()


def _nospace(text: str) -> str:
    """Boşlukların tamamı atılmış anahtar: satır sonu/boşluk kaybı farklarını yok sayar."""
    return re.sub(r"\s+", "", _INVISIBLE.sub("", text)).casefold()


def _handle_stop(signum: int, _frame: object) -> None:
    global STOP
    STOP = True
    print(f"durdurma sinyali ({signum}); mevcut karardan sonra çıkılıyor", flush=True)


_BEDESTEN = None


def _fetch_official_text(source: str, client, document_id: str) -> str:
    from ingestion.text import html_to_text, normalize_text

    if source in ("yargitay", "danistay"):
        # Adalet Bakanlığı Bedesten: CAPTCHA'sız, portalla aynı kimlik ve metin. Hız sınırında (429)
        # istisna yukarı fırlatılır ve döngünün kendi bekleme mantığı devreye girer; başka hatada portala düşülür.
        global _BEDESTEN
        from ingestion.bedesten_emsal import BedestenClient, BedestenError, BedestenRateLimited

        if _BEDESTEN is None:
            _BEDESTEN = BedestenClient(timeout=20.0)
        try:
            text = normalize_text(html_to_text(_BEDESTEN.content_html(document_id)))
            if text:
                return text
        except BedestenRateLimited:
            raise
        except BedestenError as exc:
            if "bulunamadı" in str(exc) or "Record not found" in str(exc):
                # Bedesten kaydı hiç vermiyor (ölçüldü: 2026-10-02, listede görünüp çekilemeyen
                # "hayalet" kayıt). Portala düşmek bağlantı hatasında beş saat takılıp kaldı; kalıcı
                # sayılır ("geçersiz" sözcüğü döngüde beklemesiz `unavailable` işaretletir).
                raise ValueError(f"geçersiz kimlik: Bedesten kaydı yok ({document_id})") from exc
    html = client.fetch_document_html(document_id)
    if source == "danistay":
        from ingestion.danistay.scraper import extract_decision_text

        return extract_decision_text(html)
    return normalize_text(html_to_text(html))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, choices=sorted(SOURCES))
    parser.add_argument("--delay", type=float, default=6.0, help="Başlangıç bekleme (sn); hız kendini ayarlar")
    parser.add_argument("--min-delay", type=float, default=4.5, help="En hızlı bekleme (sn) ≈ 13 istek/dk")
    parser.add_argument("--max-delay", type=float, default=30.0)
    parser.add_argument("--cooldown", type=float, default=90.0, help="429 sonrası bekleme (sn)")
    parser.add_argument("--captcha-wait", type=float, default=900.0)
    parser.add_argument("--batch", type=int, default=50)
    parser.add_argument("--max-docs", type=int, default=0, help="0 = sınırsız")
    parser.add_argument("--queue-only", action="store_true",
                        help="Yalnız atıf kuyruğunu doğrula (tarih taraması yok); kuyruk boşsa 5 dk bekler")
    parser.add_argument("--dry-run", action="store_true", help="Yazma; yalnız eşleşme oranını göster")
    parser.add_argument("--restart", action="store_true", help="İmleci sıfırla (en yeni tarihten başla)")
    args = parser.parse_args()

    from ingestion.hf_700k import strip_third_party_markup
    from ingestion.source_errors import is_rate_limited
    from ingestion.text import content_hash
    from ingestion.yargitay.store import _SNAPSHOT_SOURCE

    if args.source == "yargitay":
        from ingestion.yargitay.portal import YargitayPortalClient, document_url

        client = YargitayPortalClient(timeout_seconds=30, max_retries=2)
    elif args.source == "emsal":
        from ingestion.yargitay.portal import YargitayPortalClient
        from ingestion.yargitay.portal import document_url as _document_url

        emsal_base = "https://emsal.uyap.gov.tr/"
        client = YargitayPortalClient(base_url=emsal_base, timeout_seconds=30, max_retries=2)

        def document_url(document_id: str) -> str:
            return _document_url(document_id, base_url=emsal_base)
    else:
        from ingestion.danistay.portal import DanistayPortalClient, document_url

        client = DanistayPortalClient(timeout_seconds=30, max_retries=2)

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL tanımlı değil")

    cfg = SOURCES[args.source]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = STATE_DIR / f"verify-{args.source}.json"
    state = {}
    if state_path.exists() and not args.restart and not args.dry_run:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    cursor_date, cursor_id = state.get("date"), state.get("id")
    totals = {"verified": 0, "mismatch": 0, "unavailable": 0, "rate_limited": 0, "captcha": 0, **{k: state.get(k, 0) for k in ("verified", "mismatch", "unavailable")}}
    captcha_streak = 0
    success_streak = 0
    cur_delay = args.delay  # AIMD: 429/CAPTCHA'da artar, 20 başarıda %5 azalır (min-delay altına inmez)
    transient_failures = 0
    processed = 0
    t0 = time.time()

    def save_state(date_value, id_value) -> None:
        if args.dry_run:
            return
        state_path.write_text(
            json.dumps({"date": str(date_value), "id": str(id_value), **{k: totals[k] for k in ("verified", "mismatch", "unavailable")}}, ensure_ascii=False),
            encoding="utf-8",
        )

    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("SET statement_timeout = '120s'")
        while not STOP:
            rows = connection.execute(
                _SELECT_QUEUE, {"prefix": cfg["prefix"] + "%", "batch": args.batch}
            ).fetchall()
            from_queue = bool(rows)
            if args.queue_only and not from_queue:
                time.sleep(300)
                continue
            if from_queue:
                print(f"atıf kuyruğundan {len(rows)} kayıt öncelikli işleniyor", flush=True)
            else:
                rows = connection.execute(
                    _SELECT_BATCH,
                    {"cdate": cursor_date, "cid": cursor_id, "prefix": cfg["prefix"] + "%", "batch": args.batch},
                ).fetchall()
            if not rows:
                print("işlenecek doğrulanmamış kayıt kalmadı", flush=True)
                break
            for source_id, external_id, seed_text, decision_date in rows:
                if STOP or (args.max_docs and processed >= args.max_docs):
                    break
                document_id = external_id.split(":", 1)[1]
                status = None
                official = ""
                try:
                    official = _fetch_official_text(args.source, client, document_id)
                    captcha_streak = 0
                    success_streak += 1
                    if success_streak >= 20:
                        cur_delay = max(args.min_delay, cur_delay * 0.95)
                        success_streak = 0
                except Exception as exc:  # noqa: BLE001
                    message = str(exc)
                    if "captcha" in message.lower() or "captcha" in type(exc).__name__.lower():
                        captcha_streak += 1
                        success_streak = 0
                        cur_delay = min(args.max_delay, cur_delay * 1.5)
                        totals["captcha"] += 1
                        if captcha_streak >= 3:
                            print("üst üste 3 CAPTCHA; otomatik aşılmaz, durduruldu", flush=True)
                            return 3
                        print(f"CAPTCHA istendi; {args.captcha_wait:.0f} sn bekleniyor ({captcha_streak}/3)", flush=True)
                        time.sleep(args.captcha_wait)
                        break  # aynı kayıttan yeniden başla (imleç ilerlemedi)
                    if is_rate_limited(message):
                        totals["rate_limited"] += 1
                        success_streak = 0
                        cur_delay = min(args.max_delay, cur_delay * 1.3)
                        print(f"hız sınırı (429); {args.cooldown:.0f} sn bekleniyor; yeni aralık {cur_delay:.1f} sn", flush=True)
                        time.sleep(args.cooldown)
                        break
                    lowered = message.lower()
                    permanent = any(word in lowered for word in ("bos ", "boş", "gecersiz", "geçersiz"))
                    # Danıştay hız sınırında "hiddencontent bulunamadı" (boş sayfa) döndürür: kararın
                    # eksik olduğu anlamına gelmez; yavaşlayıp aynı kararı yeniden dene.
                    soft_block = "hiddencontent" in lowered
                    if soft_block:
                        success_streak = 0
                        cur_delay = min(args.max_delay, cur_delay * 1.3)
                    transient_failures += 1
                    if not permanent and transient_failures < (4 if soft_block else 5):
                        wait = args.cooldown if soft_block else 30
                        print(f"geçici hata ({transient_failures}): {message[:70]}; {wait:.0f} sn bekleniyor; aralık {cur_delay:.1f} sn", flush=True)
                        time.sleep(wait)
                        break  # aynı kayıttan yeniden dene
                    status = "unavailable"
                    official = ""
                    reason = message[:120]
                else:
                    reason = ""

                processed += 1
                transient_failures = 0
                now = datetime.now(UTC).isoformat(timespec="seconds")
                if status is None and official.strip():
                    seed_key = _canon(seed_text or "")
                    # Kayıtlı metin üçüncü taraf temizliğinden geçmiş olabilir ("İçtihat Metni"
                    # başlık satırı atılmış ya da satır içinde kalmış olabilir): ham ya da temizlenmiş
                    # resmî metinden biri boşluk farkları dışında aynıysa doğrulanır.
                    same = seed_key in (_canon(official), _canon(strip_third_party_markup(official)))
                    if not same:
                        seed_flat = _nospace(seed_text or "")
                        same = seed_flat in (_nospace(official), _nospace(strip_third_party_markup(official)))
                    status = "verified" if same else "mismatch"
                elif status is None:
                    status, reason = "unavailable", "boş resmî metin"

                if status == "verified":
                    digest = content_hash(official)
                    if not args.dry_run:
                        with connection.transaction(), connection.cursor() as cur:
                            cur.execute(_SNAPSHOT_SOURCE, (source_id,))
                            cur.execute(
                                _VERIFY,
                                {
                                    "id": source_id,
                                    "method": cfg["method"],
                                    "canonical": cfg["canonical"],
                                    "url": document_url(document_id),
                                    "text": official,
                                    "hash": digest,
                                    "version": f"sha256:{digest[:16]}",
                                    "metadata": Jsonb(
                                        {
                                            "official_verified": True,
                                            "third_party": False,
                                            "provenance": "official_portal",
                                            "verified_via": "seed_verifier",
                                            "verified_at": now,
                                            "verification": "text_equal_ignoring_whitespace",
                                        }
                                    ),
                                },
                            )
                else:
                    if not args.dry_run:
                        connection.execute(
                            _MARK,
                            {
                                "id": source_id,
                                "metadata": Jsonb({"verify_status": status, "verify_checked_at": now, "verify_reason": reason or None}),
                            },
                        )
                totals[status] += 1
                if from_queue:
                    if not args.dry_run:
                        connection.execute(_QUEUE_DONE, ([source_id],))
                else:
                    # Kuyruk kaydı tarih sırasının dışından gelir; imleci yalnız tarama ilerletir.
                    cursor_date, cursor_id = decision_date, source_id
                    save_state(cursor_date, cursor_id)
                if processed % 25 == 0 or args.dry_run:
                    print(
                        f"{datetime.now():%H:%M:%S} işlenen={processed} doğrulanan={totals['verified']} "
                        f"uyuşmayan={totals['mismatch']} açılmayan={totals['unavailable']} aralık={cur_delay:.1f}sn tarih={decision_date} "
                        f"| {(time.time() - t0) / 60:.0f} dk",
                        flush=True,
                    )
                time.sleep(cur_delay)
            else:
                if args.max_docs and processed >= args.max_docs:
                    break
                continue
            if args.max_docs and processed >= args.max_docs:
                break
    print(
        f"BİTTİ: işlenen={processed} doğrulanan={totals['verified']} uyuşmayan={totals['mismatch']} "
        f"açılmayan={totals['unavailable']} | {(time.time() - t0) / 60:.0f} dk",
        flush=True,
    )
    return 0


def _run_forever() -> int:
    """Beklenmeyen hata (veritabanı zaman aşımı, bağlantı kopması) doğrulayıcıyı öldürmesin: nedeni kalıcı
    dosyaya yazılır, kısa beklemeden sonra yeniden bağlanıp imleçten devam edilir. CAPTCHA'da durma (dönüş kodu)
    ve normal bitiş bu döngüden geçmez."""
    import traceback

    source = sys.argv[sys.argv.index("--source") + 1] if "--source" in sys.argv else "genel"
    crash_log = ROOT / "data" / "logs" / f"verify-crash-{source}.log"
    while True:
        try:
            return main()
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception:  # noqa: BLE001
            with crash_log.open("a", encoding="utf-8") as handle:
                handle.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{traceback.format_exc()}\n")
            print(f"{time.strftime('%H:%M:%S')} hata (crash logu yazıldı); 30 sn sonra yeniden bağlanılıyor", flush=True)
            if STOP:
                return 1
            time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(_run_forever())
