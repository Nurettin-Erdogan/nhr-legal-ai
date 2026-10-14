"""PC (ana veritabanı) tarafı: çekici düğümlere (AWS, Azure) iş gönderir, sonuçları alır ve seed'leri doğrular.

PC portala hiç istek atmaz. Her çağrıda (Görev Zamanlayıcı 10 dk'da bir `run`):
  1. collect: düğümlerdeki biten sonuç parçalarını (out/*.jsonl.gz) scp ile alır, düğümden siler.
  2. apply  : her sonucu ilgili seed ile `verify_seeds.compare_texts` kuralıyla karşılaştırır:
              eşleşen → resmî (ready) + resmî metin; harf/rakam farkı → korpustan çıkarılır (deleted_at);
              portalda yok → verify_status=unavailable; ağ hatası → atıf kuyruğuna (sonra yeniden).
  3. dispatch: düğümde bekleyen iş azsa yeni iş dosyası (5000 kimlik) gönderir. Öncelik: atıf kuyruğu
              (seed_verification_queue: asistanın atıf yaptığı seed'ler), sonra en yeniden eskiye. Seed daire etiketleri
              güvenilmez (570 bin "Büyük Genel Kurulu" yanlış etiketi), bu yüzden daireye göre öncelik verilmez.
              İmleç data/campaign/fetcher-hub.json.

  python scripts/fetcher_hub.py run
  python scripts/fetcher_hub.py status
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
load_dotenv(ROOT / ".env")

NODES = {
    "aws": {"host": "ubuntu@13.60.255.72", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "azure": {"host": "nhr@20.91.186.253", "key": None, "dir": "fetcher"},
}
JOB_SIZE = 5000
LOW_WATER = 1          # düğümde en çok bu kadar iş dosyası varken yenisi gönderilir (biri işlenir, biri sırada)
STATE = ROOT / "data" / "campaign" / "fetcher-hub.json"
INBOX = ROOT / "data" / "fetcher" / "inbox"
APPLIED = ROOT / "data" / "fetcher" / "applied"
LOG = ROOT / "data" / "logs" / "fetcher-hub.log"

_SEED = """
  AND ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending' AND ls.is_current
  AND ls.deleted_at IS NULL AND ls.source_type = 'court_decision'
  AND ls.metadata->>'verify_status' IS NULL
  AND (ls.external_id LIKE 'yargitay:%%' OR ls.external_id LIKE 'danistay:%%')
"""
_SELECT = """
SELECT ls.id, ls.external_id, d.decision_date
FROM court_decision_details d JOIN legal_sources ls ON ls.id = d.legal_source_id
WHERE d.decision_date IS NOT NULL
  AND (%(cdate)s::date IS NULL OR (d.decision_date, d.legal_source_id) < (%(cdate)s::date, %(cid)s::uuid))
""" + _SEED + """
ORDER BY d.decision_date DESC, d.legal_source_id DESC
LIMIT %(n)s
"""
_QUEUE = """
SELECT ls.id, ls.external_id
FROM seed_verification_queue q JOIN legal_sources ls ON ls.id = q.legal_source_id
WHERE q.picked_at IS NULL
""" + _SEED + """
ORDER BY q.request_count DESC, q.requested_at
LIMIT %(n)s
"""
_PICKED = "UPDATE seed_verification_queue SET picked_at = NOW() WHERE legal_source_id = ANY(%s)"
_ROW = """
SELECT ls.id, ls.raw_text FROM legal_sources ls
WHERE ls.external_id = %s AND ls.source_type = 'court_decision' AND ls.is_current AND ls.deleted_at IS NULL
  AND ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending'
"""
_REQUEUE = """
INSERT INTO seed_verification_queue (legal_source_id, request_count) VALUES (%s, 1)
ON CONFLICT (legal_source_id) DO UPDATE SET picked_at = NULL
"""


def _log(message: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _ssh_args(node: dict) -> list[str]:
    # ServerAlive: Azure'da oturumun bağlandıktan sonra asılı kaldığı görüldü (2026-10-14); 30 sn yanıtsızsa kopar.
    args = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3"]
    if node["key"]:
        args += ["-i", node["key"]]
    return args


def ssh(node: dict, command: str, timeout: int = 120) -> str:
    result = subprocess.run(["ssh", *_ssh_args(node), node["host"], command],
                            capture_output=True, text=True, timeout=timeout, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"ssh {node['host']}: {result.stderr.strip()[:200]}")
    return result.stdout


def scp(node: dict, source: str, target: str, timeout: int = 600) -> None:
    result = subprocess.run(["scp", "-q", *_ssh_args(node), source, target],
                            capture_output=True, text=True, timeout=timeout, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"scp {source} → {target}: {result.stderr.strip()[:200]}")


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# -- collect -------------------------------------------------------------------------------------
def collect(name: str, node: dict) -> int:
    """Biten parçaları kopyalar; düğümden toplu siler. Silme başarısız olursa parça bir sonraki turda yeniden
    kopyalanır, işleme zararsızdır (zaten doğrulanmış kayıt atlanır)."""
    listing = ssh(node, f"cd {node['dir']}/out 2>/dev/null && ls -1 *.jsonl.gz 2>/dev/null || true", timeout=60).split()
    target = INBOX / name
    target.mkdir(parents=True, exist_ok=True)
    copied = []
    for fname in listing:
        local = target / fname
        try:
            scp(node, f"{node['host']}:{node['dir']}/out/{fname}", str(local) + ".part", timeout=180)
        except Exception as exc:  # noqa: BLE001
            _log(f"{name}: {fname} kopyalanamadı: {exc}")
            break
        os.replace(str(local) + ".part", local)
        copied.append(fname)
    if copied:
        try:
            ssh(node, "cd " + node["dir"] + "/out && rm -f " + " ".join(copied), timeout=60)
        except Exception as exc:  # noqa: BLE001
            _log(f"{name}: düğümde silme başarısız (sonraki turda tekrar kopyalanır): {exc}")
    return len(copied)


# -- apply ---------------------------------------------------------------------------------------
def apply_all(connection: psycopg.Connection) -> dict[str, int]:
    from ingestion.hf_700k import strip_third_party_markup
    from ingestion.text import content_hash
    from ingestion.yargitay.store import _SNAPSHOT_SOURCE
    from ingestion.danistay.portal import document_url as danistay_url
    from ingestion.yargitay.portal import document_url as yargitay_url
    from verify_seeds import _MARK, _QUEUE_DONE, _TRASH, _VERIFY, SOURCES, compare_texts

    urls = {"yargitay": yargitay_url, "danistay": danistay_url}
    totals = {"verified": 0, "mismatch": 0, "unavailable": 0, "requeued": 0, "skipped": 0}
    APPLIED.mkdir(parents=True, exist_ok=True)
    for path in sorted(INBOX.glob("*/*.jsonl.gz")):
        node_name = path.parent.name
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        for row in rows:
            source, document_id = row["external_id"].split(":", 1)
            found = connection.execute(_ROW, (row["external_id"],)).fetchone()
            if not found:
                totals["skipped"] += 1  # zaten doğrulanmış/silinmiş ya da resmî kayıt
                continue
            source_id, seed_text = found
            now = datetime.now(UTC).isoformat(timespec="seconds")
            if row["status"] == "error":
                connection.execute(_REQUEUE, (source_id,))
                totals["requeued"] += 1
                continue
            if row["status"] == "not_found" or not (row.get("text") or "").strip():
                connection.execute(_MARK, {"id": source_id, "metadata": Jsonb(
                    {"verify_status": "unavailable", "verify_checked_at": now, "verify_reason": row.get("error") or "boş"})})
                totals["unavailable"] += 1
                continue
            official = row["text"]
            status, verification = compare_texts(seed_text or "", official, strip_third_party_markup(official))
            if status == "verified":
                cfg = SOURCES[source]
                digest = content_hash(official)
                with connection.transaction():
                    connection.execute(_SNAPSHOT_SOURCE, (source_id,))
                    connection.execute(_VERIFY, {
                        "id": source_id, "method": cfg["method"], "canonical": cfg["canonical"],
                        "url": urls[source](document_id), "text": official, "hash": digest,
                        "version": f"sha256:{digest[:16]}",
                        "metadata": Jsonb({"official_verified": True, "third_party": False,
                                           "provenance": "official_portal", "verified_via": f"fetcher:{node_name}",
                                           "verified_at": now, "verification": verification,
                                           "verify_status": "verified"}),
                    })
                totals["verified"] += 1
            else:
                connection.execute(_TRASH, {"id": source_id, "metadata": Jsonb(
                    {"verify_status": "mismatch", "verify_checked_at": now, "verify_reason": f"fetcher:{node_name}"})})
                totals["mismatch"] += 1
            connection.execute(_QUEUE_DONE, ([source_id],))
        (APPLIED / node_name).mkdir(parents=True, exist_ok=True)
        os.replace(path, APPLIED / node_name / path.name)
    return totals


# -- dispatch ------------------------------------------------------------------------------------
def next_batch(connection: psycopg.Connection, state: dict, n: int) -> tuple[list[str], list]:
    """(kimlikler, kuyruktan alınanların legal_source_id'leri). Kuyruk işareti iş düğüme ulaşınca konur."""
    queued = connection.execute(_QUEUE, {"n": n}).fetchall()
    ids = [row[1] for row in queued]
    if len(ids) < n and not state.get("all_done"):
        cursor = state.get("all", {})
        rows = connection.execute(_SELECT, {"cdate": cursor.get("date"), "cid": cursor.get("id"), "n": n - len(ids)}).fetchall()
        if rows:
            seen = set(ids)
            ids += [row[1] for row in rows if row[1] not in seen]
            state["all"] = {"date": str(rows[-1][2]), "id": str(rows[-1][0])}
        else:
            state["all_done"] = True
    return ids, [row[0] for row in queued]


def dispatch(name: str, node: dict, connection: psycopg.Connection, state: dict) -> int:
    pending = ssh(node, f"ls -1 {node['dir']}/jobs/*.jsonl.gz 2>/dev/null | wc -l").strip()
    if int(pending or 0) > LOW_WATER:  # biri işlenirken en çok biri sırada beklesin
        return 0
    ids, queued = next_batch(connection, state, JOB_SIZE)
    if not ids:
        return 0
    job = f"{datetime.now():%Y%m%d-%H%M%S}-{name}"
    local = ROOT / "data" / "fetcher" / "jobs" / f"{job}.jsonl.gz"
    local.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(local, "wt", encoding="utf-8") as handle:
        for external_id in ids:
            handle.write(json.dumps({"external_id": external_id}) + "\n")
    scp(node, str(local), f"{node['host']}:{node['dir']}/jobs/{job}.jsonl.gz.part")
    ssh(node, f"mv {node['dir']}/jobs/{job}.jsonl.gz.part {node['dir']}/jobs/{job}.jsonl.gz")
    if queued:
        connection.execute(_PICKED, (queued,))
    save_state(state)  # imleç ancak iş düğüme ulaştıktan sonra kalıcı
    return len(ids)


def run() -> int:
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL tanımlı değil")
    state = load_state()
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("SET statement_timeout = '300s'")
        for name, node in NODES.items():
            try:
                got = collect(name, node)
                if got:
                    _log(f"{name}: {got} sonuç parçası alındı")
            except Exception as exc:  # noqa: BLE001
                _log(f"{name}: toplama hatası: {exc}")
        totals = apply_all(connection)
        if any(totals.values()):
            _log(f"işlendi: {totals}")
            for key, value in totals.items():
                state.setdefault("totals", {})[key] = state.get("totals", {}).get(key, 0) + value
            save_state(state)
        for name, node in NODES.items():
            try:
                sent = dispatch(name, node, connection, state)
                if sent:
                    _log(f"{name}: {sent} kimlik gönderildi")
            except Exception as exc:  # noqa: BLE001
                _log(f"{name}: gönderme hatası: {exc}")
    return 0


def status() -> int:
    state = load_state()
    print(json.dumps({k: v for k, v in state.items()}, ensure_ascii=False, indent=1))
    for name, node in NODES.items():
        try:
            print(name, ssh(node, f"systemctl is-active nhr-fetcher; ls {node['dir']}/jobs {node['dir']}/out 2>/dev/null | tr '\\n' ' '; echo; tail -n 2 {node['dir']}/worker.log").strip())
        except Exception as exc:  # noqa: BLE001
            print(name, "erişilemedi:", exc)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("run", "status"))
    args = parser.parse_args()
    return run() if args.command == "run" else status()


if __name__ == "__main__":
    raise SystemExit(main())
