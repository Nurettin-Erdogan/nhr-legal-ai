"""Derin denetimde bulunan küçük ama kesin veri yanlışlarını düzeltir (varsayılan kuru çalıştırma; `--apply` yazar).

1. İkiye katlanmış metin: metnin ilk yarısı ile ikinci yarısı birebir aynıysa (aynı metin art arda iki kez yazılmış) yalnız ilk yarı kalır.
   Parçalar eski ayarla yeniden kurulur; değişen parçanın vektörü sıfırlanır (gömme kuyruğu yeniden doldurur), fazla parçalar
   (atıf bağı yoksa) silinir. Eski hâl `.local/corpus-repair-backups/misc-*.jsonl` yedeğine yazılır.
2. Rumi takvim tarihi: Osmanlı dönemi kanunlarında "1337" gibi Rumi yıl Miladi yıl sanılmış (Resmî Gazete tarihi < 1800). Tarih
   uydurulmaz: alan NULL yapılır, özgün değer `legislation_details`'a bağlı kaynağın `metadata.rumi_date` alanına yazılır.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psycopg.types.json import Jsonb  # noqa: E402

from api.db import admin_database_connection  # noqa: E402
from ingestion.text import content_hash  # noqa: E402
from ingestion.yargitay.chunking import chunk_text  # noqa: E402

SIZES = (1800, 1200, 1500, 2400, 3000, 4000, 8000, 16000)


def doubled_ids(connection):
    path = ROOT / ".local" / "doubled_ids.txt"
    if path.exists():
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    found = []
    with connection.transaction():
        with connection.cursor(name="doubled_scan") as scan:
            scan.itersize = 300
            scan.execute("SELECT id, raw_text FROM legal_sources WHERE deleted_at IS NULL AND is_current AND raw_text IS NOT NULL")
            for row in scan:
                text = row["raw_text"]
                half = len(text) // 2
                if len(text) > 400 and text[:half].strip() == text[half:].strip():
                    found.append(str(row["id"]))
    return found


def repair_doubled(connection, apply: bool, backup) -> dict:
    stats = {"adaylar": 0, "düzeltilen": 0, "atlanan": 0}
    skips: list[str] = []
    for source_id in doubled_ids(connection):
        source = connection.execute("SELECT id, raw_text, content_hash, metadata, title FROM legal_sources WHERE id = %s", (source_id,)).fetchone()
        if source is None:
            continue
        old = source["raw_text"]
        half = len(old) // 2
        if not (len(old) > 400 and old[:half].strip() == old[half:].strip()):
            continue  # artık ikilenmiş değil
        stats["adaylar"] += 1
        new = old[:half].strip()
        chunks = connection.execute("SELECT id, chunk_index, content, content_hash FROM legal_chunks WHERE legal_source_id = %s ORDER BY chunk_index", (source_id,)).fetchall()
        old_contents = [chunk["content"] for chunk in chunks]
        size = next((s for s in SIZES if [piece.content for piece in chunk_text(old, max_chars=s)] == old_contents), None)
        if size is None or source["content_hash"] != content_hash(old):
            stats["atlanan"] += 1
            skips.append(f"{source_id}: {'parçalama üretilemedi' if size is None else 'özet uyuşmuyor'}")
            continue
        new_chunks = chunk_text(new, max_chars=size)
        surplus = chunks[len(new_chunks):]
        if surplus and connection.execute("SELECT 1 FROM citations WHERE legal_chunk_id = ANY(%s) LIMIT 1", ([c["id"] for c in surplus],)).fetchone():
            stats["atlanan"] += 1
            skips.append(f"{source_id}: fazla parçaya atıf bağlı")
            continue
        if not apply:
            stats["düzeltilen"] += 1
            continue
        backup.write(json.dumps({"tür": "doubled", "id": str(source_id), "title": source["title"], "raw_text": old, "content_hash": source["content_hash"],
                                 "chunks": [{**c, "id": str(c["id"])} for c in chunks]}, ensure_ascii=False, default=str) + "\n")
        backup.flush()
        os.fsync(backup.fileno())
        with connection.transaction():
            if surplus:
                connection.execute("DELETE FROM legal_chunks WHERE id = ANY(%s)", ([c["id"] for c in surplus],))
            for new_chunk, old_chunk in zip(new_chunks, chunks):
                if new_chunk.content != old_chunk["content"]:
                    connection.execute(
                        "UPDATE legal_chunks SET content=%s, content_hash=%s, paragraph_start=%s, paragraph_end=%s, token_count=NULL, "
                        "embedding=NULL, embedding_model=NULL, embedding_created_at=NULL WHERE id=%s",
                        (new_chunk.content, new_chunk.content_hash, new_chunk.paragraph_start, new_chunk.paragraph_end, old_chunk["id"]))
            metadata = dict(source["metadata"] or {})
            metadata["doubled_text_fix"] = {"previous_content_hash": source["content_hash"], "previous_length": len(old),
                                            "fixed_at": datetime.now(timezone.utc).isoformat()}
            connection.execute("UPDATE legal_sources SET raw_text=%s, content_hash=%s, metadata=%s WHERE id=%s",
                               (new, content_hash(new), Jsonb(metadata), source_id))
        stats["düzeltilen"] += 1
    stats["atlama_nedenleri"] = skips
    return stats


def repair_rumi_dates(connection, apply: bool, backup) -> dict:
    rows = connection.execute(
        "SELECT d.legal_source_id, d.official_gazette_date, d.version_date, s.metadata FROM legislation_details d JOIN legal_sources s ON s.id = d.legal_source_id "
        "WHERE d.official_gazette_date < '1800-01-01' OR d.version_date < '1800-01-01'").fetchall()
    stats = {"etkilenen_kayıt": len(rows)}
    if not apply:
        return stats
    for row in rows:
        backup.write(json.dumps({"tür": "rumi", "id": str(row["legal_source_id"]), "official_gazette_date": str(row["official_gazette_date"]),
                                 "version_date": str(row["version_date"])}, ensure_ascii=False) + "\n")
        metadata = dict(row["metadata"] or {})
        metadata["rumi_date"] = {"official_gazette_date": str(row["official_gazette_date"]) if row["official_gazette_date"] else None,
                                 "version_date": str(row["version_date"]) if row["version_date"] else None,
                                 "note": "Rumi takvim yılı Miladi sanılmıştı; tarih uydurulmadı, alan boşaltıldı."}
        with connection.transaction():
            connection.execute(
                "UPDATE legislation_details SET official_gazette_date = CASE WHEN official_gazette_date < '1800-01-01' THEN NULL ELSE official_gazette_date END, "
                "version_date = CASE WHEN version_date < '1800-01-01' THEN NULL ELSE version_date END WHERE legal_source_id = %s", (row["legal_source_id"],))
            connection.execute("UPDATE legal_sources SET published_at = CASE WHEN published_at < '1800-01-01' THEN NULL ELSE published_at END, metadata = %s WHERE id = %s",
                               (Jsonb(metadata), row["legal_source_id"]))
    backup.flush()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    backup_path = ROOT / ".local" / "corpus-repair-backups" / f"misc-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with admin_database_connection() as connection, backup_path.open("a", encoding="utf-8") as backup:
        connection.execute("SET statement_timeout = 0")
        connection.commit()
        connection.autocommit = True
        print("ikilenmiş metin:", repair_doubled(connection, args.apply, backup), flush=True)
        print("Rumi tarih:", repair_rumi_dates(connection, args.apply, backup), flush=True)
    print(("UYGULANDI; yedek: " + str(backup_path)) if args.apply else "KURU ÇALIŞTIRMA", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
