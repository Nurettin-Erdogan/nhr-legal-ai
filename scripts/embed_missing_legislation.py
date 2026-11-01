"""Hazır mevzuat parçalarından vektörü (nomic-embed-text, 768) olmayanları doldurur.

Yalnız `legal_chunks.embedding IS NULL` olan, kaynağı `ready` mevzuat parçaları işlenir; önce güncel maddeler. Yazma koşulludur
(`content_hash` aynı ve `embedding IS NULL`): başka bir işlem (gömme kuyruğu ya da metin onarımı) aynı parçayı değiştirdiyse bu yazım
sessizce atlanır, eski metnin vektörü yeni metne yazılmaz. Yeniden başlatılabilir. `legislation_chunk_vectors` tetikleyiciyle eşlenir;
bge-m3 vektörü `scripts/embed_legislation_m3.py` ile ayrıca doldurulur.

  python scripts/embed_missing_legislation.py              # hepsi
  python scripts/embed_missing_legislation.py --limit 500  # deneme
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.db import admin_database_connection  # noqa: E402
from scripts.repair_next_article_captions import BATCH, MODEL, embed, vector_literal  # noqa: E402

PAGE = 400
_TARGETS = """
SELECT k.id
FROM legal_sources s JOIN legal_chunks k ON k.legal_source_id = s.id
WHERE s.source_type = 'legislation' AND s.ingest_status = 'ready' AND k.embedding IS NULL
"""
_CONTENT = "SELECT id, content, content_hash FROM legal_chunks WHERE id = ANY(%s) AND embedding IS NULL ORDER BY id"
_UPDATE = (
    "UPDATE legal_chunks SET embedding = %s::vector, embedding_model = %s, embedding_created_at = %s "
    "WHERE id = %s AND content_hash IS NOT DISTINCT FROM %s AND embedding IS NULL"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--shard", default="0/1", help="i/N: kimliğin N'ye bölümünden kalanı i olan parçalar (paralel çalıştırma)")
    args = parser.parse_args()
    shard_index, shard_count = (int(part) for part in args.shard.split("/"))
    done = written = skipped = errors = 0
    started = time.time()
    with admin_database_connection() as connection:
        connection.execute("SET statement_timeout = 0")
        connection.commit()
        connection.autocommit = True
        # Hedef listesi tek sorguyla alınır (sayfalı tarama 22 milyon satırlık tabloyu her sayfada yeniden gezer).
        targets = sorted(row["id"] for row in connection.execute(_TARGETS).fetchall())
        targets = [chunk_id for chunk_id in targets if chunk_id.int % shard_count == shard_index]
        print(f"{len(targets)} parça gömülecek (parça {args.shard})", flush=True)
        for page_start in range(0, len(targets), PAGE):
            rows = connection.execute(_CONTENT, (targets[page_start : page_start + PAGE],)).fetchall()
            for start in range(0, len(rows), BATCH):
                part = rows[start : start + BATCH]
                try:
                    vectors = embed([row["content"] for row in part])
                except Exception as exc:  # noqa: BLE001 - sorunlu grup atlanır, sonraki çalıştırmada yeniden denenir
                    errors += len(part)
                    print(f"  gömme hatası ({len(part)} parça): {exc}", flush=True)
                    continue
                for row, vector in zip(part, vectors):
                    cursor = connection.execute(_UPDATE, (vector_literal(vector), MODEL, datetime.now(timezone.utc), row["id"], row["content_hash"]))
                    if cursor.rowcount:
                        written += 1
                    else:
                        skipped += 1
                done += len(part)
            print(f"  {done} parça işlendi, {written} yazıldı, {skipped} atlandı, {errors} hata ({time.time() - started:.0f} sn)", flush=True)
            if args.limit and done >= args.limit:
                break
    print("BİTTİ", {"işlenen": done, "yazılan": written, "atlanan": skipped, "hata": errors}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
