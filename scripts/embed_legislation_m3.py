"""Mevzuat parçalarının ikinci anlam vektörünü (bge-m3, 1024 boyut) üretir — migration 061.

Yalnız `legislation_chunk_vectors.embedding_m3 IS NULL` olan parçalar işlenir; yeniden başlatılabilir. Önce güncel
maddeler. Yerel Ollama'da ~30 parça/sn (2026-10-22 ölçümü: 4.025 parça 133 sn); 109 bin parça ~1 saat. Yazma yalnız
nhr_app ile (DATABASE_ADMIN_URL); uygulama rolü bu tabloya yazamaz.

  python scripts/embed_legislation_m3.py              # hepsi
  python scripts/embed_legislation_m3.py --limit 500  # deneme
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.ai.embeddings import EmbeddingProviderError, create_embedding_provider  # noqa: E402
from api.config import get_settings  # noqa: E402

MODEL, DIMENSIONS, MAX_CHARS = "bge-m3", 1024, 8000
_stop = False


def _handle_stop(*_args) -> None:
    global _stop
    _stop = True


PENDING_SQL = """
SELECT vector.chunk_id, chunk.content
FROM legislation_chunk_vectors vector
JOIN legal_chunks chunk ON chunk.id = vector.chunk_id
JOIN legal_sources ls ON ls.id = vector.legal_source_id
WHERE vector.embedding_m3 IS NULL
ORDER BY ls.is_current DESC, vector.chunk_id
LIMIT %s
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=0, help="en çok bu kadar parça (0 = hepsi)")
    parser.add_argument("--batch", type=int, default=32)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL tanımlı değil")
    provider = create_embedding_provider(provider_name="ollama", model=MODEL, dimensions=DIMENSIONS,
                                         ollama_base_url=get_settings().ollama_base_url)
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    done, started = 0, time.time()
    with psycopg.connect(url, autocommit=True) as connection:
        remaining = connection.execute(
            "SELECT count(*) FROM legislation_chunk_vectors WHERE embedding_m3 IS NULL").fetchone()[0]
        print(f"bekleyen {remaining} parça", flush=True)
        while not _stop and (not args.limit or done < args.limit):
            size = args.batch if not args.limit else min(args.batch, args.limit - done)
            rows = connection.execute(PENDING_SQL, (size,)).fetchall()
            if not rows:
                break
            try:
                vectors = provider.embed_documents([content[:MAX_CHARS] for _, content in rows])
            except EmbeddingProviderError as exc:
                print(f"embedding hatası: {exc}; 30 sn sonra yeniden", flush=True)
                time.sleep(30)
                continue
            with connection.cursor() as cursor:
                cursor.executemany(
                    "UPDATE legislation_chunk_vectors SET embedding_m3 = %s::vector "
                    "WHERE chunk_id = %s AND embedding_m3 IS NULL",
                    [("[" + ",".join(f"{v:.7f}" for v in vector) + "]", chunk_id)
                     for (chunk_id, _), vector in zip(rows, vectors)])
            done += len(rows)
            if done % (args.batch * 20) < args.batch:
                rate = done / max(time.time() - started, 1)
                print(f"{done} parça, {rate:.1f}/sn, kalan ~{(remaining - done) / max(rate, 0.1) / 60:.0f} dk", flush=True)
    print(f"bitti: {done} parça, {time.time() - started:.0f} sn", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
