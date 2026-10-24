"""Kredisi biten hesabın düğümlerindeki başlanmamış Yargıtay/Danıştay iş dosyalarını hesap 2 düğümlerine taşır.

  python scripts/evacuate_jobs.py            # planı yazar ve uygular
  python scripts/evacuate_jobs.py --dry-run  # yalnız plan

Bağışçı: anahtarı jurisai-aws.pem OLMAYAN aktif düğümler (hesap 1 + Azure). Alıcı: jurisai-aws.pem'li düğümler (hesap 2).
Her bağışçıda sıradaki ilk 2 iş ve .progress'i olan iş yerinde kalır; kalanlar alıcıların en kısa kuyruklusuna gider.
Dosya önce alıcıya `.part` olarak yazılır, mv ile yayımlanır, sonra bağışçıdan silinir: yarıda kesilirse iş kaybolmaz (en kötü iki yerde durur;
işlemede zaten doğrulanmış kayıtlar atlanır). Eşzamanlılık düşük tutulur (ağ engeli dersi, 2026-10-21).
"""

from __future__ import annotations

import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetcher_hub as hub  # noqa: E402

WORKERS = 8
KEEP = 1


def is_takers_account(node: dict) -> bool:
    return bool(node.get("key")) and "jurisai-aws" in str(node["key"])


def list_jobs(item):
    name, node = item
    try:
        out = hub.ssh(node, f"ls -1 {node['dir']}/jobs/*.jsonl.gz 2>/dev/null; ls -1 {node['dir']}/jobs/*.progress 2>/dev/null || true", timeout=60)
    except Exception:  # noqa: BLE001
        return name, None, None
    files = sorted(Path(line).name for line in out.split() if line.endswith(".jsonl.gz"))
    started = {Path(line).name[: -len(".progress")] for line in out.split() if line.endswith(".progress")}
    movable = [f for f in files if f[: -len(".jsonl.gz")] not in started]
    return name, files, movable


def main() -> int:
    dry = "--dry-run" in sys.argv
    nodes = hub.active_nodes()
    donors = {n: v for n, v in nodes.items() if not is_takers_account(v)}
    takers = {n: v for n, v in nodes.items() if is_takers_account(v)}
    print(f"bağışçı {len(donors)} | alıcı {len(takers)}", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        rows = list(pool.map(list_jobs, nodes.items()))
    info = {r[0]: r for r in rows if r[1] is not None}
    counts = {n: len(info[n][1]) for n in takers if n in info}
    plan: list[tuple[str, str, str]] = []
    for name in donors:
        if name not in info:
            print("okunamadı:", name, flush=True)
            continue
        movable = info[name][2][KEEP:] if len(info[name][2]) > KEEP else []  # sıradaki KEEP işi yerinde bırak (~14 saatlik iş)
        for job in movable:
            taker = min(counts, key=counts.get)
            plan.append((name, taker, job))
            counts[taker] += 1
    print(f"taşınacak iş: {len(plan)} | alıcı kuyruk en az/en çok: {min(counts.values())}/{max(counts.values())}", flush=True)
    if dry:
        return 0

    def move(step: tuple[str, str, str]) -> bool:
        donor, taker, job = step
        a, b = nodes[donor], nodes[taker]
        with tempfile.TemporaryDirectory() as tmp:
            try:
                local = f"{tmp}/{job}"
                hub.scp(a, f"{a['host']}:{a['dir']}/jobs/{job}", local, timeout=120)
                hub.scp(b, local, f"{b['host']}:{b['dir']}/jobs/{job}.part", timeout=120)
                hub.ssh(b, f"mv {b['dir']}/jobs/{job}.part {b['dir']}/jobs/{job}", timeout=60)
                hub.ssh(a, f"rm -f {a['dir']}/jobs/{job}", timeout=60)
                return True
            except Exception as exc:  # noqa: BLE001
                print("hata", donor, taker, job, str(exc)[:100], flush=True)
                return False

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for ok in pool.map(move, plan):
            done += 1 if ok else 0
            if done and done % 50 == 0:
                print(f"taşınan {done}/{len(plan)}", flush=True)
    print(f"bitti: taşınan {done}/{len(plan)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
