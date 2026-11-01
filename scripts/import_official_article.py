"""Preview/import one exact article from an allowlisted official MBS PDF.

No model, no inherited verification flags, no overwrite of differing text.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from psycopg.types.json import Jsonb
from psycopg.rows import tuple_row
from api.db import admin_database_connection
from ingestion.mevzuat.identity import canonical_article, primary_article
from ingestion.mevzuat.models import LegislationRecord
from ingestion.mevzuat.store import upsert_legislation
from ingestion.mevzuat.text_verify import fetch_official_pdf_text,extract_article_text,verify_article_text
from ingestion.text import content_hash

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--law',required=True)
    parser.add_argument('--article',required=True)
    parser.add_argument('--url',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    article=canonical_article(args.article)
    # Official URL validation is enforced by the downloader. Also bind the
    # document identifier to the requested law rather than trusting CLI labels.
    if not args.url.endswith('/1.5.'+args.law+'.pdf'):
        raise SystemExit('This command supports only the exact requested official law PDF')
    full=fetch_official_pdf_text(args.url,timeout_seconds=12)
    body=extract_article_text(full,article)
    if len(body)<200 or primary_article(body)!=article:
        raise SystemExit('Exact official article not found')
    now=datetime.now(timezone.utc)
    proof={'verified':True,'url':args.url,'article_no':article,'checked_at':now.isoformat(),
           'article_hash':content_hash(body),'document_text_hash':content_hash(full)}
    with admin_database_connection() as db:
        if not args.apply:
            db.execute('SET TRANSACTION READ ONLY')
        db.execute("SET LOCAL lock_timeout='2s'")
        db.execute("SET LOCAL statement_timeout='15s'")
        sibling=db.execute("""SELECT d.law_name FROM legislation_details d JOIN legal_sources s
            ON s.id=d.legal_source_id WHERE d.law_no=%s AND d.legislation_type='law'
            AND s.deleted_at IS NULL LIMIT 1""",(args.law,)).fetchone()
        if not sibling:
            raise SystemExit('Unknown law; do not infer its title')
        existing=db.execute("""SELECT to_jsonb(s) AS source,to_jsonb(d) AS details
            FROM legislation_details d JOIN legal_sources s ON s.id=d.legal_source_id
            WHERE d.law_no=%s AND d.legislation_type='law' AND d.article_no=%s
              AND s.is_current AND s.deleted_at IS NULL""",(args.law,article)).fetchall()
        if len(existing)>1:
            raise SystemExit('Ambiguous current article')
        if existing and not verify_article_text(existing[0]['source']['raw_text'],full,article_no=article).verified:
            raise SystemExit('Existing text differs from current official PDF; version review required')
        print(json.dumps({'law':args.law,'article':article,'official_chars':len(body),
                          'operation':'verify_existing' if existing else 'insert_missing',
                          'apply':args.apply},ensure_ascii=False))
        if not args.apply:
            return
        stamp=now.strftime('%Y%m%dT%H%M%S%fZ')
        backup=ROOT/'.local/corpus-repair-backups'/('official-'+stamp+'.json')
        backup.parent.mkdir(parents=True,exist_ok=True)
        with backup.open('x',encoding='utf-8') as file:
            json.dump({'before':existing,'official_article':body,'proof':proof},file,
                      ensure_ascii=False,indent=2,default=str)
            file.flush()
            import os
            os.fsync(file.fileno())
        metadata={'verified_against_mbs':True,'mbs_text_verification':proof}
        if existing:
            source=existing[0]['source']
            locked=db.execute('SELECT raw_text,content_hash FROM legal_sources WHERE id=%s FOR UPDATE',
                              (source['id'],)).fetchone()
            if locked['raw_text']!=source['raw_text'] or locked['content_hash']!=source['content_hash']:
                raise SystemExit('Concurrent source change; aborted')
            source_id=source['id']
        else:
            record=LegislationRecord(record_type='legislation',legislation_type='law',law_name=sibling['law_name'],
                law_no=args.law,article_no=article,article_title=None,title=sibling['law_name']+' m. '+article,
                raw_text=body,external_id='mevzuat:kanun:'+args.law+':m.'+article,content_hash=content_hash(body),
                source_url=args.url,scraped_at=now,metadata={**metadata,'source':'official_mbs_pdf',
                    'mevzuat_tur':'KANUN'})
            original_factory=db.row_factory
            try:
                db.row_factory=tuple_row  # ingestion store's documented cursor contract
                source_id=upsert_legislation(db,record).legal_source_id
            finally:
                db.row_factory=original_factory
            db.execute("UPDATE legal_sources SET ingestion_method='official_mbs_pdf_http' WHERE id=%s",(source_id,))
        # Existing policy permits verified MBS OR Gazette evidence. No Gazette
        # flag is invented/copied from a sibling; readiness is for this row only.
        db.execute("""UPDATE legal_sources SET metadata=metadata || %s,ingest_status='ready',
            last_verified_at=NOW() WHERE id=%s""",(Jsonb(metadata),source_id))
        print('Verified exact official article; source id:',source_id,'backup:',backup)


if __name__=='__main__':
    main()
