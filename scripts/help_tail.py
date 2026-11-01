"""Boşta kalan sunucuları, hâlâ iş taşıyan (yavaş) sunucuların kuyruk SONUNA yardıma gönderir.

  python scripts/help_tail.py [--dry]

Yavaş uçta (portal zaman aşımı veren kayıtlar) bazı sunucular saatlerce tek başına çalışırken yüzlercesi boşta kalıyordu (2026-10-24).
Her yüklü sunucunun kalan kimlik listesinin arka kısmı TERS SIRADA yeni bir iş dosyası olarak boşta bir sunucuya verilir: yüklü sunucu
listeyi baştan, yardımcı sondan işler, ortada buluşurlar. Çakışan az sayıda kimlik işlemede zaten doğrulanmış/atlanmış sayılır.
Yüklü sunucudaki dosyaya dokunulmaz.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetcher_hub as hub  # noqa: E402

MIN_REMAINING = 400
LIST_CMD = (
    'cd {d}/jobs 2>/dev/null || exit 0; for f in $(ls -1 *.jsonl.gz 2>/dev/null | sort); do '
    'p=$(cat "${{f%.jsonl.gz}}.progress" 2>/dev/null || echo 0); zcat "$f" | tail -n +$((p+1)); done'
)


def remaining_ids(item):
    name, node = item
    try:
        out = hub.ssh(node, LIST_CMD.format(d=node["dir"]), timeout=120)
    except Exception:  # noqa: BLE001
        return name, None
    ids = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                ids.append(json.loads(line)["external_id"])
            except Exception:  # noqa: BLE001
                pass
    return name, ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()
    nodes = hub.active_nodes()
    with ThreadPoolExecutor(max_workers=16) as pool:
        listed = dict(pool.map(remaining_ids, nodes.items()))
    listed = {n: v for n, v in listed.items() if v is not None}
    donors = {n: v for n, v in listed.items() if len(v) >= MIN_REMAINING}
    idle = sorted(n for n, v in listed.items() if len(v) == 0)
    total = sum(len(v) for v in listed.values())
    print(f"düğüm {len(listed)} | kalan {total:,} | yüklü {len(donors)} | boşta {len(idle)}", flush=True)
    if not donors or not idle:
        return 0
    helpers_per = max(1, len(idle) // len(donors))
    plan = []   # (donor, helper, ids)
    cursor = 0
    for donor, ids in sorted(donors.items(), key=lambda kv: -len(kv[1])):
        k = min(helpers_per, max(1, len(ids) // MIN_REMAINING))
        part = len(ids) // (k + 1)
        for i in range(k):
            if cursor >= len(idle):
                break
            end = len(ids) - i * part
            start = end - part
            chunk = list(reversed(ids[start:end]))
            if chunk:
                plan.append((donor, idle[cursor], chunk))
                cursor += 1
    print(f"plan: {len(plan)} yardım işi | toplam {sum(len(p[2]) for p in plan):,} kimlik", flush=True)
    if args.dry:
        return 0
    stamp = time.strftime("%Y%m%d-%H%M%S")

    def send(step):
        donor, helper, chunk = step
        node = nodes[helper]
        job = f"tail-{stamp}-{donor}-to-{helper}"
        local = ROOT / "data" / "fetcher" / "jobs" / f"{job}.jsonl.gz"
        with gzip.open(local, "wt", encoding="utf-8") as handle:
            for external_id in chunk:
                handle.write(json.dumps({"external_id": external_id}) + "\n")
        try:
            hub.ssh(node, f"mkdir -p {node['dir']}/jobs", timeout=60)
            hub.scp(node, str(local), f"{node['host']}:{node['dir']}/jobs/{job}.jsonl.gz.part", timeout=120)
            hub.ssh(node, f"mv {node['dir']}/jobs/{job}.jsonl.gz.part {node['dir']}/jobs/{job}.jsonl.gz", timeout=60)
            return True
        except Exception as exc:  # noqa: BLE001
            print("gönderilemedi", helper, str(exc)[:100], flush=True)
            return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        ok = sum(pool.map(send, plan))
    print(f"gönderilen: {ok}/{len(plan)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
