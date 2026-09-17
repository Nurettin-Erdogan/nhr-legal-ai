"""One paced KDK backfill pass from a host that can reach the official portal."""

from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worker.backfill import embed_new_legal_chunks, prepare_full_backfill  # noqa: E402
from worker.jobs import run_sync  # noqa: E402
from worker.models import Checkpoint, SyncRequest  # noqa: E402
from worker.repository import SyncRepository  # noqa: E402

LOG = logging.getLogger("local-kdk")


def due(checkpoint: Checkpoint, *, now: datetime) -> bool:
    if checkpoint.health_state == "blocked":
        return False
    return checkpoint.next_run_at is None or checkpoint.next_run_at <= now


def main() -> int:
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        LOG.error("DATABASE_ADMIN_URL yerel .env içinde tanımlı değil")
        return 2
    with psycopg.connect(url, autocommit=True) as connection:
        prepare_full_backfill(connection, "kdk")
        checkpoint = SyncRepository(connection).get_checkpoint("kdk")
        if not due(checkpoint, now=datetime.now(UTC)):
            LOG.info("KDK sıradaki turu bekliyor: %s", checkpoint.next_run_at)
            return 0
        result = run_sync(connection, SyncRequest(source="kdk", lane="backfill",
                                                   resume=True, max_records=40))
        counters = result.get("counters") or {}
        LOG.info("KDK turu status=%s created=%s updated=%s error=%s",
                 result.get("status"), counters.get("records_created"),
                 counters.get("records_updated"), result.get("error"))
        if result.get("status") in {"failed", "captcha_required"}:
            return 2
        if counters.get("records_created") or counters.get("records_updated"):
            embedded = embed_new_legal_chunks(connection)
            if embedded.get("error"):
                return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
