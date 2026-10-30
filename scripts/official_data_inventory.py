"""Write an honest public-data acquisition inventory. No ingestion/model calls."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingestion.official_catalog import collection_report

ROOT = Path(__file__).resolve().parents[1]


def build_report(counters=()):
    source_counts = Counter()
    for row in counters:
        key, n = row['key'], row['n']
        if key.startswith('src|'):
            source_counts[key.split('|', 2)[1]] += n
    return dict(updated=datetime.now(timezone.utc).isoformat(),
        scope='public legal collections only; private documents excluded',
        complete=False, stored_counter_totals=dict(source_counts),
        counter_warning='Stored counters are not verified unique IDs or coverage denominators',
        institutions=21, collections=collection_report())


def refresh_progress(journal, checkpoint):
    """Partial/skipped articles remain open even after a law job has finished."""
    latest = {}
    if journal.exists():
        for line in journal.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            latest[row['law']] = row
    unresolved = []
    for law, row in latest.items():
        skipped = (row.get('preview') or {}).get('skipped', [])
        unresolved.extend(dict(law=law, article=item.get('article'), reason=item.get('reason')) for item in skipped)
        if row.get('status') not in {'applied', 'partial'}:
            unresolved.append(dict(law=law, article=None,
                                   reason=row.get('reason') or row.get('status')))
    scan = json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else {}
    return dict(law_refresh=dict(scope='existing current law records only; not every official law',
        attempted_laws=len(latest), statuses=dict(Counter(r.get('status') for r in latest.values())),
        unresolved_items=unresolved, complete=False),
        text_hash_scan={k: scan.get(k) for k in ('scanned', 'status', 'updated', 'scope', 'consistency')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', action='store_true', help='Read cached public counters; no full-text scan')
    args = parser.parse_args()
    counters = []
    if args.database:
        from api.db import database_connection
        with database_connection() as db:
            db.execute('SET TRANSACTION READ ONLY')
            counters = db.execute('SELECT * FROM corpus_counts()').fetchall()
    report = build_report(counters)
    report['campaign_progress'] = refresh_progress(ROOT / '.local/corpus-refresh/applied.jsonl',
        ROOT / '.local/public-text-integrity/checkpoint.json')
    batch_state = ROOT / '.local/official-data-campaign/aym-batch.json'
    if batch_state.exists():
        report['campaign_progress']['aym_batch'] = json.loads(batch_state.read_text(encoding='utf-8'))
    destination = ROOT / '.local/official-data-campaign/inventory.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, destination)
    print(json.dumps(dict(institutions=report['institutions'], collections=len(report['collections']),
        capabilities=dict(Counter(c['capability'] for c in report['collections'])),
        stored_counter_totals=report['stored_counter_totals'], complete=False,
        report=str(destination)), ensure_ascii=False))


if __name__ == '__main__':
    main()
