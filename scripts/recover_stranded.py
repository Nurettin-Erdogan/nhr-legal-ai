"""Kapanan düğümlerde kalan (henüz doğrulanmamış) kimlikleri yeni iş dosyası olarak canlı düğümlere gönderir.

  python scripts/recover_stranded.py --dry-run
  python scripts/recover_stranded.py

Mantık: PC'deki `data/fetcher/jobs/*.jsonl.gz` her zaman gönderilmiş işin yerel kopyasıdır. Canlı düğümlerin `jobs/` ve `jobs-emsal/` dizinlerindeki
işler dışında kalan yerel iş dosyalarındaki kimlikler, veritabanında hâlâ `bulk_seed + pending + verify_status yok` ise kaybolmuş sayılır
(tamamlanıp sonucu toplanmış olanlar zaten doğrulanmıştır ve elenir). Yeni işler hesap 2 düğümlerine en kısa kuyruktan başlayarak dağıtılır.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetcher_hub as hub  # noqa: E402

JOBS_LOCAL = ROOT / "data" / "fetcher" / "jobs"
SIZES = {"bedesten": 5000, "emsal": 1500}
DIRS = {"bedesten": "jobs", "emsal": "jobs-emsal"}
FILTER = """
SELECT external_id FROM legal_sources
WHERE external_id = ANY(%s) AND ingestion_method = 'bulk_seed' AND ingest_status = 'pending' AND is_current
  AND deleted_at IS NULL AND source_type = 'court_decision' AND metadata->>'verify_status' IS NULL
"""


def live_jobs(item):
    name, node = item
    names: set[str] = set()
    for lane in ("jobs", "jobs-emsal"):
        try:
            out = hub.ssh(node, f"ls -1 {node['dir']}/{lane}/*.jsonl.gz 2>/dev/null || true", timeout=60)
        except Exception:  # noqa: BLE001
            return name, None
        names |= {Path(line).name for line in out.split() if line.endswith(".jsonl.gz")}
    return name, names


def done_parts() -> set[tuple[str, int]]:
    """İşlenmiş (applied) ya da işlenmeyi bekleyen (inbox) sonuç parçaları: ad = <iş>-<başlangıç 7 hane>.jsonl.gz, parça 200 kayıt."""
    parts: set[tuple[str, int]] = set()
    for base in (ROOT / "data" / "fetcher" / "applied", ROOT / "data" / "fetcher" / "inbox"):
        for path in base.glob("*/*.jsonl.gz"):
            stem = path.name[: -len(".jsonl.gz")]
            job, _, offset = stem.rpartition("-")
            if offset.isdigit():
                parts.add((job, int(offset)))
    return parts


PART = 200


def read_missing_ids(path: Path, done: set[tuple[str, int]]) -> list[str]:
    job = path.name[: -len(".jsonl.gz")]
    ids: list[str] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line)["external_id"] for line in handle if line.strip()]
    for start in range(0, len(rows), PART):
        if (job, start) not in done:
            ids.extend(rows[start : start + PART])
    return ids


def main() -> int:
    dry = "--dry-run" in sys.argv
    nodes = hub.active_nodes()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(live_jobs, nodes.items()))
    unknown = [n for n, v in results if v is None]
    if unknown:
        print("UYARI: okunamayan canlı düğüm:", unknown, flush=True)
    live = set().union(*[v for _, v in results if v])
    takers = {n: v for n, v in nodes.items() if v.get("key")}  # 2026-10-23: tüm düğümler id_rsa kullanıyor
    emsal_takers = dict(takers)  # Emsal servisi hesap 2'nin 50 düğümünde de kurulu ve çalışıyor (2026-10-22 doğrulandı); iş verilince çeker
    candidates = [p for p in sorted(JOBS_LOCAL.glob("*.jsonl.gz")) if p.name not in live and not p.name.startswith("recover-")]
    print(f"yerel iş {len(list(JOBS_LOCAL.glob('*.jsonl.gz')))} | canlıda {len(live)} | aday (canlıda olmayan) {len(candidates)}", flush=True)
    lanes = {"bedesten": [], "emsal": []}
    for path in candidates:
        lanes["emsal" if "emsal" in path.name else "bedesten"].append(path)
    stranded: dict[str, list[str]] = {}
    done = done_parts()
    print(f"işlenmiş/bekleyen sonuç parçası: {len(done):,}", flush=True)
    with psycopg.connect(os.environ.get("DATABASE_ADMIN_URL") or open(ROOT / ".env", encoding="utf-8").read().split("DATABASE_ADMIN_URL=")[1].split()[0].strip('"'), autocommit=True) as connection:
        connection.execute("SET statement_timeout = '300s'")
        for lane, paths in lanes.items():
            seen: set[str] = set()
            out: list[str] = []
            for path in paths:
                ids = [i for i in read_missing_ids(path, done) if i not in seen]
                seen.update(ids)
                for start in range(0, len(ids), 2000):
                    chunk = ids[start : start + 2000]
                    rows = connection.execute(FILTER, (chunk,)).fetchall()
                    keep = {r[0] for r in rows}
                    out.extend(i for i in chunk if i in keep)
            stranded[lane] = out
            print(f"{lane}: aday kimlik {len(seen):,} | hâlâ doğrulanmamış (kayıp) {len(out):,}", flush=True)
    if dry:
        return 0
    counts = {n: 0 for n in takers}
    stamp = f"{time.strftime('%Y%m%d-%H%M%S')}"
    sent = 0
    for lane, ids in stranded.items():
        pool_nodes = emsal_takers if lane == "emsal" else takers
        if not ids or not pool_nodes:
            continue
        size = SIZES[lane]
        jobs = [ids[i : i + size] for i in range(0, len(ids), size)]
        for index, chunk in enumerate(jobs):
            taker = min(pool_nodes, key=lambda n: counts[n])
            counts[taker] += 1
            node = nodes[taker]
            job = f"recover-{stamp}-{lane[:3]}{index:03d}-{taker}"
            local = JOBS_LOCAL / f"{job}.jsonl.gz"
            with gzip.open(local, "wt", encoding="utf-8") as handle:
                for external_id in chunk:
                    handle.write(json.dumps({"external_id": external_id}) + "\n")
            directory = DIRS[lane]
            try:
                hub.ssh(node, f"mkdir -p {node['dir']}/{directory}", timeout=60)
                hub.scp(node, str(local), f"{node['host']}:{node['dir']}/{directory}/{job}.jsonl.gz.part", timeout=120)
                hub.ssh(node, f"mv {node['dir']}/{directory}/{job}.jsonl.gz.part {node['dir']}/{directory}/{job}.jsonl.gz", timeout=60)
                sent += len(chunk)
            except Exception as exc:  # noqa: BLE001
                print("gönderilemedi", taker, job, str(exc)[:100], flush=True)
        print(f"{lane}: {len(jobs)} iş gönderildi", flush=True)
    print(f"toplam gönderilen kimlik: {sent:,}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
