"""mevzuat_verify keep-alive: checkpoint next_run_at'e uyar, süreci öldürmez."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from time import sleep

import psycopg
from dotenv import load_dotenv

from worker.jobs import run_sync
from worker.models import SyncRequest
from worker.repository import SyncRepository

load_dotenv()


def main() -> None:
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL tanımlı değil")
    while True:
        with psycopg.connect(url, autocommit=True) as connection:
            checkpoint = SyncRepository(connection).get_checkpoint("mevzuat_verify")
            now = datetime.now(UTC)
            if checkpoint.next_run_at and checkpoint.next_run_at > now:
                wait = min(30.0, max(1.0, (checkpoint.next_run_at - now).total_seconds()))
                sleep(wait)
                continue
            run_sync(connection, SyncRequest(source="mevzuat_verify", resume=True))
        sleep(1)


if __name__ == "__main__":
    main()
