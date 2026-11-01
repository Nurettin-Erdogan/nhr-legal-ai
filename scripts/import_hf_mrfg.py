"""mrfg/turkish-court-decisions -> legal_sources (bulk_seed, pending, doğrulanmamış).

Dosyaları tek tek indirir, aktarır, siler; kontrol noktalıdır (yeniden başlatılabilir).
  python scripts/import_hf_mrfg.py --source yargitay --limit-rows 10000   # deneme
  python scripts/import_hf_mrfg.py --source yargitay                      # tam
Chunk yazmaz; arama için sonra scripts/chunk_bulk_seed.py çalıştırılır.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import psycopg
import pyarrow.parquet as pq
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from ingestion.bulk_chunk import chunk_sources_by_external_ids  # noqa: E402
from ingestion.bulk_copy import insert_pending_seed, load_bulk_checkpoint, save_bulk_checkpoint  # noqa: E402
from ingestion.hf_mrfg import CANONICAL_SOURCE_NAME, HF_DATASET, IMPORT_TYPE, SOURCES, prepare_mrfg_row  # noqa: E402

BATCH_ROWS = 2_000
WORK_DIR = ROOT / "data" / "eval" / "mrfg"
COLUMNS = ["source", "document_id", "court", "esas_no", "karar_no", "karar_tarihi", "text", "masked_count", "raw_sha256"]


def list_files(source: str) -> list[str]:
    req = Request(f"https://huggingface.co/api/datasets/{HF_DATASET}", headers={"User-Agent": "nhr-import"})
    with urlopen(req, timeout=60) as r:
        siblings = json.load(r)["siblings"]
    return sorted(s["rfilename"] for s in siblings if s["rfilename"].startswith(f"data/{source}/") and s["rfilename"].endswith(".parquet"))


def download(name: str) -> Path:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    dest = WORK_DIR / name.replace("/", "_")
    if dest.exists():
        return dest
    tmp = dest.with_suffix(".part")
    req = Request(f"https://huggingface.co/datasets/{HF_DATASET}/resolve/main/{name}", headers={"User-Agent": "nhr-import"})
    with urlopen(req, timeout=120) as r, tmp.open("wb") as fh:
        while chunk := r.read(1 << 20):
            fh.write(chunk)
    tmp.rename(dest)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=sorted(SOURCES), required=True)
    ap.add_argument("--ignore-checkpoint", action="store_true", help="Bitmiş dosyaları da yeniden işle (mevcut kayıtları parçalamak için)")
    ap.add_argument("--limit-rows", type=int, default=0, help="Deneme: toplam bu kadar satırda dur")
    a = ap.parse_args()
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL yok")
    checkpoint_name = f"bulk:hf_mrfg:{a.source}" + (":trial" if a.limit_rows else "")
    batch_id = f"hf-mrfg-{a.source}"
    totals = {"inserted": 0, "existing": 0, "official_ready": 0, "duplicate_batch": 0, "quarantine": 0, "copied": 0, "skipped_masked_or_unsupported": 0}
    t0 = time.time()
    with psycopg.connect(url, autocommit=False, row_factory=dict_row) as connection:
        connection.execute("SET statement_timeout = 0")
        connection.execute("SET synchronous_commit = off")
        state = load_bulk_checkpoint(connection, checkpoint_name)
        files_done = set() if a.ignore_checkpoint else set(state.get("files_done") or [])
        for k in totals:
            totals[k] = int(state.get(k) or 0)
        seen_rows = 0
        for name in list_files(a.source):
            if name in files_done:
                continue
            path = download(name)
            print(f"{name}: indirildi ({path.stat().st_size >> 20} MB)", flush=True)
            pf = pq.ParquetFile(path)
            chunk = []
            stop = False
            for batch in pf.iter_batches(batch_size=BATCH_ROWS, columns=COLUMNS):
                for raw in batch.to_pylist():
                    seen_rows += 1
                    prepared = prepare_mrfg_row(raw)
                    if prepared is None:
                        totals["skipped_masked_or_unsupported"] += 1
                    else:
                        chunk.append(prepared)
                    if a.limit_rows and seen_rows >= a.limit_rows:
                        stop = True
                        break
                if chunk:
                    stats = insert_pending_seed(
                        connection, chunk, batch_id=batch_id, canonical_source_name=CANONICAL_SOURCE_NAME,
                        extra_metadata={"dataset": HF_DATASET, "import_type": IMPORT_TYPE},
                    )
                    for k in ("inserted", "existing", "official_ready", "duplicate_batch", "quarantine", "copied"):
                        totals[k] += getattr(stats, k)
                    totals["chunks"] = totals.get("chunks", 0) + chunk_sources_by_external_ids(
                        connection, [row.external_id for row in chunk if not row.quarantine_code]
                    )
                    connection.commit()
                    chunk = []
                print(f"  satır={seen_rows:,} eklenen={totals['inserted']:,} | {(time.time() - t0) / 60:.1f} dk", flush=True)
                if stop:
                    break
            if stop:
                print("DENEME limiti doldu", flush=True)
                break
            files_done.add(name)
            save_bulk_checkpoint(connection, checkpoint_name, {"files_done": sorted(files_done), **totals})
            connection.commit()
            pf.close()
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            print(f"{name}: tamam", flush=True)
    print("TOTALS " + json.dumps(totals, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
