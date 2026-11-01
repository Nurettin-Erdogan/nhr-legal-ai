"""Mevzuat maddelerinin sonuna yapışmış "sonraki maddenin başlığı"nı atar (ve parçaları yeniden gömer).

Resmî PDF'te madde başlığı "Madde 19 -" satırından önce gelir; madde metni bir sonraki başlık konumuna kadar kesildiğinden m.18'in
sonunda m.19'un başlığı ("Sözleşmenin feshinde usul") kalıyordu. Kural `ingestion.mevzuat.text_verify.strip_next_article_caption`.

Her etkilenen kayıt için, tek transaction'da:
  - `legal_sources.raw_text` ve `content_hash` yenilenir; kanıt kaydındaki `article_hash` (varsa) yeni özetle değişir;
    `metadata.caption_trim` ile neyin atıldığı yazılır (geri alınabilir).
  - Parça(lar) aynı parçalama ayarıyla yeniden kurulur; değişen parçanın içeriği/özeti güncellenir ve nomic vektörü hemen yeniden
    üretilir (Ollama), bge-m3 vektörü tetikleyiciyle sıfırlanır (`scripts/embed_legislation_m3.py` yeniden doldurur).
  - Önceki hâli `.local/corpus-repair-backups/caption-trim-*.jsonl` yedeğine yazılır.
Parçalama ayarı eski parçalarla birebir doğrulanamayan ya da atıf bağı taşıyan fazla parça içeren kayıtlar atlanır ve raporlanır.

Varsayılan kuru çalıştırmadır: `--apply` verilmedikçe hiçbir şey yazılmaz.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psycopg.types.json import Jsonb  # noqa: E402

from api.db import admin_database_connection  # noqa: E402
from ingestion.mevzuat.text_verify import strip_next_article_caption  # noqa: E402
from ingestion.text import content_hash  # noqa: E402
from ingestion.yargitay.chunking import chunk_text  # noqa: E402

OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
DIMENSIONS = int(os.getenv("EMBED_DIMENSIONS", "768"))
CHUNK_SIZES = (1800, 16000)  # eski aktarımların kullandığı ayarlar (mevzuat varsayılanı ve resmî yenileme)
BATCH = 16


def embed(texts: list[str]) -> list[list[float]]:
    if os.getenv("NHR_NO_EMBED") == "1":  # gömme kapalıyken parça vektörsüz (NULL) kalır; gömme kuyruğu sonra doldurur
        return [None] * len(texts)  # type: ignore[list-item]
    body = json.dumps({"model": MODEL, "input": [t.strip() or "." for t in texts], "dimensions": DIMENSIONS, "truncate": True, "keep_alive": "30m"}).encode()
    request = urllib.request.Request(f"{OLLAMA}/api/embed", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=900) as response:
        vectors = json.loads(response.read())["embeddings"]
    if len(vectors) != len(texts) or any(len(v) != DIMENSIONS for v in vectors):
        raise RuntimeError("beklenmeyen embedding sayısı/boyutu")
    return vectors


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def plan_source(source: dict, chunks: list[dict]) -> dict | None:
    """Bir kaydın düzeltme planı; değişiklik yoksa None. Güvenle yapılamıyorsa {'skip': neden}."""
    old = source["raw_text"]
    new = strip_next_article_caption(old)
    if new == old:
        return None
    if source["content_hash"] != content_hash(old):
        return {"skip": "kayıtlı özet metinle uyuşmuyor"}
    old_contents = [chunk["content"] for chunk in chunks]
    size = next((s for s in CHUNK_SIZES if [c.content for c in chunk_text(old, max_chars=s)] == old_contents), None)
    if size is None:
        return {"skip": "eski parçalama yeniden üretilemedi"}
    new_chunks = chunk_text(new, max_chars=size)
    if not new_chunks:
        return {"skip": "düzeltilmiş metin boş"}
    return {"new": new, "new_hash": content_hash(new), "removed": old[len(new):].strip(), "size": size, "new_chunks": new_chunks}


def apply_source(connection, source: dict, chunks: list[dict], plan: dict, vectors: dict[str, list[float]]) -> str:
    new_chunks = plan["new_chunks"]
    surplus = chunks[len(new_chunks):]
    with connection.transaction():
        # Başka bir parça (shard) ya da işlem bu kaydı zaten değiştirdiyse hiçbir şey yazma (çift gömme ve eski metnin üzerine yazma olmasın).
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
            metadata["mbs_text_verification"] = {**proof, "article_hash": plan["new_hash"]}
        metadata["caption_trim"] = {"removed": plan["removed"], "previous_content_hash": source["content_hash"],
                                    "trimmed_at": datetime.now(timezone.utc).isoformat()}
        connection.execute("UPDATE legal_sources SET raw_text=%s, content_hash=%s, metadata=%s WHERE id=%s",
                           (plan["new"], plan["new_hash"], Jsonb(metadata), source["id"]))
    return "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Yazar (varsayılan kuru çalıştırma)")
    parser.add_argument("--limit", type=int, default=0, help="En çok bu kadar kayıt işle (0 = hepsi)")
    parser.add_argument("--law-no", help="Yalnız bu kanun numarası (ör. 4857)")
    parser.add_argument("--shard", default="0/1", help="i/N: kayıt kimliğinin N'ye bölümünden kalanı i olanları işle (paralel çalıştırma)")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = ROOT / ".local" / "corpus-repair-backups" / f"caption-trim-{stamp}.jsonl"
    stats = {"scanned": 0, "changed": 0, "applied": 0, "skipped": 0, "chunks_changed": 0}
    skips: dict[str, int] = {}
    started = time.time()
    with admin_database_connection() as connection:
        connection.execute("SET statement_timeout = 0")
        # Otomatik kayıt: aksi halde `connection.transaction()` dıştaki açık işlemin içinde kayıt noktasına dönüşür ve hiçbir kayıt
        # betik bitene kadar kalıcı olmaz (saatlerce açık işlem, kilitler, kesilirse hepsi kaybolur).
        connection.commit()
        connection.autocommit = True
        query = ("SELECT s.id, s.raw_text, s.content_hash, s.metadata, s.title FROM legal_sources s "
                 + ("JOIN legislation_details d ON d.legal_source_id = s.id AND d.law_no = %s " if args.law_no else "")
                 + "WHERE s.source_type = 'legislation' AND s.raw_text IS NOT NULL ORDER BY s.id")
        # Tüm metni belleğe almadan akışla tara (230 bin madde süreç başına ~1 GB tutuyordu): yalnız bu parçanın düzeltilecek kayıtları saklanır.
        shard_index, shard_count = (int(part) for part in args.shard.split("/"))
        pending = []
        with connection.transaction():
            with connection.cursor(name="caption_scan") as scan:
                scan.itersize = 300
                scan.execute(query, (args.law_no,) if args.law_no else ())
                for source in scan:
                    stats["scanned"] += 1
                    if source["id"].int % shard_count != shard_index:
                        continue
                    if strip_next_article_caption(source["raw_text"]) != source["raw_text"]:
                        pending.append(source)
        stats["changed"] = len(pending)
        if args.limit:
            pending = pending[: args.limit]
        if args.apply:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup = backup_path.open("a", encoding="utf-8") if args.apply else None
        for offset in range(0, len(pending), 50):
            batch = pending[offset : offset + 50]
            plans: list[tuple[dict, list[dict], dict]] = []
            for source in batch:
                chunks = connection.execute(
                    "SELECT id, chunk_index, content, content_hash, paragraph_start, paragraph_end FROM legal_chunks "
                    "WHERE legal_source_id = %s ORDER BY chunk_index", (source["id"],)).fetchall()
                plan = plan_source(source, chunks)
                if plan is None:
                    continue
                if "skip" in plan:
                    stats["skipped"] += 1
                    skips[plan["skip"]] = skips.get(plan["skip"], 0) + 1
                    continue
                plans.append((source, chunks, plan))
            if not args.apply:
                stats["applied"] += len(plans)
                continue
            texts = {}
            for _, chunks, plan in plans:
                for new_chunk, old_chunk in zip(plan["new_chunks"], chunks):
                    if new_chunk.content != old_chunk["content"]:
                        texts[new_chunk.content_hash] = new_chunk.content
            vectors: dict[str, list[float]] = {}
            keys = list(texts)
            for start in range(0, len(keys), BATCH):
                part = keys[start : start + BATCH]
                try:
                    for key, vector in zip(part, embed([texts[k] for k in part])):
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
