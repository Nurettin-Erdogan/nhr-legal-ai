"""Single bounded public AYM acquisition using existing worker/checkpoint locks.

SSD staging only, no daemon, no cloud model, no retry loop or server changes.
The worker's own reconciliation decides progress; a finished batch never means
the collection is complete. Unsupported institutions are not impersonated.
"""
import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import shutil
import sys
from time import sleep

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STATE = ROOT / '.local/official-data-campaign'


def storage_available(root, minimum_gib=100, *, usage=shutil.disk_usage):
    if not 50 <= minimum_gib <= 500:
        raise ValueError('Safety reserve must be 50–500 GiB')
    return usage(root).free >= minimum_gib * 1024**3


def archive_directory(root):
    root = Path(root).resolve()
    archive = (root / '.local/official-data-campaign/raw/aym').resolve()
    if not archive.is_relative_to(root):
        raise ValueError('Archive must remain inside the project SSD staging area')
    return archive


def write_state(payload):
    STATE.mkdir(parents=True, exist_ok=True)
    temporary = STATE / 'aym-batch.tmp'
    with temporary.open('w', encoding='utf-8') as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, STATE / 'aym-batch.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-records', type=int, default=25)
    parser.add_argument('--min-free-gib', type=int, default=100)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--batches', type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.max_records <= 100:
        parser.error('Use a bounded batch of 1–100 records')
    if not 1 <= args.batches <= 100:
        parser.error('Use 1–100 checkpointed batches')
    if not storage_available(ROOT, args.min_free_gib):
        parser.exit(2, 'SSD safety reserve reached; no ingestion started\n')
    stop = STATE / 'STOP'
    if stop.exists():
        parser.exit(2, 'STOP marker exists; not overriding it\n')
    archive = archive_directory(ROOT)
    archive.mkdir(parents=True, exist_ok=True)
    # Process-local options only: do not change .env or the existing daemon.
    os.environ['INGESTION_SNAPSHOT_DIR'] = str(archive)
    os.environ['INGESTION_MAX_RETRIES'] = '1'
    os.environ['AYM_DELAY_SECONDS'] = str(max(4.5, float(os.getenv('AYM_DELAY_SECONDS', '4.5'))))
    from api.config import get_settings
    from worker.jobs import run_sync
    from worker.models import SyncRequest
    from worker.adapters.aym import AymSourceAdapter
    from ingestion.aym.portal import AymPortalClient
    from api.ai.official_research import _PacedOpener
    import psycopg
    settings = get_settings()
    if not settings.admin_database_url:
        parser.exit(2, 'Public ingestion database configuration is missing\n')
    logging.disable(logging.CRITICAL)  # Persist sanitized result fields only.
    state = dict(source='aym', started=datetime.now(timezone.utc).isoformat(),
        status='starting', pid=os.getpid(), max_records=args.max_records,
        max_batches=args.batches, batches_finished=0,
        storage='project SSD staging', reserve_gib=args.min_free_gib,
        collection_complete=False, dry_run=args.dry_run)
    write_state(state)
    def should_stop():
        return stop.exists() or not storage_available(ROOT, args.min_free_gib)
    try:
        totals = {}
        client = AymPortalClient(max_retries=1, timeout_seconds=30, opener=_PacedOpener())
        for index in range(args.batches):
            if should_stop():
                state['status'] = 'stopped_by_safety_guard'
                break
            state.update(status='running', batch=index + 1)
            write_state(state)
            with psycopg.connect(settings.admin_database_url, autocommit=True, connect_timeout=5) as db:
                result = run_sync(db, SyncRequest(source='aym', max_records=args.max_records,
                    resume=True, dry_run=args.dry_run, lane='backfill'), should_stop=should_stop,
                    adapter=AymSourceAdapter(client=client))
            counts = result.get('counters', {})
            for name, value in counts.items():
                if type(value) is int:
                    totals[name] = totals.get(name, 0) + value
            state.update(status=result.get('status', 'unknown'), counters=totals,
                         batches_finished=index + 1, run_id=str(result.get('run_id') or ''))
            write_state(state)
            print(json.dumps(state, ensure_ascii=False), flush=True)
            # A failed/partial/captcha batch is not skipped to make progress.
            # The worker checkpoint preserves the exact unresolved position.
            if (state['status'] not in {'success', 'completed'} or args.dry_run
                    or not counts.get('records_seen')
                    or (result.get('checkpoint') or {}).get('last_cursor', {}).get('complete')):
                break
            if index + 1 < args.batches:
                sleep(5)
    except Exception as exc:
        state.update(status='failed', failure_type=type(exc).__name__)
    state['finished'] = datetime.now(timezone.utc).isoformat()
    state['storage_reserve_reached'] = not storage_available(ROOT, args.min_free_gib)
    write_state(state)
    print(json.dumps(state, ensure_ascii=False), flush=True)
    return 0 if state['status'] in {'success', 'completed', 'partial'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
