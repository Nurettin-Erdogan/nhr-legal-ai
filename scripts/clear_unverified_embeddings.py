"""Doğrulanmamış (ingest_status <> 'ready') kayıtların embedding'lerini temizler.

Parça metni (`content`) ve arama vektörü (`search_vector`) korunur; yalnız `embedding`,
`embedding_model` ve `embedding_created_at` boşaltılır. Böylece bu kayıtlar anahtar kelimeyle
aranabilir kalır, anlamsal aramaya girmez. Embedding daha sonra yeniden üretilebilir.

Sıra: (1) HNSW indeksi düşürülür (ölü girdilerle 22 GB büyümüş olur), (2) parçalar küçük
gruplarla boşaltılır, kontrol noktası dosyasından sürdürülebilir, (3) `--rebuild` ile HNSW indeksi
yalnız kalan (resmî) vektörlerle yeniden kurulur.

Kullanım (embedding, sentinel ve doğrulayıcılar durdurulmuş olmalı):
    python scripts/clear_unverified_embeddings.py --count          # yalnız say
    python scripts/clear_unverified_embeddings.py --run            # temizle (sürdürülebilir)
    python scripts/clear_unverified_embeddings.py --rebuild        # HNSW'yi yeniden kur
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "data" / "cache" / "clear_unverified_embeddings.json"
HNSW = "idx_legal_chunks_embedding_hnsw"

_NEXT_BATCH = """
SELECT c.id
FROM legal_chunks c
JOIN legal_sources s ON s.id = c.legal_source_id
WHERE c.embedding IS NOT NULL
  AND c.id > %s
  AND s.ingest_status <> 'ready'
ORDER BY c.id
LIMIT %s
"""


def _connect() -> psycopg.Connection:
    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        sys.exit("DATABASE_ADMIN_URL tanımlı değil")
    return psycopg.connect(url, autocommit=True)


def _load_checkpoint() -> dict:
    try:
        return json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"last_id": "00000000-0000-0000-0000-000000000000", "cleared": 0}


def _save_checkpoint(state: dict) -> None:
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(json.dumps(state), encoding="utf-8")


def count(connection: psycopg.Connection) -> None:
    connection.execute("SET statement_timeout = '600s'")
    row = connection.execute(
        "SELECT count(*) FILTER (WHERE s.ingest_status = 'ready'), "
        "count(*) FILTER (WHERE s.ingest_status <> 'ready') "
        "FROM legal_chunks c JOIN legal_sources s ON s.id = c.legal_source_id "
        "WHERE c.embedding IS NOT NULL"
    ).fetchone()
    print(f"embedding'i olan parça: resmî(ready)={row[0]:,}  doğrulanmamış={row[1]:,}", flush=True)


def run(connection: psycopg.Connection, batch: int) -> None:
    connection.execute("SET statement_timeout = 0")
    connection.execute("SET lock_timeout = '10s'")
    connection.execute("SET synchronous_commit = off")
    print(f"{HNSW} düşürülüyor (ölü girdilerle şişmiş, yeniden kurulacak)…", flush=True)
    connection.execute(f"DROP INDEX IF EXISTS {HNSW}")
    state = _load_checkpoint()
    started = time.monotonic()
    while True:
        ids = [row[0] for row in connection.execute(_NEXT_BATCH, (state["last_id"], batch)).fetchall()]
        if not ids:
            break
        connection.execute(
            "UPDATE legal_chunks SET embedding = NULL, embedding_model = NULL, "
            "embedding_created_at = NULL WHERE id = ANY(%s)",
            (ids,),
        )
        state["last_id"] = str(ids[-1])
        state["cleared"] += len(ids)
        _save_checkpoint(state)
        elapsed = time.monotonic() - started
        print(f"temizlenen={state['cleared']:,}  hız={state['cleared'] / max(elapsed, 1):,.0f}/sn", flush=True)
    print("temizlik bitti. Sıradaki adım: --rebuild", flush=True)


def rebuild(connection: psycopg.Connection) -> None:
    connection.execute("SET statement_timeout = 0")
    connection.execute("SET maintenance_work_mem = '3GB'")
    connection.execute("SET max_parallel_maintenance_workers = 0")
    print("HNSW indeksi kuruluyor (yalnız kalan vektörler)…", flush=True)
    started = time.monotonic()
    connection.execute(
        f"CREATE INDEX IF NOT EXISTS {HNSW} ON legal_chunks USING hnsw (embedding vector_cosine_ops) "
        "WHERE (embedding IS NOT NULL)"
    )
    print(f"indeks hazır ({(time.monotonic() - started) / 60:.1f} dk)", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--batch", type=int, default=20000)
    args = parser.parse_args()
    if not (args.count or args.run or args.rebuild):
        parser.print_help()
        return
    with _connect() as connection:
        if args.count:
            count(connection)
        if args.run:
            run(connection, args.batch)
        if args.rebuild:
            rebuild(connection)


if __name__ == "__main__":
    main()
