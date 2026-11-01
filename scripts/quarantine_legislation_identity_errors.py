"""Hide confirmed primary-heading identity mismatches, with reversible backup.

No text/chunk/citation deletion. Only current, ready public legislation whose
near-start heading disagrees with its stored article is eligible.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import admin_database_connection
from ingestion.mevzuat.identity import primary_article, canonical_article
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]


def mismatch(article, text):
    heading = primary_article(text or '')
    return bool(heading and heading != canonical_article(article))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expect-digest')
    args = parser.parse_args()
    if args.apply and not args.expect_digest:
        parser.error('Apply requires preview digest')
    with admin_database_connection() as db:
        if not args.apply:
            db.execute('SET TRANSACTION READ ONLY')
        db.execute("SET LOCAL statement_timeout='0'")
        db.execute("SET LOCAL lock_timeout='2s'")
        ids = []
        with db.cursor(name='identity_quarantine_scan') as cursor:
            cursor.itersize = 250
            cursor.execute("""SELECT s.id,d.article_no,s.raw_text FROM legal_sources s
                JOIN legislation_details d ON d.legal_source_id=s.id
                WHERE s.source_type='legislation' AND s.is_current AND s.deleted_at IS NULL
                  AND s.ingest_status='ready'""")
            for row in cursor:
                if mismatch(row['article_no'], row['raw_text']):
                    ids.append(row['id'])
        rows = db.execute("""SELECT to_jsonb(s) AS source,to_jsonb(d) AS details
            FROM legal_sources s JOIN legislation_details d ON d.legal_source_id=s.id
            WHERE s.id=ANY(%s::uuid[]) ORDER BY s.id""", (ids,)).fetchall()
        digest = hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
        print(json.dumps(dict(count=len(rows), digest=digest, apply=args.apply, records=[
            dict(id=r['source']['id'], law=r['details']['law_no'], article=r['details']['article_no'],
                 heading=primary_article(r['source']['raw_text'])) for r in rows]), ensure_ascii=False), flush=True)
        if not args.apply:
            return
        if digest != args.expect_digest:
            raise ValueError('Preview changed; no writes')
        for row in rows:
            locked = db.execute('SELECT to_jsonb(s) AS source FROM legal_sources s WHERE id=%s FOR UPDATE',
                                (row['source']['id'],)).fetchone()
            if locked['source'] != row['source']:
                raise ValueError('Concurrent change; no writes')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = ROOT / '.local/corpus-repair-backups' / ('identity-quarantine-' + stamp + '.json')
        backup.parent.mkdir(exist_ok=True, parents=True)
        with backup.open('x', encoding='utf-8') as stream:
            json.dump(dict(digest=digest, before=rows), stream, ensure_ascii=False, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        for row in rows:
            db.execute("""UPDATE legal_sources SET ingest_status='pending', metadata=metadata || %s
                WHERE id=%s""", (Jsonb(dict(corpus_identity_error=True,
                    corpus_review_reason='stored_article_primary_heading_mismatch',
                    corpus_quarantine_digest=digest)), row['source']['id']))
        print(json.dumps(dict(quarantined=len(rows), backup=str(backup))), flush=True)


if __name__ == '__main__':
    main()
