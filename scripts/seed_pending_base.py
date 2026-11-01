"""Bekleyen resmî embedding parçası sayısının tabanını bir kez yazar (data/cache/embedding_pending_base.json).

API "bekleyen"i bu tabandan, o günden beri hazırlanan parçaları (corpus_counts() 'chunks|embedded') düşerek hesaplar.
Ağır sayım (resmî kaynakların embedding'siz parçaları) yönetici bağlantısıyla yapılır; ayda bir kez ya da tabandan sapma
görülürse yeniden çalıştırın.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
OUT = ROOT / "data" / "cache" / "embedding_pending_base.json"
SQL = """
SELECT count(*)::bigint FROM legal_chunks c
WHERE c.embedding IS NULL
  AND c.legal_source_id = ANY(ARRAY(
      SELECT id FROM legal_sources WHERE ingest_status = 'ready' AND is_current AND deleted_at IS NULL))
"""


def main() -> None:
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], autocommit=True) as connection:
        connection.execute("SET statement_timeout = 0")
        embedded_before = dict(connection.execute("SELECT key, n FROM corpus_counts()").fetchall())["chunks|embedded"]
        started = time.time()
        pending = int(connection.execute(SQL).fetchone()[0])
        embedded_after = dict(connection.execute("SELECT key, n FROM corpus_counts()").fetchall())["chunks|embedded"]
    # Sayım sırasında hazırlananlar belirsiz: aralığın ortası alınır.
    embedded = (embedded_before + embedded_after) // 2
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"pending": pending, "embedded": embedded, "at": time.time()}), encoding="utf-8")
    print(f"bekleyen={pending:,} hazır={embedded:,} süre={time.time() - started:.0f} sn")


if __name__ == "__main__":
    main()
