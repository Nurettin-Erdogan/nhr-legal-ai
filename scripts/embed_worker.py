"""Embedding düğümü işçisi (yalnız standart kütüphane): PC'den gelen parça işlerini sunucudaki Ollama ile vektöre çevirir.

`scripts/embed_hub.py` işleri `~/embed/jobs/*.jsonl.gz` içine bırakır (her satır {"id", "content"}); bu işçi her işi
`~/embed/out/<iş>.jsonl.gz` dosyasına yazar (her satır {"id", "v": [768 sayı]}). Veritabanı ve karar metni düğümde
kalıcı saklanmaz: iş ve sonuç dosyaları hub tarafından toplanınca silinir. Model PC'dekiyle aynıdır (nomic-embed-text,
768 boyut, truncate), vektörler eski vektörlerle uyumludur. Kaldığı yerden devam eder (systemd: nhr-embed.service).
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JOBS = ROOT / "jobs"
OUT = ROOT / "out"
BASE_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
DIMENSIONS = int(os.getenv("EMBED_DIMENSIONS", "768"))
BATCH = int(os.getenv("EMBED_BATCH", "16"))
PARALLEL = int(os.getenv("EMBED_PARALLEL", "2"))
NUM_THREAD = int(os.getenv("EMBED_NUM_THREAD", "0"))
log = logging.getLogger("embed_worker")


def embed(texts: list[str]) -> list[list[float]]:
    payload = {"model": MODEL, "input": texts, "dimensions": DIMENSIONS, "truncate": True, "keep_alive": "30m"}
    if NUM_THREAD:  # OLLAMA_NUM_THREAD diye bir ortam değişkeni yok; iş parçacığı sayısı istekle verilir (2026-10-24)
        payload["options"] = {"num_thread": NUM_THREAD}
    body = json.dumps(payload).encode()
    request = urllib.request.Request(f"{BASE_URL}/api/embed", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=900) as response:
        vectors = json.loads(response.read())["embeddings"]
    if len(vectors) != len(texts) or any(len(v) != DIMENSIONS for v in vectors):
        raise RuntimeError("beklenmeyen embedding sayısı/boyutu")
    return vectors


def run_job(path: Path) -> None:
    name = path.name[: -len(".jsonl.gz")]
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    started = time.time()
    out_path = OUT / f"{name}.jsonl.gz"
    part = OUT / f"{name}.jsonl.gz.part"
    done = 0
    def embed_batch(start: int):
        batch = rows[start : start + BATCH]
        texts = [(row["content"] or "").strip() or "." for row in batch]
        try:
            vectors = embed(texts)
        except Exception as exc:  # noqa: BLE001 - tek sorunlu parça işi düşürmesin: teker teker dene
            vectors = []
            for row, text in zip(batch, texts):
                try:
                    vectors.extend(embed([text]))
                except Exception:  # noqa: BLE001
                    vectors.append(None)
            log.warning("parti tek tek denendi: %s", str(exc)[:80])
        return batch, vectors

    # Sunucuda Ollama tek çekirdek kullanıyordu (2026-10-24: 0,5 parça/sn); EMBED_PARALLEL eşzamanlı parti ile iki çekirdek de çalışır
    # (Ollama tarafında OLLAMA_NUM_PARALLEL aynı değer olmalı). Sıra korunur.
    with gzip.open(part, "wt", encoding="utf-8", compresslevel=3) as out:
        with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
            for batch, vectors in pool.map(embed_batch, range(0, len(rows), BATCH)):
                for row, vector in zip(batch, vectors):
                    if vector is None:
                        continue
                    out.write(json.dumps({"id": row["id"], "v": [round(x, 6) for x in vector]}, separators=(",", ":")) + "\n")
                    done += 1
    os.replace(part, out_path)
    path.unlink()
    log.info("iş %s: %d/%d parça, %.1f sn (%.1f parça/sn)", name, done, len(rows), time.time() - started,
             done / max(time.time() - started, 0.001))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    JOBS.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.part"):
        stale.unlink()
    while True:
        jobs = sorted(p for p in JOBS.glob("*.jsonl.gz"))
        if not jobs:
            time.sleep(10)
            continue
        try:
            run_job(jobs[0])
        except Exception as exc:  # noqa: BLE001
            log.error("iş hatası %s: %s", jobs[0].name, exc)
            time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
