"""Mevzuat maddelerindeki bölünmüş sözcükleri ("tarafı ndan", "Kanu nun") birleştirir ve parçaları yeniden gömer.

Kural ve güvenceler `ingestion.mevzuat.word_repair` içinde: yalnız korpusta doğrulanan sözcükler birleştirilir ve her kayıtta,
boşluklar çıkarılınca eski ve yeni metnin birebir aynı olduğu doğrulanır (harf değişmez). Uygulama biçimi
`scripts/repair_next_article_captions.py` ile aynıdır (tek transaction, yedek, nomic vektörü anında yeniden üretilir, bge-m3 sıfırlanır).
`metadata.word_rejoin` neyin birleştirildiğini yazar (geri alınabilir). Kanıt kaydındaki `article_hash` yeni özetle güncellenir; kanıtta
`normalization` listesine "word_rejoin" eklenir.

Başlık sızıntısı düzeltmesi (`repair_next_article_captions.py`) bitmeden çalıştırılmaz: ikisi aynı satırlara dokunur.
Varsayılan kuru çalıştırmadır: `--apply` verilmedikçe hiçbir şey yazılmaz.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psycopg.types.json import Jsonb  # noqa: E402

from api.db import admin_database_connection  # noqa: E402
from ingestion.mevzuat.word_repair import build_vocabulary, only_spaces_removed, rejoin_split_words  # noqa: E402
from ingestion.text import content_hash  # noqa: E402
from ingestion.yargitay.chunking import chunk_text  # noqa: E402
from scripts.repair_next_article_captions import BATCH, CHUNK_SIZES, MODEL, embed, vector_literal  # noqa: E402


def plan_source(source: dict, chunks: list[dict], vocabulary) -> dict | None:
    old = source["raw_text"]
    new, joins = rejoin_split_words(old, vocabulary)
    if new == old:
        return None
    if not only_spaces_removed(old, new):
        return {"skip": "birleştirme harf değiştirdi"}
    if source["content_hash"] != content_hash(old):
        return {"skip": "kayıtlı özet metinle uyuşmuyor"}
    old_contents = [chunk["content"] for chunk in chunks]
    size = next((s for s in CHUNK_SIZES if [c.content for c in chunk_text(old, max_chars=s)] == old_contents), None)
    if size is None:
        return {"skip": "eski parçalama yeniden üretilemedi"}
    new_chunks = chunk_text(new, max_chars=size)
    if not new_chunks:
        return {"skip": "düzeltilmiş metin boş"}
    return {"new": new, "new_hash": content_hash(new), "joins": [[j.kind, j.left, j.fragment] for j in joins], "size": size,
            "new_chunks": new_chunks}


def apply_source(connection, source: dict, chunks: list[dict], plan: dict, vectors: dict[str, list[float]]) -> None:
    new_chunks = plan["new_chunks"]
    surplus = chunks[len(new_chunks):]
    with connection.transaction():
        guard = connection.execute("SELECT 1 FROM legal_sources WHERE id = %s AND content_hash = %s FOR UPDATE", (source["id"], source["content_hash"])).fetchone()
        if guard is None:
            raise RuntimeError("kayıt başka işlem tarafından değiştirilmiş")
        if surplus:
            cited = connection.execute("SELECT 1 FROM citations WHERE legal_chunk_id = ANY(%s) LIMIT 1", ([c["id"] for c in surplus],)).fetchone()
            if cited:
                raise RuntimeError("fazla parçaya atıf bağlı")
            connection.execute("DELETE FROM legal_chunks WHERE id = ANY(%s)", ([c["id"] for c in surplus],))
        for new_chunk, old_chunk in zip(new_chunks, chunks):
            if new_chunk.content == old_chunk["content"]:
                continue
            vector = vectors.get(new_chunk.content_hash)
            connection.execute(
                "UPDATE legal_chunks SET content=%s, content_hash=%s, paragraph_start=%s, paragraph_end=%s, token_count=NULL, "
                "embedding=%s::vector, embedding_model=%s, embedding_created_at=%s WHERE id=%s",
                (new_chunk.content, new_chunk.content_hash, new_chunk.paragraph_start, new_chunk.paragraph_end,
                 vector_literal(vector) if vector else None, MODEL if vector else None,
                 datetime.now(timezone.utc) if vector else None, old_chunk["id"]),
            )
        metadata = dict(source["metadata"] or {})
        proof = metadata.get("mbs_text_verification")
        if isinstance(proof, dict) and proof.get("article_hash") == source["content_hash"]:
            metadata["mbs_text_verification"] = {**proof, "article_hash": plan["new_hash"],
                                                 "normalization": sorted({*proof.get("normalization", []), "word_rejoin"})}
        metadata["word_rejoin"] = {"joins": plan["joins"], "previous_content_hash": source["content_hash"],
                                   "repaired_at": datetime.now(timezone.utc).isoformat()}
        connection.execute("UPDATE legal_sources SET raw_text=%s, content_hash=%s, metadata=%s WHERE id=%s",
                           (plan["new"], plan["new_hash"], Jsonb(metadata), source["id"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Yazar (varsayılan kuru çalıştırma)")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--law-no")
    parser.add_argument("--shard", default="0/1", help="i/N: kayıt kimliğinin N'ye bölümünden kalanı i olanları işle (paralel çalıştırma)")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = ROOT / ".local" / "corpus-repair-backups" / f"word-rejoin-{stamp}.jsonl"
    stats = {"scanned": 0, "changed": 0, "applied": 0, "skipped": 0, "joins": 0, "chunks_changed": 0}
    skips: dict[str, int] = {}
    started = time.time()
    with admin_database_connection() as connection:
        connection.execute("SET statement_timeout = 0")
        connection.commit()
        connection.autocommit = True
        print("sözlük kuruluyor…", flush=True)
        # Akışla oku (tüm metni belleğe yüklemek 230 bin maddede süreç başına ~1 GB tutuyordu).
        with connection.transaction():
            with connection.cursor(name="vocab_scan") as scan:
                scan.itersize = 300
                scan.execute("SELECT raw_text FROM legal_sources WHERE source_type = 'legislation' AND ingest_status = 'ready' "
                             "AND is_current AND raw_text IS NOT NULL")
                vocabulary = build_vocabulary(row["raw_text"] for row in scan)
        query = ("SELECT s.id, s.raw_text, s.content_hash, s.metadata, s.title FROM legal_sources s "
                 + ("JOIN legislation_details d ON d.legal_source_id = s.id AND d.law_no = %s " if args.law_no else "")
                 + "WHERE s.source_type = 'legislation' AND s.raw_text IS NOT NULL ORDER BY s.id")
        shard_index, shard_count = (int(part) for part in args.shard.split("/"))
        pending = []
        with connection.transaction():
            with connection.cursor(name="split_scan") as scan:
                scan.itersize = 300
                scan.execute(query, (args.law_no,) if args.law_no else ())
                for source in scan:
                    stats["scanned"] += 1
                    if source["id"].int % shard_count != shard_index:
                        continue
                    if rejoin_split_words(source["raw_text"], vocabulary)[0] != source["raw_text"]:
                        pending.append(source)
        stats["changed"] = len(pending)
        if args.limit:
            pending = pending[: args.limit]
        backup = None
        if args.apply:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            backup = backup_path.open("a", encoding="utf-8")
        for offset in range(0, len(pending), 50):
            batch = pending[offset : offset + 50]
            plans = []
            for source in batch:
                chunks = connection.execute(
                    "SELECT id, chunk_index, content, content_hash, paragraph_start, paragraph_end FROM legal_chunks "
                    "WHERE legal_source_id = %s ORDER BY chunk_index", (source["id"],)).fetchall()
                plan = plan_source(source, chunks, vocabulary)
                if plan is None:
                    continue
                if "skip" in plan:
                    stats["skipped"] += 1
                    skips[plan["skip"]] = skips.get(plan["skip"], 0) + 1
                    continue
                plans.append((source, chunks, plan))
                stats["joins"] += len(plan["joins"])
            if not args.apply:
                stats["applied"] += len(plans)
                continue
            texts_by_hash = {}
            for _, chunks, plan in plans:
                for new_chunk, old_chunk in zip(plan["new_chunks"], chunks):
                    if new_chunk.content != old_chunk["content"]:
                        texts_by_hash[new_chunk.content_hash] = new_chunk.content
            vectors: dict[str, list[float]] = {}
            keys = list(texts_by_hash)
            for start in range(0, len(keys), BATCH):
                part = keys[start : start + BATCH]
                try:
                    for key, vector in zip(part, embed([texts_by_hash[k] for k in part])):
                        vectors[key] = vector
                except Exception as exc:  # noqa: BLE001 - vektörsüz kalan parça gömme kuyruğuna düşer (embedding NULL)
                    print(f"  gömme hatası ({len(part)} parça): {exc}", flush=True)
            for source, chunks, plan in plans:
                backup.write(json.dumps({"id": str(source["id"]), "title": source["title"], "raw_text": source["raw_text"],
                                         "content_hash": source["content_hash"], "metadata": source["metadata"],
                                         "chunks": [{**c, "id": str(c["id"])} for c in chunks]}, ensure_ascii=False, default=str) + "\n")
                backup.flush()
                os.fsync(backup.fileno())
                try:
                    apply_source(connection, source, chunks, plan, vectors)
                    stats["applied"] += 1
                    stats["chunks_changed"] += sum(1 for n, o in zip(plan["new_chunks"], chunks) if n.content != o["content"])
                except Exception as exc:  # noqa: BLE001
                    stats["skipped"] += 1
                    skips[str(exc)[:80]] = skips.get(str(exc)[:80], 0) + 1
            print(f"  {min(offset + 50, len(pending))}/{len(pending)}  ({time.time() - started:.0f} sn)", flush=True)
        if backup:
            backup.close()
    print(("UYGULANDI" if args.apply else "KURU ÇALIŞTIRMA"), stats, skips, flush=True)
    if args.apply:
        print("yedek:", backup_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
