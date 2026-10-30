"""Resumable read-only public text/hash scan; NOT official-source verification.

No private tables, model calls or database writes. Findings contain identifiers,
not full text. Checkpoints are local; STOP finishes the current batch. This is a
moving-corpus scan, not a transactionally frozen snapshot: changed/inserted rows
require a later reconciliation pass before whole-corpus acceptance.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import database_connection
from ingestion.text import content_hash

ROOT = Path(__file__).resolve().parents[1]

STATE = ROOT / '.local/public-text-integrity'


def inspect_text(row):
    text = row['raw_text'] or ''
    issues = []
    if not text.strip():
        issues.append('empty_text')
    if row['content_hash'] != content_hash(text):
        issues.append('hash_mismatch')
    return issues


def save_checkpoint(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    # Windows readers/antivirus can briefly hold the destination open. Keep
    # the previous durable checkpoint until an atomic replacement succeeds.
    for attempt in range(20):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch-size', type=int, default=250)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 500:
        parser.error('batch-size must be 1..500')
    STATE.mkdir(parents=True, exist_ok=True)
    lock = STATE / 'runner.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(str(os.getpid()))
    try:
        path = STATE / 'checkpoint.json'
        state = json.loads(path.read_text()) if path.exists() else dict(
            started=datetime.now(timezone.utc).isoformat(), last_id=None,
            scanned=0, counts={}, status='running',
            scope='nondeleted public source text/hash only; not official comparison',
            consistency='moving corpus; final reconciliation required')
        if state['status'] == 'scan_exhausted_requires_reconciliation':
            print(json.dumps(state), flush=True)
            return
        counts = Counter(state['counts'])
        while not (STATE / 'STOP').exists():
            with database_connection() as db:
                db.execute('SET TRANSACTION READ ONLY')
                db.execute("SET LOCAL statement_timeout='60s'")
                db.execute("SET LOCAL lock_timeout='2s'")
                rows = db.execute("""SELECT id,source_type,ingest_status,is_current,
                    raw_text,content_hash FROM legal_sources
                    WHERE deleted_at IS NULL
                      AND source_type IN ('legislation','court_decision','other')
                      AND (%s::uuid IS NULL OR id > %s::uuid)
                    ORDER BY id LIMIT %s""",
                    (state['last_id'], state['last_id'], args.batch_size)).fetchall()
            if not rows:
                state['status'] = 'scan_exhausted_requires_reconciliation'
                save_checkpoint(path, state)
                print(json.dumps(state), flush=True)
                return
            # Findings precede checkpoint: after interruption a batch may repeat.
            # Consumers must deduplicate by source ID + issue + stored hash.
            with (STATE / 'findings.jsonl').open('a', encoding='utf-8') as stream:
                for row in rows:
                    counts['type:' + row['source_type']] += 1
                    for issue in inspect_text(row):
                        counts[issue] += 1
                        stream.write(json.dumps(dict(id=str(row['id']), issue=issue,
                            source_type=row['source_type'], status=row['ingest_status'],
                            current=row['is_current'], stored_hash=row['content_hash'])) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            state.update(last_id=str(rows[-1]['id']), scanned=state['scanned'] + len(rows),
                         counts=dict(counts), updated=datetime.now(timezone.utc).isoformat())
            save_checkpoint(path, state)
            if state['scanned'] % 10000 < len(rows):
                print(json.dumps(state), flush=True)
            time.sleep(0.2)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
