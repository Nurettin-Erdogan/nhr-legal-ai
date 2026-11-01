"""Kapsam raporu: yıl bazında portal toplamı (resmî arama, yıl başına 1 istek) ile bizdeki kayıtlar.

  python scripts/coverage_report.py db        # veritabanı tarafı -> data/campaign/coverage-db.json
  python scripts/coverage_report.py portal    # portal toplamları -> data/campaign/coverage-portal.json
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
OUT = ROOT / "data" / "campaign"


def db() -> None:
    import psycopg

    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"]) as c:
        c.execute("SET default_transaction_read_only=on")
        c.execute("SET statement_timeout=0")
        rows = c.execute(
            """
            SELECT CASE WHEN d.court_name ILIKE 'Danıştay%%' OR d.court_name ILIKE 'Danistay%%' THEN 'danistay'
                        WHEN d.court_name ILIKE 'Yargıtay%%' OR d.court_name ILIKE 'Yargitay%%' THEN 'yargitay' ELSE 'diger' END AS kaynak,
                   extract(year FROM d.decision_date)::int AS yil,
                   count(*) AS toplam,
                   count(*) FILTER (WHERE s.ingest_status = 'ready') AS resmi
            FROM court_decision_details d JOIN legal_sources s ON s.id = d.legal_source_id
            WHERE s.is_current AND s.deleted_at IS NULL AND s.source_type = 'court_decision'
            GROUP BY 1, 2 ORDER BY 1, 2
            """
        ).fetchall()
    data = {}
    for kaynak, yil, toplam, resmi in rows:
        data.setdefault(kaynak, {})[str(yil)] = {"toplam": toplam, "resmi": resmi}
    (OUT / "coverage-db.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("db tamam", {k: sum(v["toplam"] for v in y.values()) for k, y in data.items()}, flush=True)


def portal() -> None:
    result: dict[str, dict[str, int | str]] = {"yargitay": {}, "danistay": {}}
    path = OUT / "coverage-portal.json"
    if path.exists():
        result.update(json.loads(path.read_text(encoding="utf-8")))
    from ingestion.danistay.portal import DanistayPortalClient
    from ingestion.danistay.scraper import ScraperConfig as DConfig, search_filters as d_filters
    from ingestion.yargitay.portal import YargitayPortalClient
    from ingestion.yargitay.scraper import ScraperConfig as YConfig, _search_filters as y_filters

    dc = DanistayPortalClient(timeout_seconds=40, max_retries=2)
    yc = YargitayPortalClient(timeout_seconds=40, max_retries=2)
    for year in range(2026, 1996, -1):
        for name, client, make in (("danistay", dc, lambda y: d_filters(DConfig(decision_date_from=date(y, 1, 1), decision_date_to=date(y, 12, 31)), page_number=1, page_size=1)),
                                   ("yargitay", yc, lambda y: y_filters(YConfig(keyword="", chamber="", decision_date_from=date(y, 1, 1), decision_date_to=date(y, 12, 31)), page_number=1, page_size=1))):
            if str(year) in result[name] and isinstance(result[name][str(year)], int):
                continue
            try:
                f = make(year)
                client.begin_detailed_search(f)
                page = client.search_page(f)
                result[name][str(year)] = page.records_filtered
                print(name, year, page.records_filtered, flush=True)
            except Exception as exc:  # CAPTCHA/429: bu yıl atlanır, yeniden çalıştırılınca denenir
                result[name][str(year)] = f"hata: {type(exc).__name__}"
                print(name, year, "HATA", type(exc).__name__, str(exc)[:80], flush=True)
            path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            time.sleep(8)


if __name__ == "__main__":
    {"db": db, "portal": portal}[sys.argv[1]]()
