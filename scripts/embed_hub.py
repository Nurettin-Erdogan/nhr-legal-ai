"""Embedding işini bulut düğümlerine dağıtır (PC yalnız veritabanını ve taşımayı yapar).

  python scripts/embed_hub.py run            # tek tur: topla -> işle -> dağıt
  python scripts/embed_hub.py run --loop     # sürekli (varsayılan 60 sn arayla)
  python scripts/embed_hub.py status

Düğümler `data/campaign/embed-nodes.json` içinde ([{"name", "host", "key"}]). Her düğümde `scripts/embed_worker.py`
(`nhr-embed.service`) çalışır. Resmî (`ready`) kayıtların `embedding IS NULL` parçaları 400'lük işlere bölünür,
düğümlerin `~/embed/jobs/` dizinine konur; sonuç vektörleri `~/embed/out/` dizininden toplanıp `legal_chunks.embedding`
sütununa yazılır (aynı model/boyut: nomic-embed-text, 768). Duraklatma: data/campaign/PAUSE_EMBED_HUB (PC yerel embedding bayrağı PAUSE_PC_EMBED ayrıdır).
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from api.ai.embeddings import vector_literal  # noqa: E402

NODES_FILE = ROOT / "data" / "campaign" / "embed-nodes.json"
STATE = ROOT / "data" / "campaign" / "embed-hub.json"
PAUSE = ROOT / "data" / "campaign" / "PAUSE_EMBED_HUB"
WORK = ROOT / "data" / "embed"
INBOX = WORK / "inbox"
LOG = ROOT / "data" / "logs" / "embed-hub.log"
MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text").strip()
JOB_SIZE = int(os.getenv("EMBED_JOB_SIZE", "200"))
QUEUE_TARGET = int(os.getenv("EMBED_QUEUE_TARGET", "3"))
WORKERS = int(os.getenv("EMBED_HUB_WORKERS", "4"))
GROUP = int(os.getenv("EMBED_GROUP", "600"))  # bir seferde taranan resmî kaynak sayısı (embedding'siz parça oranı %7: büyük grup = hızlı tarama)


def _log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def load_nodes() -> list[dict]:
    return json.loads(NODES_FILE.read_text(encoding="utf-8")) if NODES_FILE.exists() else []


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"cursor": None, "applied": 0, "passes": 0}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def _args(node: dict) -> list[str]:
    args = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3",
            "-o", "StrictHostKeyChecking=accept-new"]
    if node.get("key"):
        args += ["-i", node["key"]]
    return args


def ssh(node: dict, command: str, timeout: int = 120) -> str:
    result = subprocess.run(["ssh", *_args(node), node["host"], command], capture_output=True, text=True,
                            timeout=timeout, encoding="utf-8", stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(f"ssh {node['host']}: {result.stderr.strip()[:160]}")
    return result.stdout


def scp(node: dict, source: str, target: str, timeout: int = 600) -> None:
    result = subprocess.run(["scp", "-q", *_args(node), source, target], capture_output=True, text=True,
                            timeout=timeout, encoding="utf-8", stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(f"scp {node['host']}: {result.stderr.strip()[:160]}")


# -- toplama -------------------------------------------------------------------------------------
def _local_dir(node: dict) -> Path | None:
    """Yerel düğüm (PC'nin GPU'su): `local` anahtarı işçinin klasörünü gösterir (jobs/ ve out/ altında)."""
    return Path(node["local"]) if node.get("local") else None


def collect_one(node: dict) -> int:
    name = node["name"]
    local_dir = _local_dir(node)
    if local_dir is not None:
        target = INBOX / name
        target.mkdir(parents=True, exist_ok=True)
        moved = 0
        for path in sorted((local_dir / "out").glob("*.jsonl.gz")):
            os.replace(path, target / path.name)
            moved += 1
        return moved
    try:
        listing = ssh(node, "cd embed/out 2>/dev/null && ls -1 *.jsonl.gz 2>/dev/null || true", timeout=60).split()
    except Exception as exc:  # noqa: BLE001
        _log(f"{name}: liste alınamadı: {exc}")
        return 0
    target = INBOX / name
    target.mkdir(parents=True, exist_ok=True)
    copied = []
    # Dosya başına scp (bağlantı kurulumu ~1-2 sn) yerine 100'lük gruplar tek ssh+tar akışıyla alınır (2026-10-24: sunucularda
    # 40+ dosya birikmişti, PC'ye çekim darboğazdı).
    import tarfile

    for start in range(0, len(listing), 100):
        batch = listing[start:start + 100]
        try:
            proc = subprocess.Popen(["ssh", *_args(node), node["host"], "cd embed/out && tar cf - " + " ".join(batch)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
            with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
                for member in archive:
                    if not member.isfile() or "/" in member.name or not member.name.endswith(".jsonl.gz"):
                        continue
                    data = archive.extractfile(member)
                    part = target / (member.name + ".part")
                    with part.open("wb") as handle:
                        handle.write(data.read())
                    os.replace(part, target / member.name)
                    copied.append(member.name)
            proc.wait(timeout=60)
        except Exception as exc:  # noqa: BLE001
            _log(f"{name}: tar akışı hatası ({len(batch)} dosya): {exc}")
            break
    if copied:
        try:
            ssh(node, "cd embed/out && rm -f " + " ".join(copied), timeout=60)
        except Exception as exc:  # noqa: BLE001
            _log(f"{name}: düğümde silme başarısız (yeniden kopyalanır, zararsız): {exc}")
    return len(copied)


def _apply_file(path: Path) -> int:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    params = [(vector_literal(row["v"]), MODEL, row["id"]) for row in rows]
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], autocommit=True) as connection:
        connection.execute("SET statement_timeout = '600s'")
        with connection.transaction(), connection.cursor() as cur:
            cur.executemany(
                "UPDATE legal_chunks SET embedding = %s::vector, embedding_model = %s, embedding_created_at = NOW() "
                "WHERE id = %s AND embedding IS NULL",
                params,
            )
    path.unlink()
    return len(rows)


def apply_all(connection: psycopg.Connection) -> int:
    """Vektör yazımı HNSW dizini yüzünden yavaş (satır başına ~50-100 ms): dosyalar paralel bağlantılarla yazılır."""
    if os.getenv("EMBED_NO_APPLY") == "1":  # yazma ayrı süreçte (embed_apply_loop.py)
        return 0
    files = sorted(INBOX.glob("*/*.jsonl.gz"))
    if not files:
        return 0
    with ThreadPoolExecutor(max_workers=int(os.getenv("EMBED_APPLY_WORKERS", "3"))) as pool:
        return sum(pool.map(_apply_file, files))


# -- iş üretimi / dağıtım ---------------------------------------------------------------------------
def build_jobs(connection: psycopg.Connection, state: dict, wanted: int) -> list[Path]:
    """`wanted` kadar iş dosyası üretir (her biri JOB_SIZE parça); imleç kaynak kimliğiyle ilerler."""
    WORK.mkdir(parents=True, exist_ok=True)
    jobs: list[Path] = []
    buffer: list[tuple] = []
    while len(jobs) < wanted:
        cursor = state.get("cursor")
        sources = [row[0] for row in connection.execute(
            "SELECT id FROM legal_sources WHERE ingest_status = 'ready' AND is_current AND deleted_at IS NULL "
            + ("AND id > %s " if cursor else "") + "ORDER BY id LIMIT %s",
            ((cursor, GROUP) if cursor else (GROUP,)),
        ).fetchall()]
        if not sources:
            if state.get("cursor"):
                state["cursor"] = None   # tur bitti: sonraki turda kaçanlar (sonradan resmîleşenler) taranır
                state["passes"] = state.get("passes", 0) + 1
                _log(f"kaynak turu bitti (tur {state['passes']}); imleç başa alındı")
                if not buffer and not jobs:
                    break
                continue
            break
        state["cursor"] = str(sources[-1])
        rows = connection.execute(
            "SELECT id, content FROM legal_chunks WHERE legal_source_id = ANY(%s) AND embedding IS NULL ORDER BY id",
            (sources,),
        ).fetchall()
        buffer.extend((str(row[0]), row[1]) for row in rows)
        while len(buffer) >= JOB_SIZE and len(jobs) < wanted:
            chunk, buffer = buffer[:JOB_SIZE], buffer[JOB_SIZE:]
            path = WORK / f"job-{int(time.time() * 1000)}-{len(jobs):03d}.jsonl.gz"
            with gzip.open(path, "wt", encoding="utf-8", compresslevel=3) as out:
                for chunk_id, content in chunk:
                    out.write(json.dumps({"id": chunk_id, "content": content}, ensure_ascii=False) + "\n")
            jobs.append(path)
    if buffer and len(jobs) < wanted:
        path = WORK / f"job-{int(time.time() * 1000)}-{len(jobs):03d}.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=3) as out:
            for chunk_id, content in buffer:
                out.write(json.dumps({"id": chunk_id, "content": content}, ensure_ascii=False) + "\n")
        jobs.append(path)
    elif buffer:
        # Fazla okunanlar başka tura kalır: imleci bu parçaların kaynağından önceye almak yerine bırak (sonraki tur alır).
        state["leftover"] = state.get("leftover", 0) + len(buffer)
    return jobs


def queue_length(node: dict) -> int:
    local_dir = _local_dir(node)
    if local_dir is not None:
        (local_dir / "jobs").mkdir(parents=True, exist_ok=True)
        return len(list((local_dir / "jobs").glob("*.jsonl.gz")))
    try:
        return int(ssh(node, "mkdir -p embed/jobs embed/out; ls -1 embed/jobs/*.jsonl.gz 2>/dev/null | wc -l", timeout=60).strip() or 0)
    except Exception as exc:  # noqa: BLE001
        _log(f"{node['name']}: kuyruk okunamadı: {exc}")
        return QUEUE_TARGET  # ulaşılamayan düğüme iş gönderme


def send(node: dict, path: Path) -> bool:
    local_dir = _local_dir(node)
    if local_dir is not None:
        import shutil

        (local_dir / "jobs").mkdir(parents=True, exist_ok=True)
        part = local_dir / "jobs" / (path.name + ".part")
        shutil.copyfile(path, part)
        os.replace(part, local_dir / "jobs" / path.name)
        path.unlink()
        return True
    try:
        scp(node, str(path), f"{node['host']}:embed/jobs/{path.name}.part", timeout=300)
        ssh(node, f"mv embed/jobs/{path.name}.part embed/jobs/{path.name}", timeout=60)
        path.unlink()
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"{node['name']}: iş gönderilemedi: {exc}")
        return False


def send_many(node: dict, paths: list[Path]) -> int:
    if _local_dir(node) is not None:
        return sum(1 for path in paths if send(node, path))
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for path in paths:
            archive.add(path, arcname=path.name)
    command = "mkdir -p embed/incoming embed/jobs && cd embed/incoming && tar xf - && mv -f *.jsonl.gz ../jobs/"
    try:
        result = subprocess.run(["ssh", *_args(node), node["host"], command], input=buffer.getvalue(),
                                capture_output=True, timeout=600)
    except Exception as exc:  # noqa: BLE001
        _log(f"{node['name']}: iş gönderilemedi: {exc}")
        return 0
    if result.returncode != 0:
        _log(f"{node['name']}: iş gönderilemedi: {result.stderr.decode('utf-8', 'ignore')[:120]}")
        return 0
    for path in paths:
        path.unlink(missing_ok=True)
    return len(paths)


def _no_collect() -> bool:
    """Yalnız dağıtım kipi: bayrak dosyası `data/campaign/EMBED_NO_COLLECT` ya da EMBED_COLLECT=0."""
    return os.getenv("EMBED_COLLECT", "1") == "0" or (ROOT / "data" / "campaign" / "EMBED_NO_COLLECT").exists()


def _compact_counters(connection: psycopg.Connection) -> None:
    """Panel sayaçlarının fark satırlarını tabana katlar (migration 059); hata asıl işi bozmaz."""
    try:
        connection.execute("SELECT corpus_counters_compact()")
    except Exception as exc:  # noqa: BLE001
        _log(f"sayaç katlama hatası: {exc}")


def run_once(connection: psycopg.Connection) -> None:
    nodes = load_nodes()
    state = load_state()
    if _no_collect():
        # Yalnız dağıtım kipi (kullanıcı 2026-10-22: "PC sadece veri çeksin, embedding sunucularda"): sonuçlar sunucularda birikir,
        # veri çekimi bitince toplanıp yazılır. PC diski ve ssh trafiği çekime ayrılır.
        got = applied = 0
    else:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            got = sum(pool.map(collect_one, nodes))
        applied = apply_all(connection)
        _compact_counters(connection)
    state["applied"] = state.get("applied", 0) + applied
    if got or applied:
        _log(f"toplandı: {got} sonuç dosyası, veritabanına yazılan: {applied} parça (toplam {state['applied']:,})")
    if PAUSE.exists():
        save_state(state)
        return
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        lengths = list(pool.map(queue_length, nodes))
    default_target = 12 if _no_collect() else QUEUE_TARGET
    missing = [(node, node.get("queue_target", default_target) - length) for node, length in zip(nodes, lengths)
               if length < node.get("queue_target", default_target)]
    wanted = sum(count for _, count in missing)
    if wanted:
        jobs = build_jobs(connection, state, wanted)
        assignments = []
        iterator = iter(jobs)
        for node, count in missing:
            for _ in range(count):
                job = next(iterator, None)
                if job is not None:
                    assignments.append((node, job))
        # Düğüm başına tek ssh+tar akışı (dosya başına scp ~100 iş/dk idi; 1.400 iş 15 dk sürüp sunucuları boşta bırakıyordu).
        by_node: dict[str, tuple[dict, list[Path]]] = {}
        for node, job in assignments:
            by_node.setdefault(node["name"], (node, []))[1].append(job)
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            sent = sum(pool.map(lambda item: send_many(*item), by_node.values()))
        if sent:
            _log(f"gönderildi: {sent} iş x {JOB_SIZE} parça")
    save_state(state)


def run(loop: bool, interval: int) -> int:
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL tanımlı değil")
    INBOX.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            with psycopg.connect(url, autocommit=True) as connection:
                connection.execute("SET statement_timeout = '300s'")
                run_once(connection)
        except Exception as exc:  # noqa: BLE001
            _log(f"tur hatası: {exc}")
        if not loop:
            return 0
        time.sleep(interval)


def status() -> int:
    state = load_state()
    print(json.dumps(state, ensure_ascii=False, indent=1))
    nodes = load_nodes()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        lengths = list(pool.map(queue_length, nodes))
    print(f"düğüm: {len(nodes)} | kuyruk toplamı: {sum(lengths)} iş")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("run", "status"))
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    return run(args.loop, args.interval) if args.command == "run" else status()


if __name__ == "__main__":
    raise SystemExit(main())
