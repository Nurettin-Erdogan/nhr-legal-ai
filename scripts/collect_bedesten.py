"""Bedesten'den bizde olmayan Yargıtay/Danıştay kararlarını çeker (CAPTCHA'sız, resmî).

Portal (karararama.*) yerine Adalet Bakanlığı Bedesten arayüzü kullanılır; doküman kimliği aynı
olduğundan boşluk kimlik düzeyinde tam bulunur. Yöntem, en yeni yıldan eskiye:

  1. Ay toplamı Bedesten'de bizdekinden büyük değilse ay atlanır (1 istek).
  2. Aksi halde gün gün toplamlar karşılaştırılır; fark olan günün listesi çekilip kimlikleri
     veritabanıyla kıyaslanır.
  3. Eksik her karar için metin çekilir ve `upsert_decision` ile `ready` (resmî) olarak yazılır.
     Aynı kimlik daha önce doğrulanmamış tohum olarak varsa resmî metinle yükseltilir.

Hız AIMD ile ayarlanır: 429'da aralık artar, seri başarıda azalır. Ortak bekleme dosyası
(`bedesten-cooldown.json`) sayesinde diğer Bedesten kullanıcıları (mevzuat, sorgu anı doğrulama) da
429 sonrası bekler. Durdurma: `data/campaign/BEDESTEN_STOP` dosyası ya da SIGINT.

    python scripts/collect_bedesten.py --source yargitay
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import logging
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

from ingestion.bedesten_emsal import (  # noqa: E402
    BedestenClient,
    BedestenError,
    BedestenItem,
    BedestenRateLimited,
)
from ingestion.text import html_to_text, normalize_text  # noqa: E402
from ingestion.yargitay.models import CourtDecision  # noqa: E402
from ingestion.yargitay.parser import build_title  # noqa: E402
from ingestion.yargitay.store import upsert_decision  # noqa: E402

logger = logging.getLogger("collect_bedesten")
STATE_DIR = ROOT / "data" / "campaign"
STOP_FILE = STATE_DIR / "BEDESTEN_STOP"
STOP = False

SOURCES = {
    "yargitay": {
        "court": "Yargıtay",
        "canonical": "Yargıtay Karar Arama",
        "method": "yargitay_public_json_http",
        "site": "karararama.yargitay.gov.tr",
        "url": "https://karararama.yargitay.gov.tr/getDokuman?id={id}",
    },
    "danistay": {
        "court": "Danıştay",
        "canonical": "Danıştay Karar Arama",
        "method": "danistay_public_json_http",
        "site": "karararama.danistay.gov.tr",
        "url": "https://karararama.danistay.gov.tr/getDokuman?id={id}",
    },
}


def _stop_requested() -> bool:
    return STOP or STOP_FILE.exists()


def decision_from_bedesten(kind: str, item: BedestenItem, html: str) -> CourtDecision:
    config = SOURCES[kind]
    missing = [
        label
        for label, value in (
            ("daire", item.chamber),
            ("esas no", item.docket_no),
            ("karar no", item.decision_no),
            ("karar tarihi", item.decision_date),
        )
        if not value
    ]
    if missing:
        raise BedestenError(f"Karar liste kaydında eksik alanlar: {', '.join(missing)}")
    text = normalize_text(html_to_text(html))
    if not text:
        raise BedestenError(f"Karar metni ayrıştırılamadı: {item.document_id}")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return CourtDecision(
        court_name=config["court"],
        chamber=item.chamber,
        docket_no=item.docket_no,
        decision_no=item.decision_no,
        decision_date=item.decision_date,
        title=build_title(config["court"], item.chamber, item.docket_no, item.decision_no, item.decision_date),
        raw_text=text,
        external_id=f"{kind}:{item.document_id}",
        content_hash=digest,
        source_url=config["url"].format(id=item.document_id),
        scraped_at=datetime.now(UTC),
        metadata={
            "source": config["site"],
            "source_adapter": kind,
            "source_document_id": item.document_id,
            "canonical_source_name": config["canonical"],
            "ingestion_method": config["method"],
            "fetch_channel": "bedesten.adalet.gov.tr/emsal-karar",
            "header": {
                "daire": item.chamber,
                "esas_no": item.docket_no,
                "karar_no": item.decision_no,
                "karar_tarihi": item.decision_date.strftime("%d.%m.%Y"),
            },
        },
    )


class Collector:
    def __init__(self, kind: str, client: BedestenClient, connection: psycopg.Connection) -> None:
        self.kind = kind
        self.client = client
        self.connection = connection
        self.prefix = f"{kind}:"
        self.fetched = 0
        self.failed = 0
        self.streak = 0
        self.started = time.monotonic()
        self.state_path = STATE_DIR / f"bedesten-{kind}-state.json"
        try:
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.state = {"months": {}}

    # -- hız ayarı ---------------------------------------------------------------------------
    def _limited(self) -> None:
        # Ölçüm: engel ~10 sn sürer ve sabit ~4,5 sn aralık + kısa bekleme dakikada ~13 istek verir.
        # 429'da aralığı büyütmek verimi düşürür; yalnız hafifçe (%3) ve en çok 6 sn'ye kadar artır.
        self.streak = 0
        self.client.min_interval = min(self.client.min_interval * 1.03, 6.0)
        logger.warning("429: aralık %.1f sn", self.client.min_interval)

    def _ok(self) -> None:
        self.streak += 1
        if self.streak >= 10 and self.client.min_interval > 4.4:
            self.streak = 0
            self.client.min_interval = max(self.client.min_interval * 0.97, 4.4)

    def _call(self, fn, *args, **kwargs):
        """429'da aynı çağrıyı bekleyerek yeniden dener (en çok 8 kez)."""
        for attempt in range(8):
            if _stop_requested():
                raise KeyboardInterrupt
            try:
                result = fn(*args, **kwargs)
                self._ok()
                return result
            except BedestenRateLimited:
                self._limited()
            except BedestenError as exc:
                # Portal listede gösterip belgeyi vermeyen kayıt kalıcı olarak yoktur (ölçüldü:
                # 2026-10-02, 2022-12). Yeniden denemek her kayıtta ~25 sn bekleyip kotayı boşa harcar.
                if "bulunamadı" in str(exc) or "Record not found" in str(exc) or attempt >= 2:
                    raise
                logger.warning("Bedesten hatası, yeniden denenecek: %s", exc)
                time.sleep(5 * (attempt + 1))
        raise BedestenError("Bedesten hız sınırı aşılamadı")

    # -- veritabanı --------------------------------------------------------------------------
    def db_day_counts(self, first: date, last: date) -> dict[date, int]:
        rows = self.connection.execute(
            "SELECT d.decision_date, count(*) FROM court_decision_details d "
            "JOIN legal_sources ls ON ls.id = d.legal_source_id "
            "WHERE d.decision_date >= %s AND d.decision_date <= %s AND ls.external_id LIKE %s "
            "AND ls.is_current AND ls.deleted_at IS NULL GROUP BY 1",
            (first, last, self.prefix + "%"),
        ).fetchall()
        return {row[0]: int(row[1]) for row in rows}

    def known_ids(self, ids: list[str]) -> set[str]:
        rows = self.connection.execute(
            "SELECT external_id FROM legal_sources WHERE external_id = ANY(%s) AND is_current",
            ([self.prefix + i for i in ids],),
        ).fetchall()
        return {row[0][len(self.prefix):] for row in rows}

    # -- iş akışı ----------------------------------------------------------------------------
    def total(self, first: date, last: date) -> int:
        return self._call(self.client.search, self.kind, first, last, page=1, page_size=1).total

    def collect_day(self, day: date, total: int, first_page: list[BedestenItem] | None = None) -> int:
        items: list[BedestenItem] = list(first_page or [])
        page = 2 if first_page else 1
        while len(items) < total:
            result = self._call(self.client.search, self.kind, day, day, page=page)
            if not result.items:
                break
            items.extend(result.items)
            page += 1
        known = self.known_ids([i.document_id for i in items])
        missing = [i for i in items if i.document_id not in known]
        saved = 0
        for item in missing:
            try:
                html = self._call(self.client.content_html, item.document_id)
                decision = decision_from_bedesten(self.kind, item, html)
                upsert_decision(self.connection, decision)
            except BedestenError as exc:
                self.failed += 1
                logger.warning("Karar alınamadı %s: %s", item.document_id, exc)
                continue
            saved += 1
            self.fetched += 1
            if self.fetched % 25 == 0:
                self.report(day)
        return saved

    def report(self, day: date) -> None:
        minutes = (time.monotonic() - self.started) / 60
        rate = self.fetched / max(minutes / 60, 0.01)
        print(
            f"{datetime.now():%H:%M:%S} yeni={self.fetched} hata={self.failed} tarih={day} "
            f"aralık={self.client.min_interval:.1f}sn hız={rate:.0f}/sa | {minutes:.0f} dk",
            flush=True,
        )

    def collect_month(self, year: int, month: int) -> None:
        key = f"{year}-{month:02d}"
        today = date.today()
        last_day = min(date(year, month, calendar.monthrange(year, month)[1]), today)
        first_day = date(year, month, 1)
        if first_day > today:
            return
        recent = (today - last_day).days < 45
        done_at = self.state["months"].get(key)
        if done_at and not recent:
            return
        if done_at and recent and time.time() - done_at < 6 * 3600:
            return
        counts = self.db_day_counts(first_day, last_day)
        if self.total(first_day, last_day) <= sum(counts.values()):
            self._finish(key)
            return
        day = last_day
        # Yeniden başlatmada bitmiş günleri tekrar sorgulamamak için gün imleci (aydan ay bitince silinir).
        cursor = self.state.setdefault("cursor", {}).get(key)
        if cursor:
            day = min(day, date.fromisoformat(cursor))
        while day >= first_day:
            if _stop_requested():
                raise KeyboardInterrupt
            have = counts.get(day, 0)
            # Tek istek: hem gün toplamı hem ilk 100 kayıt (eksik günde ayrı liste isteği gerekmez).
            first = self._call(self.client.search, self.kind, day, day, page=1)
            total = first.total
            if total > have:
                saved = self.collect_day(day, total, first.items)
                logger.info("%s: portalda %d, bizde %d, çekilen %d", day, total, have, saved)
            day = date.fromordinal(day.toordinal() - 1)
            self.state["cursor"][key] = day.isoformat()
            self._save_state()
        self._finish(key)

    def _save_state(self) -> None:
        try:
            self.state_path.write_text(json.dumps(self.state), encoding="utf-8")
        except OSError:
            logger.warning("Durum dosyası yazılamadı", exc_info=True)

    def _finish(self, key: str) -> None:
        self.state["months"][key] = time.time()
        self.state.setdefault("cursor", {}).pop(key, None)
        self._save_state()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=sorted(SOURCES), default="yargitay")
    parser.add_argument("--from-year", type=int, default=date.today().year, help="en yeni yıl")
    parser.add_argument("--to-year", type=int, default=2000, help="en eski yıl")
    parser.add_argument("--interval", type=float, default=4.5, help="başlangıç istek aralığı (sn); 4,4-6 sn arasında hafifçe ayarlanır")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        sys.exit("DATABASE_ADMIN_URL tanımlı değil")

    def _stop(_signum, _frame) -> None:
        global STOP
        STOP = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    done_marker = STATE_DIR / f"bedesten-{args.source}-done.json"
    done_marker.unlink(missing_ok=True)  # yeni tur başladı: önceki bitiş işareti geçersiz
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("SET statement_timeout = '120s'")
        collector = Collector(args.source, BedestenClient(min_interval=args.interval), connection)
        try:
            for year in range(args.from_year, args.to_year - 1, -1):
                for month in range(12, 0, -1):
                    collector.collect_month(year, month)
                print(f"{datetime.now():%H:%M:%S} {year} yılı tamam | yeni={collector.fetched}", flush=True)
        except KeyboardInterrupt:
            print("durduruldu", flush=True)
            return
    done_marker.write_text(json.dumps({"finished_at": datetime.now(UTC).isoformat(timespec="seconds")}), encoding="utf-8")
    print(f"KAMPANYA TAMAM: bedesten/{args.source} yeni={collector.fetched} hata={collector.failed}", flush=True)


if __name__ == "__main__":
    main()
