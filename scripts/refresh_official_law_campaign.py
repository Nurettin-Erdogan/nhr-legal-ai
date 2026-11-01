"""Resumable, single-client official-law refresh. No decisions/private data.

Runs the digest-bound, backed-up refresh helper sequentially. PDF ambiguity is
retained in the report, never guessed away. Create .local/corpus-refresh/STOP
to stop after the current law. A second runner cannot acquire the lock.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import database_connection

ROOT = Path(__file__).resolve().parents[1]

STATE = ROOT / '.local/corpus-refresh'
HELPER = ROOT / 'scripts/refresh_official_law.py'
LAST_FAILURE = None


def failure_code(stderr):
    if 'HTTP Error 404' in stderr:
        return 'official_document_not_found'
    if 'MBS beklenen PDF' in stderr:
        return 'unexpected_official_response'
    if 'MBS PDF indirilemedi' in stderr:
        return 'portal_unavailable'
    if 'MBS HTTP hatası' in stderr:
        return 'portal_unavailable'
    if 'Official PDF title does not match' in stderr:
        return 'official_title_mismatch'
    if 'Official PDF number not confirmed' in stderr:
        return 'official_number_not_confirmed'
    return 'helper_failed_requires_review'


def now():
    return datetime.now(timezone.utc).isoformat()


def run_helper(law, digest=None):
    global LAST_FAILURE
    LAST_FAILURE = None
    command = [sys.executable, '-X', 'utf8', str(HELPER), '--law', law,
               '--all-current', '--repair-identities', '--summary']
    if digest:
        command += ['--apply', '--expect-digest', digest]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        # Raw provider/DB exceptions are deliberately not persisted.
        LAST_FAILURE = failure_code(result.stderr)
        return None
    try:
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    except (ValueError, TypeError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=10, help='0: all remaining laws in this snapshot')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.limit < 0:
        parser.error('limit must not be negative')
    STATE.mkdir(parents=True, exist_ok=True)
    lock = STATE / 'runner.lock'
    try:
        with lock.open('x', encoding='utf-8') as stream:
            stream.write(str(os.getpid()))
    except FileExistsError:
        raise SystemExit('A campaign lock exists; inspect its runner before restarting')
    try:
        manifest = STATE / 'manifest.json'
        if manifest.exists():
            queue = json.loads(manifest.read_text(encoding='utf-8'))['laws']
        else:
            with database_connection() as db:
                db.execute('SET TRANSACTION READ ONLY')
                rows = db.execute("""SELECT DISTINCT d.law_no FROM legislation_details d
                    JOIN legal_sources s ON s.id=d.legal_source_id
                    WHERE s.source_type='legislation' AND s.is_current AND s.deleted_at IS NULL
                      AND d.legislation_type='law' AND d.law_no ~ '^[0-9]+$'
                    ORDER BY d.law_no""").fetchall()
            # The six applied pilot laws are separately audited; keep their
            # unresolved articles listed rather than reapplying them endlessly.
            queue = [r['law_no'] for r in rows if r['law_no'] not in {'6325','6098','4857','6361','4458','1512'}]
            with manifest.open('x', encoding='utf-8') as stream:
                json.dump(dict(created=now(), scope='current existing law records only', laws=queue), stream)
        journal = STATE / ('applied.jsonl' if args.apply else 'preview.jsonl')
        finished = set()
        if journal.exists():
            for line in journal.read_text(encoding='utf-8').splitlines():
                record = json.loads(line)
                legacy_unclassified_failure = record.get('status') == 'preview_failed_no_change' and not record.get('reason')
                if (record.get('reason') not in {'portal_unavailable', 'unexpected_official_response'}
                        and not legacy_unclassified_failure):
                    finished.add(record['law'])
        attempted = 0
        print(json.dumps(dict(started=now(), apply=args.apply, queued=len(queue), already_attempted=len(finished))), flush=True)
        for law in queue:
            if law in finished:
                continue
            if (STATE / 'STOP').exists() or (args.limit and attempted >= args.limit):
                break
            if shutil.disk_usage(ROOT).free < 30 * 1024**3:
                print('Stopped: workspace drive has less than 30 GiB free', flush=True)
                break
            outcome = dict(law=law, started=now(), apply=args.apply)
            preview = run_helper(law)
            if not preview:
                outcome['status'] = 'preview_failed_no_change'
                outcome['reason'] = LAST_FAILURE
            elif not args.apply:
                outcome.update(status='preview_only', preview=preview[0])
            else:
                time.sleep(5)  # one official client, no faster parallel portal traffic
                applied = run_helper(law, preview[0]['digest'])
                if applied and len(applied) == 2:
                    outcome.update(status='partial' if applied[0]['skipped'] else 'applied',
                                   preview=applied[0], result=applied[1])
                else:
                    outcome['status'] = 'apply_failed_rolled_back'
                    outcome['reason'] = LAST_FAILURE
            outcome['finished'] = now()
            with journal.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(outcome, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            print(json.dumps(outcome, ensure_ascii=False), flush=True)
            attempted += 1
            if outcome.get('reason') in {'portal_unavailable', 'unexpected_official_response'}:
                print('Paused: official portal unavailable or unexpected response; no bypass/retry loop', flush=True)
                break
            time.sleep(5)
        print(json.dumps(dict(stopped=now(), attempted=attempted)), flush=True)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
