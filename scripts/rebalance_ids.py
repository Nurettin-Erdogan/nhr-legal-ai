"""Çekici düğümlerin Yargıtay/Danıştay kuyruklarını KALAN KİMLİK sayısına göre dengeler (iş dosyalarını gerekirse böler).

  python scripts/rebalance_ids.py [--dry]

`rebalance_jobs.py` yalnız iş dosyası SAYISINI eşitler; dosyalar 5000 kimlikli ve kısmen işlenmiş olduğundan bazı düğümler 14 saat,
bazıları 1 saat iş taşıyordu (2026-10-23: 356 düğümde kalan ort. 5,9 bin, en çok 10 bin kimlik). Burada:
- Her düğümün kalan kimliği = Σ(satır - ilerleme). Hedef = toplamın düğüm sayısına bölümü.
- En yüklü düğümün, henüz başlanmamış (ve sıradaki olmayan) bir iş dosyası ya taşınır ya da ikiye bölünüp bir kısmı en az yüklü düğüme gönderilir.
Sıradaki (ilk tamamlanmamış) dosyaya ve ilerleme dosyası olanlara dokunulmaz.
"""

from __future__ import annotations

import argparse
import gzip
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetcher_hub as hub  # noqa: E402

LANE = os.environ.get("REBALANCE_DIR", "jobs")
EXCLUDE = {n for n in os.environ.get("REBALANCE_EXCLUDE", "").split(",") if n}
MIN_MOVE = 300   # bundan küçük farkı taşımaya değmez

LIST_CMD = (
    'cd {d}/{lane} 2>/dev/null || exit 0; for f in *.jsonl.gz; do [ -f "$f" ] || continue; '
    'n=$(zcat "$f" | wc -l); p=$(cat "${{f%.jsonl.gz}}.progress" 2>/dev/null || echo 0); echo "$f $n $p"; done'
)


def list_node(item):
    name, node = item
    try:
        out = hub.ssh(node, LIST_CMD.format(d=node["dir"], lane=LANE), timeout=90)
    except Exception:  # noqa: BLE001
        return name, None
    jobs = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            jobs.append((parts[0], int(parts[1]), int(parts[2])))
    return name, sorted(jobs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()
    nodes = {n: v for n, v in hub.active_nodes().items() if n not in EXCLUDE}
    with ThreadPoolExecutor(max_workers=24) as pool:
        listed = dict(pool.map(list_node, nodes.items()))
    listed = {n: j for n, j in listed.items() if j is not None}
    remaining = {n: sum(max(0, c - p) for _, c, p in j) for n, j in listed.items()}
    # Taşınabilir: ilerleme 0 olan, sıradaki (ilk tamamlanmamış) olmayan dosyalar
    movable = {}
    for n, jobs in listed.items():
        first_open = next((f for f, c, p in jobs if p < c), None)
        movable[n] = [(f, c) for f, c, p in jobs if p == 0 and f != first_open]
    total = sum(remaining.values())
    print(f"düğüm {len(listed)} | kalan toplam {total:,} | ort {total // max(1, len(listed)):,} | en az {min(remaining.values()):,} en çok {max(remaining.values()):,}")

    plan = []   # (donor, taker, file, ids_to_send, total_lines, new_name)
    counter = 0
    while True:
        donor = max(remaining, key=lambda n: remaining[n] if movable[n] else -1)
        taker = min(remaining, key=lambda n: remaining[n])
        gap = remaining[donor] - remaining[taker]
        if gap < 2 * MIN_MOVE or not movable[donor]:
            break
        delta = gap // 2
        fname, lines = movable[donor].pop()
        if lines <= delta:   # dosya bütün gider
            plan.append((donor, taker, fname, lines, lines, fname))
            remaining[donor] -= lines
            remaining[taker] += lines
        else:               # bölünür: sondan `delta` kimlik taker'a, kalan donor'da
            counter += 1
            new_name = fname[: -len(".jsonl.gz")] + f"-s{int(time.time()) % 100000}x{counter}.jsonl.gz"
            plan.append((donor, taker, fname, delta, lines, new_name))
            remaining[donor] -= delta
            remaining[taker] += delta
            movable[donor].append((fname, lines - delta))
            movable[donor].sort()
            movable[taker].append((new_name, delta))
    print(f"plan: {len(plan)} adım | sonrası en az {min(remaining.values()):,} en çok {max(remaining.values()):,}")
    if args.dry:
        return 0

    def move(step) -> bool:
        donor, taker, fname, send, lines, new_name = step
        a, b = nodes[donor], nodes[taker]
        with tempfile.TemporaryDirectory() as tmp:
            try:
                local = Path(tmp) / fname
                hub.scp(a, f"{a['host']}:{a['dir']}/{LANE}/{fname}", str(local), timeout=120)
                with gzip.open(local, "rt", encoding="utf-8") as handle:
                    rows = [line for line in handle if line.strip()]
                if len(rows) != lines:
                    return False  # bu arada değişmiş
                keep, give = rows[: len(rows) - send], rows[len(rows) - send:]
                give_path = Path(tmp) / new_name
                with gzip.open(give_path, "wt", encoding="utf-8") as out:
                    out.writelines(give)
                hub.scp(b, str(give_path), f"{b['host']}:{b['dir']}/{LANE}/{new_name}.part", timeout=120)
                hub.ssh(b, f"mv {b['dir']}/{LANE}/{new_name}.part {b['dir']}/{LANE}/{new_name}", timeout=60)
                if keep:
                    keep_path = Path(tmp) / (fname + ".keep")
                    with gzip.open(keep_path, "wt", encoding="utf-8") as out:
                        out.writelines(keep)
                    hub.scp(a, str(keep_path), f"{a['host']}:{a['dir']}/{LANE}/{fname}.part", timeout=120)
                    hub.ssh(a, f"mv {a['dir']}/{LANE}/{fname}.part {a['dir']}/{LANE}/{fname}", timeout=60)
                else:
                    hub.ssh(a, f"rm -f {a['dir']}/{LANE}/{fname}", timeout=60)
                return True
            except Exception as exc:  # noqa: BLE001
                print("hata", donor, taker, fname, str(exc)[:100])
                return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        ok = sum(pool.map(move, plan))
    print(f"yapılan: {ok}/{len(plan)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
