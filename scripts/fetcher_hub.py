"""PC (ana veritabanı) tarafı: çekici düğümlere (AWS, Azure) iş gönderir, sonuçları alır ve seed'leri doğrular.

PC portala hiç istek atmaz. Her çağrıda (Görev Zamanlayıcı günde bir `run`):
  1. collect: düğümlerdeki biten sonuç parçalarını (out/*.jsonl.gz) scp ile alır, düğümden siler.
  2. apply  : her sonucu ilgili seed ile `verify_seeds.compare_texts` kuralıyla karşılaştırır:
              eşleşen → resmî (ready) + resmî metin; harf/rakam farkı → korpustan çıkarılır (deleted_at);
              portalda yok → verify_status=unavailable; ağ hatası → atıf kuyruğuna (sonra yeniden).
  3. dispatch: düğümdeki bekleyen işi 8 dosyaya (8 x 5000 kimlik, ~2,5 günlük) tamamlar. Öncelik: atıf kuyruğu
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
    # Emsal şeridi yalnız aws2 ve aws3'te (kullanıcı 2026-10-16: "Emsal'i 2 sunucuyla çekelim"; aws ve azure IP'leri CAPTCHA'ya en çok takılanlar).
    "aws": {"host": "ubuntu@13.60.255.72", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher", "lanes": ("bedesten",)},
    "azure": {"host": "nhr@20.91.186.253", "key": None, "dir": "fetcher", "lanes": ("bedesten",)},
    # İkinci AWS sunucusu (2026-10-16, PC'nin yerine; makine sayısı artmadı): aynı hesap/anahtar, farklı IP.
    "aws2": {"host": "ubuntu@13.60.216.212", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    # Dördüncü sunucu (2026-10-16, kullanıcı: "bir sunucu daha açayım"); Azure 22 Ekim civarı kapanınca yerine yenisi AÇILMAZ (3'e iner).
    "aws3": {"host": "ubuntu@56.228.34.25", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    # aws4-aws7 yalnız Yargıtay/Danıştay (2026-10-16, kullanıcı: "2-3 sunucu daha, onlar sadece Yargıtay/Danıştay çeksin").
    "aws4": {"host": "ubuntu@51.21.194.213", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher", "lanes": ("bedesten",)},
    "aws5": {"host": "ubuntu@13.60.96.7", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher", "lanes": ("bedesten",)},
}
# Daytona sandbox'ı (kullanıcı 2026-10-16: "PC'yi bırakırız olmazsa bunu da ekle"): API anahtarı .env'de DAYTONA_API_KEY varsa eklenir.
# KAPALI: Daytona ücretsiz seviyesi portallara çıkışa izin vermiyor (Tier 3+ gerekir, ölçüldü 2026-10-16); FETCHER_USE_DAYTONA=1 ile açılır.
if os.getenv("DAYTONA_API_KEY") and os.getenv("FETCHER_USE_DAYTONA") == "1":
    NODES["daytona"] = {"host": None, "key": None, "dir": "fetcher", "kind": "daytona", "lanes": ("bedesten",)}
# PC günde bir kez çalışır (kullanıcı 2026-10-14): düğümde ~2,5 günlük iş (8 x 5000; düğüm ~16 bin/gün) hazır tutulur ki
# PC bir gün çalışmasa bile düğüm boş kalmasın.
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
_SEED_EMSAL = """
  AND ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending' AND ls.is_current
  AND ls.deleted_at IS NULL AND ls.source_type = 'court_decision'
  AND ls.metadata->>'verify_status' IS NULL
  AND ls.external_id LIKE 'emsal:%%'
"""
# Emsal şeridi EN ESKİDEN yeniye gider: PC'deki `verify_seeds.py --source emsal` en yeniden eskiye gittiği için ikisi
# aynı kaydı çekmez, ortada buluşur (çakışan az sayıda kayıt işlemede zaten doğrulanmış olarak atlanır).
_SELECT_EMSAL = """
SELECT ls.id, ls.external_id, d.decision_date
FROM court_decision_details d JOIN legal_sources ls ON ls.id = d.legal_source_id
WHERE d.decision_date IS NOT NULL
  AND (%(cdate)s::date IS NULL OR (d.decision_date, d.legal_source_id) > (%(cdate)s::date, %(cid)s::uuid))
""" + _SEED_EMSAL + """
ORDER BY d.decision_date ASC, d.legal_source_id ASC
LIMIT %(n)s
"""
LANES = {
    # şerit: (düğümdeki iş dizini, iş boyutu, düğümde tutulacak iş sayısı)
    # ~6 günlük iş: PC birkaç gün açılmasa bile sunucular boş kalmaz (kullanıcı 2026-10-15: "hiçbir zaman boşta kalmasın").
    "bedesten": ("jobs", 5000, 20),
    "emsal": ("jobs-emsal", 1500, 12),
}
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
def _collect_local(name: str, node: dict) -> int:
    out = Path(node["dir"]) / "out"
    target = INBOX / name
    target.mkdir(parents=True, exist_ok=True)
    moved = 0
    for path in sorted(out.glob("*.jsonl.gz")) if out.exists() else []:
        os.replace(path, target / path.name)
        moved += 1
    return moved


def _collect_daytona(name: str, node: dict) -> int:
    import fetcher_daytona as fd

    fd.ensure_running()
    sandbox = fd.get_sandbox()
    target = INBOX / name
    target.mkdir(parents=True, exist_ok=True)
    got = []
    for fname in fd.ls(sandbox, "out"):
        fd.get(sandbox, "out", fname, str(target / fname) + ".part")
        os.replace(str(target / fname) + ".part", target / fname)
        got.append(fname)
    if got:
        fd.rm(sandbox, "out", got)
    return len(got)


def collect(name: str, node: dict) -> int:
    """Biten parçaları kopyalar; düğümden toplu siler. Silme başarısız olursa parça bir sonraki turda yeniden
    kopyalanır, işleme zararsızdır (zaten doğrulanmış kayıt atlanır)."""
    if node.get("kind") == "daytona":
        return _collect_daytona(name, node)
    if node["host"] is None:
        return _collect_local(name, node)
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

    urls = {"yargitay": yargitay_url, "danistay": danistay_url,
            "emsal": lambda i: yargitay_url(i, base_url="https://emsal.uyap.gov.tr/")}
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
def next_batch_emsal(connection: psycopg.Connection, state: dict, n: int) -> tuple[list[str], list]:
    if state.get("emsal_done"):
        return [], []
    cursor = state.get("emsal", {})
    rows = connection.execute(_SELECT_EMSAL, {"cdate": cursor.get("date"), "cid": cursor.get("id"), "n": n}).fetchall()
    if not rows:
        state["emsal_done"] = True
        return [], []
    state["emsal"] = {"date": str(rows[-1][2]), "id": str(rows[-1][0])}
    return [row[1] for row in rows], []


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


def dispatch(name: str, node: dict, connection: psycopg.Connection, state: dict, lane: str = "bedesten") -> int:
    jobs_dir, job_size, target = LANES[lane]
    batch = next_batch if lane == "bedesten" else next_batch_emsal
    if node.get("kind") == "daytona":
        import fetcher_daytona as fd

        sandbox = fd.get_sandbox()
        pending = len(fd.ls(sandbox, jobs_dir))
    elif node["host"] is None:
        (Path(node["dir"]) / jobs_dir).mkdir(parents=True, exist_ok=True)
        pending = len(list((Path(node["dir"]) / jobs_dir).glob("*.jsonl.gz")))
    else:
        pending = int(ssh(node, f"mkdir -p {node['dir']}/{jobs_dir}; ls -1 {node['dir']}/{jobs_dir}/*.jsonl.gz 2>/dev/null | wc -l").strip() or 0)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    sent = 0
    index = 0
    while pending < target:
        ids, queued = batch(connection, state, job_size)
        if not ids:
            break
        job = f"{stamp}-{index:02d}-{name}" + ("" if lane == "bedesten" else f"-{lane}")
        local = ROOT / "data" / "fetcher" / "jobs" / f"{job}.jsonl.gz"
        local.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(local, "wt", encoding="utf-8") as handle:
            for external_id in ids:
                handle.write(json.dumps({"external_id": external_id}) + "\n")
        if node.get("kind") == "daytona":
            fd.put(sandbox, str(local), jobs_dir, f"{job}.jsonl.gz")
        elif node["host"] is None:
            import shutil
            shutil.copyfile(local, Path(node["dir"]) / jobs_dir / f"{job}.jsonl.gz.part")
            os.replace(Path(node["dir"]) / jobs_dir / f"{job}.jsonl.gz.part", Path(node["dir"]) / jobs_dir / f"{job}.jsonl.gz")
        else:
            scp(node, str(local), f"{node['host']}:{node['dir']}/{jobs_dir}/{job}.jsonl.gz.part")
            ssh(node, f"mv {node['dir']}/{jobs_dir}/{job}.jsonl.gz.part {node['dir']}/{jobs_dir}/{job}.jsonl.gz")
        if queued:
            connection.execute(_PICKED, (queued,))
        save_state(state)  # imleç ancak iş düğüme ulaştıktan sonra kalıcı
        sent += len(ids)
        pending += 1
        index += 1
    return sent


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
            for lane in node.get("lanes", tuple(LANES)):
                try:
                    sent = dispatch(name, node, connection, state, lane)
                    if sent:
                        _log(f"{name}/{lane}: {sent} kimlik gönderildi")
                except Exception as exc:  # noqa: BLE001
                    _log(f"{name}/{lane}: gönderme hatası: {exc}")
    return 0


def status() -> int:
    state = load_state()
    print(json.dumps({k: v for k, v in state.items()}, ensure_ascii=False, indent=1))
    for name, node in NODES.items():
        if node["host"] is None:
            d = Path(node["dir"])
            print(name, "yerel | iş:", len(list((d / "jobs").glob("*.jsonl.gz"))), "| sonuç:", len(list((d / "out").glob("*.jsonl.gz"))))
            continue
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
