"""Preview then replace selected current provisions with exact official PDF text.

No similarity approval, guessed identities, hard deletes, or inherited Gazette
flags. Each application needs the digest of its fresh preview. Old sources,
chunks/citations remain historical; replacements are new current revisions.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import admin_database_connection
from ingestion.mevzuat.identity import article_headings, canonical_article, primary_article
from ingestion.mevzuat.models import LegislationRecord
from ingestion.mevzuat.store import upsert_legislation
from ingestion.mevzuat.text_verify import fetch_official_pdf_text, _comparison_key, strip_next_article_caption
from ingestion.text import content_hash, normalize_text
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]


def valid_document_url(url, law):
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and parsed.hostname in {'www.mevzuat.gov.tr', 'mevzuat.gov.tr'}
            and parsed.username is None and parsed.port in (None, 443) and not parsed.query and not parsed.fragment
            and bool(re.fullmatch(r'/mevzuatmetin/1\.\d+\.' + re.escape(law) + r'\.pdf', parsed.path, re.I)))


def resolve_document_url(law, rows):
    # Older statutes use other series (e.g. 1.3.*, not 1.5.*). Never guess a
    # replacement path after an HTML response: use observed official links.
    urls = set()
    for row in rows:
        metadata = row['source'].get('metadata') or {}
        for url in ((metadata.get('mbs_verification') or {}).get('pdf_url'),
                    (metadata.get('mbs_text_verification') or {}).get('url')):
            if valid_document_url(url, law):
                urls.add(url)
    if len(urls) == 1:
        return next(iter(urls))
    from ingestion.mevzuat_bilgi_sistemi.portal import MbsClient
    names = {r['details']['law_name'] for r in rows}
    if len(names) != 1:
        raise ValueError('Current law title missing or ambiguous')
    document = MbsClient(timeout_seconds=15, max_retries=1).search_law(law, law_name=next(iter(names)))
    if not valid_document_url(document.pdf_url, law):
        raise ValueError('Observed official PDF link does not match the requested law')
    return document.pdf_url


def official_article(full, article):
    headings = article_headings(full)
    matches = [i for i, h in enumerate(headings) if h.identity == canonical_article(article)]
    if len(matches) != 1:
        raise ValueError('Official heading missing or ambiguous')
    index = matches[0]
    end = headings[index+1].start if index+1 < len(headings) else len(full)
    body = normalize_text(full[headings[index].start:end])
    if index+1 < len(headings):
        body = strip_next_article_caption(body)
    if len(body) < 40 or primary_article(body) != canonical_article(article):
        raise ValueError('Incomplete official article')
    return body


def preview(law, articles, full, rows, *, repair_identities=False, official_url=None):
    entries = []
    for article in articles:
        matching = [r for r in rows if canonical_article(r['details']['article_no']) == article]
        if len(matching) != 1:
            raise ValueError('Current source missing or ambiguous: ' + article)
        row = matching[0]
        source = row['source']
        identity_error = primary_article(source['raw_text'] or '') != article
        if identity_error and not repair_identities:
            raise ValueError('Existing identity requires separate repair: ' + article)
        body = official_article(full, article)
        entries.append(dict(article=article, before=row, official_text=body,
                            identity_correction=identity_error,
                            official_hash=content_hash(body),
                            operation='verify_exact' if content_hash(body) == source['content_hash'] else 'new_official_revision'))
    url = official_url or 'https://www.mevzuat.gov.tr/MevzuatMetin/1.5.' + law + '.pdf'
    if not valid_document_url(url, law):
        raise ValueError('Official PDF address mismatch')
    payload = dict(law=law, official_url=url, document_text_hash=content_hash(full), entries=entries)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return payload, digest


def apply(db, payload, digest, expected):
    if digest != expected:
        raise ValueError('Preview changed; refusing writes')
    for item in payload['entries']:
        old = item['before']['source']
        locked = db.execute('SELECT to_jsonb(s) AS source FROM legal_sources s WHERE id=%s FOR UPDATE', (old['id'],)).fetchone()
        if not locked or locked['source'] != old:
            raise ValueError('Concurrent source change; refusing writes')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = ROOT / '.local/corpus-repair-backups' / ('official-refresh-' + stamp + '.json')
    backup.parent.mkdir(parents=True, exist_ok=True)
    with backup.open('x', encoding='utf-8') as stream:
        json.dump(dict(preview_digest=digest, **payload), stream, ensure_ascii=False, default=str)
        stream.flush()
        os.fsync(stream.fileno())
    now = datetime.now(timezone.utc)
    results = []
    url = payload['official_url']
    for item in payload['entries']:
        old, detail = item['before']['source'], item['before']['details']
        proof = dict(verified=True, url=url, article_no=item['article'], checked_at=now.isoformat(),
                     article_hash=item['official_hash'], document_text_hash=payload['document_text_hash'],
                     method='exact_official_article_extraction')
        metadata = dict(verified_against_mbs=True, mbs_text_verification=proof,
                        corpus_refresh=dict(preview_digest=digest, previous_source_id=old['id']))
        if item['operation'] == 'verify_exact':
            source_id, status = old['id'], 'verified_exact'
        else:
            record = LegislationRecord(record_type='legislation', legislation_type='law',
                law_name=detail['law_name'], law_no=payload['law'], article_no=item['article'],
                article_title=detail['article_title'], title=detail['law_name'] + ' m. ' + item['article'],
                raw_text=item['official_text'], external_id=old['external_id'], content_hash=item['official_hash'],
                source_url=url, scraped_at=now, metadata=metadata)
            factory = db.row_factory
            try:
                db.row_factory = tuple_row
                result = upsert_legislation(db, record, max_chunk_chars=16000)
            finally:
                db.row_factory = factory
            source_id, status = result.legal_source_id, result.status
        current = db.execute('SELECT is_current,content_hash FROM legal_sources WHERE id=%s', (source_id,)).fetchone()
        if not current or not current['is_current'] or current['content_hash'] != item['official_hash']:
            raise ValueError('Replacement is not the expected current official text; rollback')
        db.execute("""UPDATE legal_sources SET metadata=metadata || %s, ingest_status='ready',
            ingestion_method='official_mbs_pdf_http', last_verified_at=NOW() WHERE id=%s""", (Jsonb(metadata), source_id))
        if item.get('identity_correction') and str(source_id) != str(old['id']):
            # A mislabeled historical snapshot is not a valid historical law.
            # Retain citations/backup but exclude it from all public evidence.
            db.execute("""UPDATE legal_sources SET ingest_status='pending',
                metadata=metadata || %s WHERE id=%s""", (Jsonb(dict(
                    corpus_identity_error=True, corrected_by_source_id=str(source_id))), old['id']))
        results.append(dict(article=item['article'], source_id=str(source_id), previous_source_id=old['id'], status=status))
    return results, str(backup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--law', required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--articles', nargs='+')
    target.add_argument('--all-current', action='store_true')
    parser.add_argument('--repair-identities', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expect-digest')
    parser.add_argument('--summary', action='store_true')
    args = parser.parse_args()
    if not args.law.isdecimal() or (args.apply and not args.expect_digest):
        parser.error('Numeric law; apply requires --expect-digest')
    articles = list(dict.fromkeys(canonical_article(a) for a in args.articles)) if args.articles else None
    with admin_database_connection() as db:
        if not args.apply:
            db.execute('SET TRANSACTION READ ONLY')
        db.execute("SET LOCAL lock_timeout='2s'")
        # A validated, backed-up refresh must not fail halfway because an index
        # update takes longer on a busy disk. Transaction rollback remains atomic.
        db.execute("SET LOCAL statement_timeout='0'" if args.apply else "SET LOCAL statement_timeout='15s'")
        rows = db.execute("""SELECT to_jsonb(s) AS source,to_jsonb(d) AS details
            FROM legal_sources s JOIN legislation_details d ON d.legal_source_id=s.id
            WHERE s.source_type='legislation' AND s.is_current AND s.deleted_at IS NULL
              AND d.legislation_type='law' AND d.law_no=%s
              AND (%s::text[] IS NULL OR d.article_no=ANY(%s))
              ORDER BY d.article_no""", (args.law, articles, articles)).fetchall()
        names = {r['details']['law_name'] for r in rows}
        url = resolve_document_url(args.law, rows)
        full = fetch_official_pdf_text(url, timeout_seconds=15)
        if len(names) != 1 or _comparison_key(next(iter(names))) not in _comparison_key(full[:3000]):
            raise ValueError('Official PDF title does not match the stored law')
        if not re.search(r'Kanun\s+Numarası\s*:\s*' + re.escape(args.law) + r'\b', full[:3000], re.I):
            raise ValueError('Official PDF number not confirmed')
        skipped = []
        if articles is None:
            articles = []
            for row in rows:
                article = canonical_article(row['details']['article_no'])
                try:
                    preview(args.law, [article], full, rows, repair_identities=args.repair_identities, official_url=url)
                    articles.append(article)
                except ValueError as error:
                    skipped.append(dict(article=article, reason=str(error)))
        payload, digest = preview(args.law, articles, full, rows, repair_identities=args.repair_identities, official_url=url)
        print(json.dumps(dict(law=args.law, digest=digest, apply=args.apply,
            skipped=skipped,
            operation_counts=dict(Counter(i['operation'] for i in payload['entries'])),
            identity_corrections=sum(i.get('identity_correction', False) for i in payload['entries']),
            **({} if args.summary else dict(operations=[dict(article=i['article'], operation=i['operation'], characters=len(i['official_text'])) for i in payload['entries']]))), ensure_ascii=False), flush=True)
        if args.apply:
            results, backup = apply(db, payload, digest, args.expect_digest)
            print(json.dumps(dict(backup=backup, **(dict(applied=len(results), statuses=dict(Counter(r['status'] for r in results)))
                if args.summary else dict(results=results))), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
