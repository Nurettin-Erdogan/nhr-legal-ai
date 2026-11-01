"""Read-only: which stored statute articles are older than the law's current official text?

Every article verified against the official PDF carries the hash of that PDF's text (`mbs_text_verification.document_text_hash`).
A law's PDF is fetched again; if its text hash differs from the stored one, the law has been amended since the check, and each stored
article of it is compared with the new text (exact normalised text) to name exactly which ones are out of date. Nothing is written:
the findings go to `.local/law_freshness.jsonl`, and the articles are then refreshed with `scripts/refresh_official_law.py`, which
previews, backs up and writes new revisions.

  python scripts/audit_law_freshness.py [--laws 4857,6098]
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from api.db import admin_database_connection  # noqa: E402
from ingestion.mevzuat.identity import canonical_article  # noqa: E402
from ingestion.mevzuat.text_verify import _comparison_key, extract_article_text, fetch_official_pdf_text  # noqa: E402
from ingestion.text import content_hash  # noqa: E402

_PAUSE_SECONDS = 2.0
_OUT = ROOT / ".local" / "law_freshness.jsonl"


def stored_laws(db, only: set[str] | None) -> dict[str, dict]:
    rows = db.execute("""
        SELECT d.law_no, d.article_no, s.id, s.raw_text, s.metadata->'mbs_text_verification'->>'url' AS url,
               s.metadata->'mbs_text_verification'->>'document_text_hash' AS doc_hash
        FROM legislation_details d JOIN legal_sources s ON s.id = d.legal_source_id
        WHERE d.legislation_type = 'law' AND s.is_current AND s.deleted_at IS NULL AND s.ingest_status = 'ready'
          AND s.metadata->'mbs_text_verification'->>'verified' = 'true' AND d.law_no IS NOT NULL""").fetchall()
    laws: dict[str, dict] = {}
    for row in rows:
        if only and row['law_no'] not in only:
            continue
        entry = laws.setdefault(row['law_no'], dict(urls=set(), hashes=set(), articles=[]))
        if row['url']:
            entry['urls'].add(row['url'])
        if row['doc_hash']:
            entry['hashes'].add(row['doc_hash'])
        entry['articles'].append((canonical_article(row['article_no'] or ''), str(row['id']), row['raw_text'] or ''))
    return laws


def main() -> None:
    only = set(sys.argv[sys.argv.index('--laws') + 1].split(',')) if '--laws' in sys.argv else None
    with admin_database_connection() as db:
        db.execute('SET TRANSACTION READ ONLY')
        db.execute("SET LOCAL statement_timeout = '240s'")
        laws = stored_laws(db, only)
    print(json.dumps(dict(laws=len(laws)), ensure_ascii=False), flush=True)
    done = set()
    if _OUT.exists():
        for line in _OUT.read_text(encoding='utf-8').splitlines():
            try:
                done.add(json.loads(line)['law'])
            except (ValueError, KeyError):
                continue
    for law in sorted(laws):
        if law in done:
            continue
        entry = laws[law]
        line: dict = dict(law=law, articles=len(entry['articles']), checked_at=datetime.now(timezone.utc).isoformat())
        try:
            if len(entry['urls']) != 1:
                line['status'] = 'no_single_official_url'
            else:
                full = fetch_official_pdf_text(next(iter(entry['urls'])), timeout_seconds=60)
                current = content_hash(full)
                if current in entry['hashes'] and len(entry['hashes']) == 1:
                    line['status'] = 'unchanged'
                else:
                    stale = []
                    for article, source_id, text in entry['articles']:
                        # Exact comparison of the normalised texts. (`verify_article_text` refuses every article whose key is
                        # shorter than 200 characters, identical or not: measured 2026-11-01 on 2872 m.1, a false alarm.)
                        official = extract_article_text(full, article)
                        if not official or _comparison_key(official) != _comparison_key(text):
                            stale.append(article)
                    line.update(status='amended_since_check' if stale else 'pdf_changed_articles_equal',
                                stored_hashes=len(entry['hashes']), stale_articles=stale[:60], stale_count=len(stale))
        except Exception as exc:  # one law failing must not stop the audit
            line.update(status='error', error=type(exc).__name__, detail=str(exc)[:120])
        with _OUT.open('a', encoding='utf-8') as file:
            file.write(json.dumps(line, ensure_ascii=False) + chr(10))
        print(json.dumps({k: line[k] for k in ('law', 'status', 'articles', 'stale_count') if k in line}), flush=True)
        time.sleep(_PAUSE_SECONDS)


if __name__ == '__main__':
    main()
