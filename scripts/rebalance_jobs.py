"""Çekici düğümlerin Yargıtay/Danıştay iş kuyruklarını dengeler (boş kalan düğümlere iş taşır).

  python scripts/rebalance_jobs.py          # planı yazar, uygular

Kuyruğu en uzun düğümlerden, henüz başlanmamış iş dosyalarını (ilk dosya ve .progress'i olan dosya hariç) en kısa kuyruklu
düğümlere taşır; en uzun ile en kısa fark <= 1 iş olana kadar. Aktif düğümler `fetcher_hub.active_nodes()`.
"""

from __future__ import annotations

import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetcher_hub as hub  # noqa: E402


LANE = os.environ.get("REBALANCE_DIR", "jobs")  # jobs (Yargıtay/Danıştay) ya da jobs-emsal
EXCLUDE = {n for n in os.environ.get("REBALANCE_EXCLUDE", "").split(",") if n}


def list_jobs(item) -> tuple[str, list[str]]:
    name, node = item
    try:
        out = hub.ssh(node, f"ls -1 {node['dir']}/{LANE}/*.jsonl.gz 2>/dev/null; ls -1 {node['dir']}/{LANE}/*.progress 2>/dev/null || true", timeout=60)
    except Exception:  # noqa: BLE001
        return name, []
    files = [Path(line).name for line in out.split() if line.endswith(".jsonl.gz")]
    started = {Path(line).name[: -len(".progress")] for line in out.split() if line.endswith(".progress")}
    movable = [f for f in sorted(files) if f[: -len(".jsonl.gz")] not in started]
    return name, files, movable  # type: ignore[return-value]


def main() -> int:
    nodes = {n: v for n, v in hub.active_nodes().items() if n not in EXCLUDE}
    with ThreadPoolExecutor(max_workers=16) as pool:
        rows = list(pool.map(list_jobs, nodes.items()))
    counts = {r[0]: len(r[1]) for r in rows if len(r) == 3}
    movable = {r[0]: list(r[2])[1:] if len(r[2]) > 1 else [] for r in rows if len(r) == 3}  # ilk işi (sıradaki) koru
    plan: list[tuple[str, str, str]] = []
    while True:
        donor = max(counts, key=lambda n: counts[n] if movable[n] else -1)
        taker = min(counts, key=lambda n: counts[n])
        if counts[donor] - counts[taker] <= 1 or not movable[donor]:
            break
        job = movable[donor].pop()
        plan.append((donor, taker, job))
        counts[donor] -= 1
        counts[taker] += 1
    print(f"taşınacak iş: {len(plan)} | sonrası kuyruk en az/en çok: {min(counts.values())}/{max(counts.values())}")

    def move(step: tuple[str, str, str]) -> bool:
        donor, taker, job = step
        a, b = nodes[donor], nodes[taker]
        with tempfile.TemporaryDirectory() as tmp:
            try:
                local = f"{tmp}/{job}"
                hub.scp(a, f"{a['host']}:{a['dir']}/{LANE}/{job}", local, timeout=120)
                hub.scp(b, local, f"{b['host']}:{b['dir']}/{LANE}/{job}.part", timeout=120)
                hub.ssh(b, f"mv {b['dir']}/{LANE}/{job}.part {b['dir']}/{LANE}/{job}", timeout=60)
                hub.ssh(a, f"rm -f {a['dir']}/{LANE}/{job}", timeout=60)
                return True
            except Exception as exc:  # noqa: BLE001
                print("hata", donor, taker, job, str(exc)[:100])
                return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        ok = sum(pool.map(move, plan))
    print(f"taşınan: {ok}/{len(plan)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
