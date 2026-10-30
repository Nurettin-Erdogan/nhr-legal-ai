"""Read-only comparison with one official PDF per law. Never promotes records.

Exact identity/text checks, no similarity-threshold verification. A difference
may reflect formatting, version dates or parsing, not necessarily false law.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import database_connection
from ingestion.mevzuat.identity import article_headings, canonical_article
from ingestion.mevzuat.text_verify import fetch_official_pdf_text, _comparison_key


def classify(stored, official):
    if not official:
        return 'official_heading_absent'
    if ''.join(stored.split()) == ''.join(official.split()):
        return 'exact_ignoring_whitespace'
    if _comparison_key(stored) == _comparison_key(official):
        return 'formatting_only_candidate'
    return 'text_difference_requires_review'


def audit_law(law, inspect=False):
    started = monotonic()
    with database_connection() as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        rows = connection.execute("""SELECT s.id,s.raw_text,s.source_version,s.ingest_status,
            d.article_no FROM legal_sources s JOIN legislation_details d ON d.legal_source_id=s.id
            WHERE s.source_type='legislation' AND s.deleted_at IS NULL AND s.is_current
              AND d.legislation_type='law' AND d.law_no=%s ORDER BY d.article_no""", (law,)).fetchall()
    full = fetch_official_pdf_text('https://www.mevzuat.gov.tr/MevzuatMetin/1.5.' + law + '.pdf', timeout_seconds=15)
    headings = article_headings(full)
    bodies, occurrences = {}, Counter(h.identity for h in headings)
    for position, heading in enumerate(headings):
        end = headings[position+1].start if position+1 < len(headings) else len(full)
        bodies.setdefault(heading.identity, full[heading.start:end])
    counts, examples = Counter(), defaultdict(list)
    for row in rows:
        article = canonical_article(row['article_no'])
        status = ('ambiguous_official_heading' if occurrences[article] > 1
                  else classify(row['raw_text'] or '', bodies.get(article)))
        counts[status] += 1
        if len(examples[status]) < 12:
            example = dict(id=str(row['id']), article=article, state=row['ingest_status'])
            if inspect and status == 'text_difference_requires_review' and len(examples[status]) < 2:
                from difflib import SequenceMatcher
                left, right = _comparison_key(row['raw_text'] or ''), _comparison_key(bodies.get(article, ''))
                matcher = SequenceMatcher(None, left, right, autojunk=False)
                example['difference_windows'] = [dict(kind=kind, stored=left[max(0,a-25):min(len(left),b+25)],
                    official=right[max(0,c-25):min(len(right),d+25)])
                    for kind,a,b,c,d in matcher.get_opcodes() if kind != 'equal'][:4]
            examples[status].append(example)
    return dict(law=law, records=len(rows), seconds=round(monotonic()-started, 2),
                counts=dict(counts), examples=dict(examples), official_heading_count=len(headings), read_only=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--laws', nargs='+', default=['6325', '6098', '4857', '6361', '4458', '1512'])
    parser.add_argument('--inspect', action='store_true')
    args = parser.parse_args()
    for law in args.laws:
        if not law.isdecimal():
            raise SystemExit('Numeric official law identifier required')
        try:
            print(json.dumps(audit_law(law, args.inspect), ensure_ascii=False), flush=True)
        except Exception as error:
            print(json.dumps(dict(law=law, error_type=type(error).__name__, read_only=True)), flush=True)
