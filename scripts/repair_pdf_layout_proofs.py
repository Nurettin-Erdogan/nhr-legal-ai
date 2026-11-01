"""Preview/apply exact, PDF-layout-backed captions for configured statutes.

This updates public source metadata only. It never changes raw legal text,
revision, chunks, verification status, or user/private data. Default is read-only.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import statute_hints
from api.ai.free_answer import _usable
from api.ai.official_transport import fetch_public_document
from api.ai.provision_context import complete_provision
from api.db import admin_database_connection, database_connection
from api.ai.rag import RAGContext
from ingestion.mevzuat.identity import article_headings, canonical_article
from ingestion.mevzuat.pdf_layout import exact_suffix_for_caption, extract_layout_captions
from ingestion.mevzuat.text_verify import extract_article_text
from ingestion.text import content_hash
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]

_URL = re.compile(r"https://(?:www\.)?mevzuat\.gov\.tr/MevzuatMetin/1\.\d+\.(\d+)\.pdf\Z", re.I)
_METHOD = 'pypdf_bold_caption_exact_suffix_v1'
# The read-only admission audit identified these 12 exact article records as
# blocked by an attached next-article heading. Do not annotate other statutes.
_ADMISSION_BLOCKED_REFERENCES = {
    ('2004', '257'), ('2918', '85'), ('4721', '1023'),
    ('6098', '77'), ('6098', '117'), ('6098', '120'), ('6098', '146'),
    ('6098', '227'), ('6098', '342'), ('6098', '345'), ('6098', '350'),
    ('6325', '18/A'),
}


def _references():
    items = {(h.law_no, canonical_article(h.article_no))
             for topic in statute_hints.TOPICS for h in topic.hints}
    items.update((h.law_no, canonical_article(h.article_no)) for h in statute_hints._EMPLOYMENT_RIGHTS_HINTS)
    return sorted(items & _ADMISSION_BLOCKED_REFERENCES)


def _fetch_pdf(url, law):
    match = _URL.fullmatch(url or '')
    if not match or match.group(1) != law:
        raise ValueError('Official PDF URL/law mismatch')
    document = fetch_public_document(url, timeout=30, max_bytes=20 * 1024 * 1024)
    if document.content_type != 'application/pdf' or not document.body.startswith(b'%PDF'):
        raise ValueError('Official endpoint did not return a PDF')
    full_text, captions = extract_layout_captions(document.body)
    return document, full_text, captions


def _next_heading(full_text, article):
    headings = article_headings(full_text)
    matches = [index for index, item in enumerate(headings) if item.identity == article]
    if len(matches) != 1 or matches[0] + 1 >= len(headings):
        return None
    return headings[matches[0] + 1].identity


def _context(row, article):
    return RAGContext(
        chunk_id=row['id'], source_id=row['id'], source_type='legislation', title=row['title'],
        source_url=row['source_url'], authority='Mevzuat Bilgi Sistemi', court_name=None, chamber=None,
        docket_no=None, decision_no=None, decision_date=None, law_name=row['law_name'], law_no=row['law_no'],
        article_no=article, article_title=row['article_title'], content=row['raw_text'], rank=1.0,
        source_version=row.get('source_version'), revision=row.get('revision'), verification='official')


def preview(connection):
    references = _references()
    laws = sorted({law for law, _ in references})
    rows = connection.execute("""
        SELECT s.id, s.raw_text, s.content_hash, s.metadata, s.source_url, s.source_version, s.revision,
               d.law_no, d.article_no, d.law_name, d.article_title, s.title
        FROM legal_sources s JOIN legislation_details d ON d.legal_source_id=s.id
        WHERE s.source_type='legislation' AND s.deleted_at IS NULL AND s.is_current
          AND s.ingest_status='ready' AND d.legislation_type='law'
          AND d.law_no = ANY(%s)
    """, (laws,)).fetchall()
    by_ref = {}
    for row in rows:
        key = (row['law_no'], canonical_article(row['article_no']))
        by_ref.setdefault(key, []).append(row)
    pdfs, pdf_errors, outcomes = {}, {}, []
    for law, article in references:
        matching = by_ref.get((law, article), [])
        if len(matching) != 1:
            outcomes.append(dict(law=law, article=article, status='missing_or_ambiguous_source'))
            continue
        row = matching[0]
        metadata = row['metadata'] or {}
        text_proof = metadata.get('mbs_text_verification') or {}
        url = text_proof.get('url')
        if (text_proof.get('verified') is not True or text_proof.get('article_hash') != row['content_hash']
                or not re.fullmatch(r'[0-9a-f]{64}', str(text_proof.get('document_text_hash', '')))):
            outcomes.append(dict(law=law, article=article, status='missing_exact_official_text_proof'))
            continue
        if law not in pdfs:
            if law in pdf_errors:
                outcomes.append(dict(law=law, article=article, status='official_pdf_fetch_failed',
                                    error=pdf_errors[law]))
                continue
            try:
                pdfs[law] = _fetch_pdf(url, law)
            except Exception as exc:  # bounded official transport; failure remains closed
                pdf_errors[law] = type(exc).__name__
                outcomes.append(dict(law=law, article=article, status='official_pdf_fetch_failed', error=type(exc).__name__))
                continue
        document, full_text, captions = pdfs[law]
        if content_hash(full_text) != text_proof['document_text_hash']:
            outcomes.append(dict(law=law, article=article, status='official_pdf_snapshot_changed'))
            continue
        article_text = extract_article_text(full_text, article)
        if not article_text or content_hash(article_text) != row['content_hash'] or article_text != row['raw_text']:
            outcomes.append(dict(law=law, article=article, status='stored_text_not_exact_pdf_extract'))
            continue
        next_article = _next_heading(full_text, article)
        candidates = [item for item in captions if item.article_no == next_article]
        suffixes = {exact_suffix_for_caption(row['raw_text'], item.caption) for item in candidates}
        suffixes.discard(None)
        if not suffixes or not next_article:
            outcomes.append(dict(law=law, article=article, status='no_unique_bold_suffix_match'))
            continue
        # Several contiguous bold levels can all match the same literal tail.
        # Use the full proven heading block, never just its last subheading.
        caption = max(suffixes, key=lambda value: len(''.join(value.split())))
        if not all(''.join(caption.split()).endswith(''.join(value.split())) for value in suffixes):
            outcomes.append(dict(law=law, article=article, status='no_unique_bold_suffix_match'))
            continue
        context = _context(row, article)
        restored = complete_provision(context, row['raw_text'], following_title=caption)
        if not restored or _usable(restored, 16000) is None:
            outcomes.append(dict(law=law, article=article, status='existing_rule_completeness_gate_rejected'))
            continue
        proof = dict(verified=True, method=_METHOD, url=document.url, article_no=article,
                     following_article_no=next_article, caption=caption, article_hash=row['content_hash'],
                     document_text_hash=text_proof['document_text_hash'])
        outcomes.append(dict(law=law, article=article, status='repairable', source_id=str(row['id']),
                             content_hash=row['content_hash'], original_metadata=metadata, proof=proof))
    public = [{k: v for k, v in item.items() if k not in ('original_metadata', 'proof')}
              | ({'caption': item['proof']['caption'], 'following_article': item['proof']['following_article_no']}
                 if item['status'] == 'repairable' else {}) for item in outcomes]
    digest = hashlib.sha256(json.dumps(public, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    return outcomes, digest


def apply(connection, outcomes, expected_digest, actual_digest):
    if not expected_digest or expected_digest != actual_digest:
        raise ValueError('Preview digest mismatch; no metadata written')
    updates = [item for item in outcomes if item['status'] == 'repairable']
    if not updates:
        return 0, None
    backup_dir = ROOT / '.local' / 'corpus-repair-backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / ('pdf-layout-proof-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    backup.write_text(json.dumps([dict(source_id=item['source_id'], content_hash=item['content_hash'],
        previous_metadata=item['original_metadata']) for item in updates], ensure_ascii=False, indent=2), encoding='utf-8')
    with connection.transaction():
        connection.execute("SET LOCAL lock_timeout = '2s'")
        connection.execute("SET LOCAL statement_timeout = '15s'")
        for item in updates:
            result = connection.execute("""
                UPDATE legal_sources SET metadata = metadata || jsonb_build_object('mbs_pdf_layout', %s::jsonb)
                WHERE id=%s AND content_hash=%s AND is_current AND deleted_at IS NULL
                  AND metadata = %s::jsonb
                RETURNING id
            """, (Jsonb(item['proof']), item['source_id'], item['content_hash'], Jsonb(item['original_metadata']))).fetchone()
            if not result:
                raise RuntimeError('Concurrent source metadata/content change; transaction rolled back')
    return len(updates), str(backup)


def main():
    args = sys.argv[1:]
    apply_requested = '--apply' in args
    expected = args[args.index('--expect-digest') + 1] if '--expect-digest' in args else None
    with (admin_database_connection() if apply_requested else database_connection()) as db:
        if not apply_requested:
            db.execute('SET TRANSACTION READ ONLY')
        outcomes, digest = preview(db)
        print(json.dumps(dict(scope='configured official statute hints; exact verified PDF/layout only',
            apply=apply_requested, digest=digest, counts=dict(Counter(x['status'] for x in outcomes)),
            results=[{k: v for k, v in item.items() if k not in ('original_metadata', 'proof')}
                     | ({'caption': item['proof']['caption'], 'following_article': item['proof']['following_article_no']}
                        if item['status'] == 'repairable' else {}) for item in outcomes]), ensure_ascii=False), flush=True)
        if apply_requested:
            changed, backup = apply(db, outcomes, expected, digest)
            print(json.dumps(dict(metadata_only_updates=changed, backup=backup), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
