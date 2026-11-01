"""Doğrulanmamış (pending) mevzuat maddelerini resmî PDF metniyle birebir karşılaştırarak doğrular.

Künye doğrulaması (Resmî Gazete/MBS araması) bir kaydı eşleştiremediğinde, maddenin kendi resmî PDF'i yine de okunabilir. Kural
(kullanıcı kararı 2026-10-15): bir resmî kaynakla eşleşen yeterlidir. Burada kaynak adresinden türetilen resmî PDF indirilir, maddenin
metni `_comparison_key` ile birebir karşılaştırılır; yalnız eşleşen madde `ready` olur ve madde kanıtı yazılır. Eşleşmeyen kayıt
değişmez (pending kalır), çöpe gitmez ve deneme sayacı artmaz. Varsayılan kuru çalıştırmadır (`--apply` yazar).

  python scripts/verify_pending_by_text.py            # kuru çalıştırma
  python scripts/verify_pending_by_text.py --apply
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psycopg.types.json import Jsonb  # noqa: E402

from api.db import admin_database_connection  # noqa: E402
from ingestion.mevzuat.identity import canonical_article  # noqa: E402
from ingestion.mevzuat.text_verify import _comparison_key  # noqa: E402
from ingestion.text import content_hash  # noqa: E402
from scripts.verify_article_texts import fetch_with_retry, official_bodies, pdf_url_for, without_leading_caption  # noqa: E402

_PENDING = """
SELECT s.id, s.raw_text, s.content_hash, s.metadata, s.source_url, d.article_no, d.law_no
FROM legal_sources s JOIN legislation_details d ON d.legal_source_id = s.id
WHERE s.source_type = 'legislation' AND s.deleted_at IS NULL AND s.is_current AND s.ingest_status = 'pending'
  AND s.source_url LIKE 'https://www.mevzuat.gov.tr/%%'
ORDER BY s.source_url
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    totals: Counter = Counter()
    with admin_database_connection() as connection:
        connection.execute("SET statement_timeout = 0")
        connection.commit()
        connection.autocommit = True
        rows = connection.execute(_PENDING).fetchall()
        by_url: dict[str, list[dict]] = {}
        for row in rows:
            by_url.setdefault(row["source_url"], []).append(row)
        print(f"{len(rows)} bekleyen madde, {len(by_url)} belge", flush=True)
        for source_url, group in by_url.items():
            target = pdf_url_for(source_url)
            if target is None:
                totals["adres_çözülemedi"] += len(group)
                continue
            _, url = target
            try:
                full = fetch_with_retry(url)
            except Exception as exc:  # noqa: BLE001
                totals["pdf_yok"] += len(group)
                print(f"  {url}: PDF alınamadı ({str(exc)[:70]})  [{len(group)} madde]", flush=True)
                continue
            bodies, occurrences = official_bodies(full)
            document_hash = content_hash(full)
            counts: Counter = Counter()
            for row in group:
                article = canonical_article(row["article_no"] or "")
                official = bodies.get(article)
                if occurrences[article] != 1 or not official:
                    counts["belirsiz_ya_da_yok"] += 1
                    continue
                stored = row["raw_text"] or ""
                if row["content_hash"] != content_hash(stored):
                    counts["özet_uyuşmuyor"] += 1
                    continue
                if _comparison_key(without_leading_caption(stored)) != _comparison_key(official):
                    counts["fark"] += 1
                    continue
                counts["eşleşti"] += 1
                if args.apply:
                    proof = {"verified": True, "url": url, "article_no": article, "checked_at": datetime.now(timezone.utc).isoformat(),
                             "article_hash": row["content_hash"], "document_text_hash": document_hash, "method": "comparison_key_match"}
                    connection.execute(
                        "UPDATE legal_sources SET ingest_status = 'ready', last_verified_at = now(), "
                        "metadata = metadata || %s WHERE id = %s AND ingest_status = 'pending'",
                        (Jsonb({"mbs_text_verification": proof, "verified_against_mbs": True, "verified_by_article_text": True}), row["id"]))
            totals.update(counts)
            print(f"  {url}: {dict(counts)}", flush=True)
            time.sleep(2)
    print(("UYGULANDI" if args.apply else "KURU ÇALIŞTIRMA"), dict(totals), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
