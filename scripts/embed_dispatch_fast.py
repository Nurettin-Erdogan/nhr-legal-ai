"""Yerelde hazır bekleyen embedding iş dosyalarını (data/embed/job-*.jsonl.gz) düğümlere TOPLU gönderir.

  python scripts/embed_dispatch_fast.py [--per-node 24] [--gpu 300]

embed_hub dosya başına scp ile ~100 iş/dk gönderiyordu; 8.000+ iş ~80 dk sürüyordu ve sunucular o sırada boşta kalıyordu
(2026-10-24). Burada her düğüme tek ssh+tar akışıyla birden çok iş gönderilir (karşıda önce `incoming/`, sonra `jobs/`
dizinine taşınır: işçi yarım dosya görmez). PC'nin GPU düğümüne (varsa) ayrı pay verilir. Gönderilen yerel dosya silinir.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import embed_hub as eh  # noqa: E402


def send_batch(node: dict, files: list[Path]) -> int:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for path in files:
            archive.add(path, arcname=path.name)
    data = buffer.getvalue()
    command = "mkdir -p embed/incoming embed/jobs && cd embed/incoming && tar xf - && mv -f *.jsonl.gz ../jobs/"
    result = subprocess.run(["ssh", *eh._args(node), node["host"], command], input=data, capture_output=True, timeout=600)
    if result.returncode != 0:
        print("hata", node["name"], result.stderr.decode("utf-8", "ignore")[:120], flush=True)
        return 0
    for path in files:
        path.unlink(missing_ok=True)
    return len(files)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-node", type=int, default=24)
    parser.add_argument("--gpu", type=int, default=300)
    args = parser.parse_args()
    nodes = [n for n in eh.load_nodes()]
    remote = [n for n in nodes if not n.get("local")]
    gpu = [n for n in nodes if n.get("local")]
    files = sorted(eh.WORK.glob("job-*.jsonl.gz"))
    print(f"yerel iş {len(files)} | sunucu {len(remote)} | gpu düğümü {len(gpu)}", flush=True)
    plan: list[tuple[dict, list[Path]]] = []
    cursor = 0
    for node in gpu:
        part = files[cursor:cursor + args.gpu]
        cursor += len(part)
        if part:
            local = Path(node["local"]) / "jobs"
            local.mkdir(parents=True, exist_ok=True)
            import shutil

            for path in part:
                shutil.copyfile(path, local / (path.name + ".part"))
                (local / (path.name + ".part")).replace(local / path.name)
                path.unlink(missing_ok=True)
            print(f"{node['name']}: {len(part)} iş yerel kuyruğa bırakıldı", flush=True)
    rest = files[cursor:]
    for index, node in enumerate(remote):
        part = rest[index * args.per_node:(index + 1) * args.per_node]
        if part:
            plan.append((node, part))
    print(f"plan: {len(plan)} düğüme toplam {sum(len(p) for _, p in plan)} iş", flush=True)
    with ThreadPoolExecutor(max_workers=24) as pool:
        sent = sum(pool.map(lambda item: send_batch(*item), plan))
    print(f"gönderilen iş: {sent}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
