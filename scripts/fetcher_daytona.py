"""Daytona sandbox'ını çekici düğüm olarak kullanmak için yardımcılar (SSH/scp yerine Daytona SDK).

`scripts/fetcher_hub.py` bu modülü `kind == "daytona"` düğümler için kullanır. Sandbox'ta `fetch_worker.py` arka plan
oturumunda (Daytona "session") sürekli çalışır; iş dosyaları `fetcher/jobs/`, sonuçlar `fetcher/out/` altındadır
(sunuculardaki yapının aynısı). Anahtar: ortam değişkeni ya da .env içinde `DAYTONA_API_KEY` (sohbete yazılmaz).

  python scripts/fetcher_daytona.py setup     # sandbox'ı oluşturur/başlatır, kodu yükler, çekiciyi başlatır
  python scripts/fetcher_daytona.py status
  python scripts/fetcher_daytona.py ip        # sandbox'ın dışarıya görünen IP'si ve Bedesten erişimi
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

SANDBOX_NAME = "nhr-fetcher"
SESSION_PREFIX = "fetcher-"
CODE_FILES = {
    "ingestion/__init__.py": ROOT / "ingestion" / "__init__.py",
    "ingestion/bedesten_emsal.py": ROOT / "ingestion" / "bedesten_emsal.py",
    "ingestion/text.py": ROOT / "ingestion" / "text.py",
    "fetch_worker.py": ROOT / "scripts" / "fetch_worker.py",
}


def client():
    from daytona import Daytona, DaytonaConfig

    key = os.getenv("DAYTONA_API_KEY")
    if not key:
        raise SystemExit("DAYTONA_API_KEY tanımlı değil (.env içine ekleyin)")
    return Daytona(DaytonaConfig(api_key=key))


def get_sandbox(create: bool = False):
    from daytona import CreateSandboxFromSnapshotParams

    daytona = client()
    try:
        sandbox = daytona.get(SANDBOX_NAME)
    except Exception:  # noqa: BLE001
        if not create:
            raise
        sandbox = daytona.create(CreateSandboxFromSnapshotParams(
            name=SANDBOX_NAME, language="python", auto_stop_interval=0, auto_archive_interval=0,
            labels={"project": "nhr-legal-ai", "purpose": "official-text-fetcher"}))
    if str(getattr(sandbox, "state", "")).lower().split(".")[-1] not in ("started", "running"):
        sandbox.start()
    return sandbox


def _home(sandbox) -> str:
    return sandbox.get_work_dir() or sandbox.get_user_home_dir()


# -- hub taşıma işlemleri ------------------------------------------------------------------------
def ls(sandbox, directory: str) -> list[str]:
    base = f"{_home(sandbox)}/fetcher/{directory}"
    try:
        return sorted(f.name for f in sandbox.fs.list_files(base) if not f.is_dir and f.name.endswith(".jsonl.gz"))
    except Exception:  # noqa: BLE001
        return []


def put(sandbox, local: str, directory: str, name: str) -> None:
    base = f"{_home(sandbox)}/fetcher/{directory}"
    try:
        sandbox.fs.create_folder(base, "755")
    except Exception:  # noqa: BLE001
        pass
    sandbox.fs.upload_file(Path(local).read_bytes(), f"{base}/{name}.part")
    sandbox.fs.move_files(f"{base}/{name}.part", f"{base}/{name}")


def get(sandbox, directory: str, name: str, local: str) -> None:
    data = sandbox.fs.download_file(f"{_home(sandbox)}/fetcher/{directory}/{name}")
    Path(local).write_bytes(data)


def rm(sandbox, directory: str, names: list[str]) -> None:
    for name in names:
        sandbox.fs.delete_file(f"{_home(sandbox)}/fetcher/{directory}/{name}")


# -- kurulum -------------------------------------------------------------------------------------
def worker_running(sandbox) -> bool:
    result = sandbox.process.exec("pgrep -fc 'fetcher/fetch_worker.py' || true")
    return int((result.result or "0").strip().splitlines()[-1] or 0) > 0


def setup() -> None:
    sandbox = get_sandbox(create=True)
    home = _home(sandbox)
    for rel in ("ingestion", "jobs", "out"):
        sandbox.fs.create_folder(f"{home}/fetcher/{rel}", "755")
    for rel, path in CODE_FILES.items():
        sandbox.fs.upload_file(path.read_bytes(), f"{home}/fetcher/{rel}")
    if not worker_running(sandbox):
        session = SESSION_PREFIX + time.strftime("%m%d%H%M")
        sandbox.process.create_session(session)
        from daytona import SessionExecuteRequest

        sandbox.process.execute_session_command(session, SessionExecuteRequest(
            command=f"cd {home}/fetcher && nohup python3 -u fetch_worker.py >> worker.log 2>&1 &", run_async=True))
    print("sandbox:", sandbox.id, "| çekici çalışıyor:", worker_running(sandbox))


def ensure_running() -> None:
    """Hub her turda çağırır: sandbox durmuşsa başlatır, çekici ölmüşse yeniden kurar."""
    sandbox = get_sandbox(create=False)
    if not worker_running(sandbox):
        setup()


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "setup":
        setup()
    elif command == "ip":
        sandbox = get_sandbox(create=True)
        print(sandbox.process.exec(
            "curl -s -m 10 https://api.ipify.org; echo; "
            "curl -s -o /dev/null -m 15 -w 'bedesten=%{http_code}\\n' https://bedesten.adalet.gov.tr/; "
            "curl -s -o /dev/null -m 15 -w 'emsal=%{http_code}\\n' https://emsal.uyap.gov.tr/").result)
    else:
        sandbox = get_sandbox(create=False)
        print("durum:", sandbox.state, "| çekici:", worker_running(sandbox), "| iş:", len(ls(sandbox, "jobs")), "| sonuç:", len(ls(sandbox, "out")))
        print(sandbox.process.exec("tail -n 2 fetcher/worker.log").result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
