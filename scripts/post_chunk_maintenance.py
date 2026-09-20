"""Toplu parcalama bittikten sonra veritabani bakimi ve arama duman testi.

ANALYZE + VACUUM yalniz istatistik/olu satir temizligi yapar; veriyi degistirmez.
Ciktisi data/logs/maintenance.log; bitince data/campaign/MAINT_DONE dosyasi yazilir.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
LOG = ROOT / "data" / "logs" / "maintenance.log"
DONE = ROOT / "data" / "campaign" / "MAINT_DONE"
API = "http://127.0.0.1:8766"
QUERIES = ["kıdem tazminatı", "haksız fesih", "iş kazası", "tapu iptali ve tescil", "vergi ziyaı cezası"]


def log(message: str) -> None:
    line = f"{datetime.now():%Y-%m-%dT%H:%M:%S} {message}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main() -> int:
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        log("DATABASE_ADMIN_URL yok")
        return 2
    DONE.parent.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("SET statement_timeout = 0")
        for table in ("legal_chunks", "legal_sources", "court_decision_details", "legal_source_revisions"):
            started = time.time()
            connection.execute(f"VACUUM (ANALYZE, PARALLEL 0) {table}")
            log(f"VACUUM ANALYZE {table} tamam ({time.time() - started:.0f} sn)")
    results = []
    for query in QUERIES:
        started = time.time()
        try:
            with urlopen(f"{API}/api/legal/search?q={quote(query)}&limit=5", timeout=90) as response:
                payload = json.load(response)
            hits = len(payload.get("results") or payload.get("items") or [])
            results.append((query, "ok", round(time.time() - started, 1), hits))
        except Exception as exc:  # noqa: BLE001
            results.append((query, f"HATA {str(exc)[:60]}", round(time.time() - started, 1), 0))
    for query, status, seconds, hits in results:
        log(f"ARAMA '{query}': {status} {seconds} sn, {hits} sonuc")
    DONE.write_text(datetime.now().isoformat(), encoding="utf-8")
    log("bakim tamam")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
