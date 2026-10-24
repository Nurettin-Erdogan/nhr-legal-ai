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
import json
import os
import signal
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

STOP = False
WRITE_WORKERS = int(os.getenv("EMBED_WRITE_WORKERS", "4"))
WRITE_QUEUE = int(os.getenv("EMBED_WRITE_QUEUE", "8"))
SHARD_PROGRESS_DIR = ROOT / "data" / "cache"


def read_all_shard_progress() -> dict[str, list]:
    snapshot: dict[str, list] = {}
    for path in SHARD_PROGRESS_DIR.glob("embed_shard_*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            snapshot[path.stem] = [raw["started"], raw["done"]]
        except (OSError, ValueError, KeyError):
            continue
    return snapshot


def write_embedded_base(url: str) -> None:
    """Kesin 'embedding hazır' sayısı (admin bağlantısı, ~10-30 sn) + o andaki işçi ilerlemesi.

    API bu sayıya işçilerin sonradan ürettiklerini ekler (api/legal.py `_live_embedded_count`).
    Sayım başlamadan önceki ilerleme kaydedilir: sayım o anın görüntüsünü görür.
    """
    try:
        snapshot = read_all_shard_progress()
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute("SET statement_timeout = '600s'")
            count = connection.execute("SELECT count(*) FROM legal_chunks WHERE embedding IS NOT NULL").fetchone()[0]
        target = SHARD_PROGRESS_DIR / "embed_base.json"
        tmp = target.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"count": count, "snapshot": snapshot, "ts": time.time()}), encoding="utf-8")
        tmp.replace(target)
    except (OSError, psycopg.Error):
        pass


def write_shard_progress(shard: int, started: float, done: int) -> None:
    """Dilimin ürettiği parça sayısı; API bunu son kesin sayıma ekleyerek sayacı canlı tutar."""
    try:
        SHARD_PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
        target = SHARD_PROGRESS_DIR / f"embed_shard_{shard}.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps({"started": started, "done": done}), encoding="utf-8")
        tmp.replace(target)
    except OSError:
        pass


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
    parser.add_argument("--include-seeds", action="store_true", help="--loop: resmî işler bitince doğrulanmamış (bulk_seed) kayıtları da çevir (en yeniden eskiye)")
    parser.add_argument("--seed-batch-sources", type=int, default=400, help="--include-seeds: bir turda kaç kaynak")
    parser.add_argument("--limit", type=int, default=0, help="0 = sınırsız")
    args = parser.parse_args()
    shard, shards = (int(part) for part in args.shard.split("/"))

    from api.ai.embeddings import EmbeddingProviderError, create_embedding_provider, vector_literal
    from api.config import get_settings
    from api.embed_pause import wait_if_embeddings_paused

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
    writers = ThreadPoolExecutor(max_workers=WRITE_WORKERS)
    pending: deque = deque()
    local = threading.local()

    def write_batch(params: list) -> None:
        connection_w = getattr(local, "connection", None)
        if connection_w is None or connection_w.closed:
            connection_w = psycopg.connect(url, autocommit=True)
            connection_w.execute("SET synchronous_commit = off")
            local.connection = connection_w
        with connection_w.transaction(), connection_w.cursor() as cur:
            cur.executemany(
                "UPDATE legal_chunks SET embedding = %s::vector, embedding_model = %s, "
                "embedding_created_at = NOW() WHERE id = %s AND embedding IS NULL",
                params,
            )

    def drain_writes() -> None:
        while pending:
            pending.popleft().result()

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

    resume_path = ROOT / "data" / "campaign" / f"embed-official-resume-{shard}of{shards}.json"

    def run_pass(connection: psycopg.Connection, source_ids: list, *, resumable: bool = False) -> None:
        nonlocal done, skipped
        # Yeniden başlatmada tam taramayı baştan yapmamak için son tamamlanan kaynak kimliği saklanır (2026-10-19:
        # her başlatmada 160 bin kaynak yeniden taranıyor, ilk ~20 dk hiç parça üretilmiyordu).
        if resumable and resume_path.exists():
            try:
                last_id = json.loads(resume_path.read_text(encoding="utf-8")).get("last_id")
            except (OSError, ValueError):
                last_id = None
            if last_id:
                source_ids = [sid for sid in source_ids if str(sid) > last_id]
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
                wait_if_embeddings_paused()  # asistan cevap üretirken GPU'yu ona bırak
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
                # Yazma darboğazı (2026-10-19): her UPDATE tüm dizinleri (HNSW + GIN) günceller, tek bağlantıyla ~6 parça/sn;
                # GPU %5 boşta. Vektörler üretilirken yazmalar paralel bağlantılarla yapılır.
                params = [(vector_literal(v), provider.model, row[0]) for row, v in zip(batch, vectors, strict=True)]
                while len(pending) >= WRITE_QUEUE:
                    pending.popleft().result()
                pending.append(writers.submit(write_batch, params))
                done += len(batch)
                write_shard_progress(shard, started, done)  # API sayacı her partide ilerler
            drain_writes()
            if resumable and group:
                resume_path.write_text(json.dumps({"last_id": str(group[-1])}), encoding="utf-8")
            elapsed = time.time() - started
            print(
                f"{time.strftime('%H:%M:%S')} kaynak {offset + len(group):,}/{len(source_ids):,} | "
                f"embedding üretilen={done:,} | {done / max(elapsed, 1):.1f} parça/sn | {elapsed / 60:.0f} dk",
                flush=True,
            )

    base_cursor = ROOT / "data" / "campaign" / "embed-seed-cursor.json"
    # Dilimli çalışmada her işçinin kendi imleci vardır; hepsi aynı noktadan (varsa eski imleçten) başlar
    # ve aynı sıralamayı izler, gruplar dilimlere (grup indeksi mod N) bölündüğü için çakışmazlar.
    cursor_path = base_cursor if shards == 1 else base_cursor.with_name(f"embed-seed-cursor-{shard}of{shards}.json")
    if shards > 1 and not cursor_path.exists() and base_cursor.exists():
        cursor_path.write_text(base_cursor.read_text(encoding="utf-8"), encoding="utf-8")

    def seed_batch(connection: psycopg.Connection, count: int) -> int:
        """Doğrulanmamış (bulk_seed) kayıtları en yeni karardan eskiye, imleçle çevirir.

        İmleç (decision_date, legal_source_id) `data/campaign/embed-seed-cursor.json` içinde
        durur; süreç yeniden başlarsa kaldığı yerden sürer. Döndürdüğü sayı 0 ise bitti.
        """
        cursor: dict = {}
        if cursor_path.exists():
            try:
                cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cursor = {}
        after = ""
        params: list = []
        if cursor.get("date") and cursor.get("id"):
            after = "AND (d.decision_date, d.legal_source_id) < (%s::date, %s::uuid)"
            params += [cursor["date"], cursor["id"]]
        params.append(count)
        rows = connection.execute(
            f"""
            SELECT d.legal_source_id, d.decision_date
            FROM court_decision_details d
            JOIN legal_sources s ON s.id = d.legal_source_id
            WHERE d.decision_date IS NOT NULL
              AND s.ingestion_method = 'bulk_seed' AND s.ingest_status = 'pending'
              AND s.is_current AND s.deleted_at IS NULL
              {after}
            ORDER BY d.decision_date DESC, d.legal_source_id DESC
            LIMIT %s
            """,
            params,
        ).fetchall()
        if not rows:
            return 0
        run_pass(connection, [row[0] for row in rows])
        last = rows[-1]
        cursor_path.write_text(json.dumps({"date": last[1].isoformat(), "id": str(last[0])}), encoding="utf-8")
        return len(rows)

    if shard == 0:
        def base_loop() -> None:
            # Kesin sayım 28,8 milyon satırı tarar (görünürlük haritası eksikken 4-5 dk, işlemci %100) ve aynı anda başka
            # sayımlarla üst üste binince aramayı ~5 kat yavaşlattı (2026-10-10). Bu yüzden: dosya 6 saatten tazeyse sayılmaz
            # (işçi yeniden başlasa da tekrar saymaz), sayımlar en erken 6 saatte bir yapılır.
            target = SHARD_PROGRESS_DIR / "embed_base.json"
            while not STOP:
                try:
                    age = time.time() - target.stat().st_mtime
                except OSError:
                    age = 1e9
                if age >= 6 * 3600:
                    write_embedded_base(url)
                for _ in range(900):  # 15 dk'da bir dosya tazeliği yeniden bakılır; durdurmada hızlı çıkış
                    if STOP:
                        return
                    time.sleep(1)

        threading.Thread(target=base_loop, name="embed-base-count", daemon=True).start()

    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("SET statement_timeout = '900s'")
        run_pass(connection, source_ids_for(connection, None), resumable=True)
        resume_path.unlink(missing_ok=True)  # tam tur bitti: sonraki tam tarama baştan
        last_full = time.time()
        last_light = time.time()
        while args.loop and not STOP:
            # Önce resmî kayıtlar (yeni doğrulanan/eklenen: hafif tur; ara sıra tam tarama), sonra
            # --include-seeds ile doğrulanmamışlar. Çevrilecek iş varken beklemeden sürer.
            worked = 0
            now = time.time()
            if now - last_light >= args.loop_interval:
                if now - last_full >= args.full_every_hours * 3600:
                    ids, last_full = source_ids_for(connection, None), now
                    resume_path.unlink(missing_ok=True)
                else:
                    since = datetime.fromtimestamp(last_light - 600, UTC).isoformat()
                    ids = source_ids_for(connection, since)
                last_light = now
                if ids:
                    run_pass(connection, ids)
                    worked += len(ids)
            if args.include_seeds and not STOP:
                worked += seed_batch(connection, args.seed_batch_sources)
            if not worked:
                time.sleep(min(args.loop_interval, 30))
    print(f"BİTTİ: {done:,} parça, atlanan {skipped:,} | {(time.time() - started) / 60:.0f} dk", flush=True)
    return 0


def _run_forever() -> int:
    """Beklenmeyen hata (veritabanı zaman aşımı, bağlantı kopması) işçiyi öldürmesin: nedeni kalıcı dosyaya
    yazılır, kısa beklemeden sonra yeniden bağlanıp kaldığı yerden (imleç dosyadan) devam edilir."""
    import traceback

    crash_log = ROOT / "data" / "logs" / f"embed-crash-{sys.argv[sys.argv.index('--shard') + 1].replace('/', 'of')}.log" if "--shard" in sys.argv else ROOT / "data" / "logs" / "embed-crash.log"
    while True:
        try:
            return main()
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception:  # noqa: BLE001
            with crash_log.open("a", encoding="utf-8") as handle:
                handle.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{traceback.format_exc()}\n")
            print(f"{time.strftime('%H:%M:%S')} hata (crash logu yazıldı); 20 sn sonra yeniden bağlanılıyor", flush=True)
            if STOP:
                return 1
            time.sleep(20)


if __name__ == "__main__":
    raise SystemExit(_run_forever())
