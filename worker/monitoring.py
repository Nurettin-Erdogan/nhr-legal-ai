from __future__ import annotations

from datetime import datetime

from worker.jobs import run_sync
from worker.models import SyncRequest
from worker.repository import SyncRepository


def format_status(connection) -> str:
    repo = SyncRepository(connection)
    lines = ["NHR Legal Data Collector", ""]
    for checkpoint in repo.list_checkpoints():
        lines.append(
            f"{checkpoint.source_name}: health={checkpoint.health_state} "
            f"last_success={checkpoint.last_successful_sync_at} "
            f"next={checkpoint.next_run_at} "
            f"window={checkpoint.last_date_from}..{checkpoint.last_date_to} "
            f"failures={checkpoint.consecutive_failures}"
        )
        if checkpoint.last_error:
            lines.append(f"  last_error={checkpoint.last_error}")
    runs = repo.list_runs(limit=5)
    if runs:
        lines.append("")
        lines.append("Son çalıştırmalar:")
        for run in runs:
            lines.append(
                f"  {run['started_at']} {run['source_adapter']} {run['status']} "
                f"seen={run['processed_count']} created={run['created_count']}"
            )
    return "\n".join(lines)


def run_named_source(connection, request: SyncRequest) -> dict:
    return run_sync(connection, request)
