"""Parçalar için embedding üretir (anlamsal arama). Öncelik: resmî doğrulanmış kayıtlar.

Yerel Ollama modeliyle saniyede ~40 parça (nomic-embed-text, 2026-09-20 ölçümü). 21,5 milyon
parçanın hepsi ~6 gün eder ve asistanın üretim modeliyle aynı makineyi paylaşır; bu yüzden
varsayılan kapsam yalnız resmî (`ready`) kayıtlardır. Yeniden başlatılabilir: yalnız
`embedding IS NULL` olan parçalar işlenir.

  python scripts/embed_chunks.py                    # resmî kayıtlar (varsayılan)
  python scripts/embed_chunks.py --limit 2000       # deneme
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

STOP = False


def _handle_stop(signum: int, _frame: object) -> None:
    global STOP
    STOP = True
    print(f"durdurma sinyali ({signum}); mevcut gruptan sonra çıkılıyor", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", type=int, default=32, help="Ollama isteği başına parça")
    parser.add_argument("--sources-per-group", type=int, default=50, help="Bir transaction'da işlenen kaynak sayısı")
    parser.add_argument("--shard", default="0/1", help="K/N: kaynak gruplarının yalnız K. dilimi (paralel süreçler için)")
    parser.add_argument("--loop", action="store_true", help="Sürekli çalış: her turda son değişen resmî kayıtları embedding'e çevirir")
    parser.add_argument("--loop-interval", type=int, default=180, help="--loop turları arası saniye")
    parser.add_argument("--full-every-hours", type=float, default=6.0, help="--loop: tüm resmî kayıtları yeniden tarama aralığı")
    parser.add_argument("--limit", type=int, default=0, help="0 = sınırsız")
    args = parser.parse_args()
    shard, shards = (int(part) for part in args.shard.split("/"))

    from api.ai.embeddings import EmbeddingProviderError, create_embedding_provider, vector_literal
    from api.config import get_settings

    settings = get_settings()
    provider = create_embedding_provider(
        provider_name=settings.embedding_provider,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        ollama_base_url=settings.ollama_base_url,
    )
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL tanımlı değil")

    done = 0
    skipped = 0
    started = time.time()

    def source_ids_for(connection: psycopg.Connection, since: str | None) -> list:
        # since=None: tüm resmî kayıtlar; aksi hâlde yalnız o zamandan beri değişenler (yeni
        # doğrulanan ya da kampanyanın yeni eklediği kayıtlar).
        extra = "AND updated_at >= %s::timestamptz" if since else ""
        params = (since,) if since else ()
        return [
            row[0]
            for row in connection.execute(
                f"""
                SELECT id FROM legal_sources
                WHERE ingest_status = 'ready' AND is_current AND deleted_at IS NULL {extra}
                ORDER BY id
                """,
                params,
            ).fetchall()
        ]

    def run_pass(connection: psycopg.Connection, source_ids: list) -> None:
        nonlocal done, skipped
        print(f"resmî kaynak: {len(source_ids):,}; model={provider.model}", flush=True)
        for offset in range(0, len(source_ids), args.sources_per_group):
            if STOP or (args.limit and done >= args.limit):
                break
            if (offset // args.sources_per_group) % shards != shard:
                continue
            group = source_ids[offset : offset + args.sources_per_group]
            rows = connection.execute(
                "SELECT id, content FROM legal_chunks WHERE legal_source_id = ANY(%s) AND embedding IS NULL",
                (group,),
            ).fetchall()
            for start in range(0, len(rows), args.batch):
                if STOP:
                    break
                batch = rows[start : start + args.batch]
                try:
                    vectors = provider.embed_documents([row[1] for row in batch])
                except EmbeddingProviderError:
                    # Tek bir sorunlu parça (Ollama HTTP 400) tüm partiyi düşürmesin: teker teker dene.
                    good, vectors = [], []
                    for row in batch:
                        try:
                            vectors.extend(provider.embed_documents([row[1]]))
                            good.append(row)
                        except EmbeddingProviderError as exc:
                            skipped += 1
                            print(f"atlandı: parça {row[0]} ({exc})", flush=True)
                    batch = good
                if len(vectors) != len(batch) or any(len(v) != provider.dimensions for v in vectors):
                    raise RuntimeError("Embedding sayısı/boyutu beklenenle eşleşmiyor")
                if not batch:
                    continue
                with connection.transaction(), connection.cursor() as cur:
                    cur.executemany(
                        "UPDATE legal_chunks SET embedding = %s::vector, embedding_model = %s, "
                        "embedding_created_at = NOW() WHERE id = %s",
                        [(vector_literal(v), provider.model, row[0]) for row, v in zip(batch, vectors, strict=True)],
                    )
                done += len(batch)
            elapsed = time.time() - started
            print(
                f"{time.strftime('%H:%M:%S')} kaynak {offset + len(group):,}/{len(source_ids):,} | "
                f"embedding üretilen={done:,} | {done / max(elapsed, 1):.1f} parça/sn | {elapsed / 60:.0f} dk",
                flush=True,
            )

    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("SET statement_timeout = '120s'")
        run_pass(connection, source_ids_for(connection, None))
        last_full = time.time()
        while args.loop and not STOP:
            # Yeni doğrulanan/eklenen kayıtlar için hafif tur; ara sıra tam tarama (atlananlar için).
            time.sleep(args.loop_interval)
            if STOP:
                break
            pass_started = time.time()
            if pass_started - last_full >= args.full_every_hours * 3600:
                ids, last_full = source_ids_for(connection, None), pass_started
            else:
                since = datetime.fromtimestamp(pass_started - args.loop_interval - 600, UTC).isoformat()
                ids = source_ids_for(connection, since)
            if ids:
                run_pass(connection, ids)
    print(f"BİTTİ: {done:,} parça, atlanan {skipped:,} | {(time.time() - started) / 60:.0f} dk", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
