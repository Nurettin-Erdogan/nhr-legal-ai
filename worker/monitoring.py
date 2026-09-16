from __future__ import annotations

from worker.jobs import run_sync
from worker.lanes import canonical_source
from worker.models import SyncRequest
from worker.repository import SyncRepository


def format_status(connection) -> str:
    repo = SyncRepository(connection)
    lines = ["NHR Legal Data Collector", ""]
    for checkpoint in repo.list_checkpoints():
        lane = "current" if checkpoint.source_name.endswith(":current") else "backfill"
        source = canonical_source(checkpoint.source_name)
        cursor = checkpoint.last_cursor or {}
        lines.append(
            f"{source} [{lane}]: health={checkpoint.health_state} "
            f"last_success={checkpoint.last_successful_sync_at} "
            f"next={checkpoint.next_run_at} "
            f"window={checkpoint.last_date_from}..{checkpoint.last_date_to} "
            f"complete={cursor.get('window_complete', cursor.get('complete'))} "
            f"failures={checkpoint.consecutive_failures}"
        )
        if checkpoint.last_error:
            lines.append(f"  last_error={checkpoint.last_error}")
    coverage = repo.list_coverage(limit=40)
    if coverage:
        lines.append("")
        lines.append("Kapsama (son pencereler):")
        for row in coverage:
            lines.append(
                f"  {row['source_name']} {row['date_from']}..{row['date_to']} "
                f"chamber={row['chamber'] or '-'} complete={row['complete']} "
                f"seen={row['seen_count']} stored={row['stored_count']} "
                f"dup={row['duplicate_count']} failed={row['failed_count']}"
            )
    runs = repo.list_runs(limit=8)
    if runs:
        lines.append("")
        lines.append("Son çalıştırmalar:")
        for run in runs:
            lines.append(
                f"  {run['started_at']} {run['source_adapter']} {run['status']} "
                f"seen={run['processed_count']} created={run['created_count']}"
            )
    return "\n".join(lines)


def coverage_payload(connection, source_name: str | None = None) -> dict:
    repo = SyncRepository(connection)
    rows = repo.list_coverage(source_name=source_name, limit=200)
    checkpoints = {
        item.source_name: item
        for item in repo.list_checkpoints()
        if source_name is None
        or canonical_source(item.source_name) == source_name
        or item.source_name == source_name
    }
    return {
        "windows": rows,
        "lanes": [
            {
                "job": name,
                "source": canonical_source(name),
                "lane": "current" if name.endswith(":current") else "backfill",
                "window_from": cp.last_date_from,
                "window_to": cp.last_date_to,
                "next_run_at": cp.next_run_at,
                "last_successful_sync": cp.last_successful_sync_at,
                "health": cp.health_state,
                "cursor": cp.last_cursor,
            }
            for name, cp in checkpoints.items()
        ],
    }


def run_named_source(connection, request: SyncRequest) -> dict:
    return run_sync(connection, request)
