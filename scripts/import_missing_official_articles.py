"""Preview/import the statute articles that the portal tree never listed: GEÇİCİ, EK and "/A" articles of current laws.

The corpus came from a portal article tree that has only plain-numbered articles; every `law` row is plain-numbered (measured
2026-10-31: zero GEÇİCİ, zero EK, five "/A" among 26 705 law articles, while the official PDF of GVK has 131 more, VUK 99, SPK 25).
The official MBS PDF of each law already ships with the corpus (it is the text the existing rows were verified against), so every
missing article is taken from there, exactly as `import_official_article.py` takes one:

  * the law's own PDF URL comes from its already-verified rows (checked against the MBS URL pattern for that law number);
  * an identity is imported only if it occurs EXACTLY ONCE in the PDF and nowhere in the database yet (any version);
  * the article text is the exact extract of the PDF, its first heading must be that identity, no repealed ("Mülga") text;
  * the proof is the same `mbs_text_verification` record the other rows carry (article hash + document hash);
  * nothing existing is changed; each insert is its own transaction; the inserted ids are written to a backup file first.

Default is a read-only preview. Chunks are created by the ordinary ingestion store; their embeddings stay empty for the embedding job.

  python scripts/import_missing_official_articles.py --laws 7036,6769            # preview
  python scripts/import_missing_official_articles.py --laws 7036 --apply         # import
  python scripts/import_missing_official_articles.py --apply                     # every law (long; paced)
"""

import importlib.util
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psycopg.rows import tuple_row  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from api.db import admin_database_connection  # noqa: E402
from ingestion.mevzuat.identity import article_headings, canonical_article, primary_article  # noqa: E402
from ingestion.mevzuat.models import LegislationRecord  # noqa: E402
from ingestion.mevzuat.parser import article_external_id, article_title_line  # noqa: E402
from ingestion.mevzuat.store import upsert_legislation  # noqa: E402
from ingestion.mevzuat.text_verify import extract_article_text, fetch_official_pdf_text  # noqa: E402
from ingestion.text import content_hash  # noqa: E402

spec = importlib.util.spec_from_file_location("refresh_official_law", ROOT / "scripts" / "refresh_official_law.py")
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)

_PAUSE_SECONDS = 2.0
_MIN_CHARS = 40
_MAX_CHARS = 30000
_BACKUPS = ROOT / ".local" / "corpus-repair-backups"


def law_documents(db, only: set[str] | None) -> dict[str, dict]:
    """{law_no: {url, law_name, have}}: one verified official PDF URL per law and every article identity already stored."""
    rows = db.execute("""
        SELECT d.law_no, d.law_name, d.article_no, s.metadata->'mbs_text_verification'->>'url' AS url
        FROM legislation_details d JOIN legal_sources s ON s.id = d.legal_source_id
        WHERE d.legislation_type = 'law' AND d.law_no IS NOT NULL AND s.deleted_at IS NULL
    """).fetchall()
    laws: dict[str, dict] = {}
    for row in rows:
        if only and row['law_no'] not in only:
            continue
        entry = laws.setdefault(row['law_no'], dict(urls=set(), name=row['law_name'], have=set()))
        entry['have'].add(canonical_article(row['article_no'] or ''))
        if row['url'] and refresh.valid_document_url(row['url'], row['law_no']):
            entry['urls'].add(row['url'])
    return {law: dict(url=next(iter(entry['urls'])), name=entry['name'], have=entry['have'])
            for law, entry in laws.items() if len(entry['urls']) == 1}


# A real article heading carries the dash: "Madde 18 – (Değişik: ...)". The amendment/commencement tables printed at the end of the
# official PDF repeat "Madde 18 | 1/1/1981 tarihinden geçerli ..." without it, which made the identity look repeated.
_STRICT_HEADING = re.compile(
    r"(?im)^[ \t]*(?:(EK\s+GEÇİCİ|EK|GEÇİCİ|GECICI)\s+)?MADDE\s+(\d+(?:\s*/\s*[A-ZÇĞİÖŞÜ]|[A-ZÇĞİÖŞÜ])?)[ \t]*[-–—]")


def _unambiguous_repeat(full: str, headings: list, identity: str) -> bool:
    """A repeated identity is still one article when exactly one occurrence is a dashed heading, that occurrence is the first one
    (so `extract_article_text`, which also takes the first, reads the same text), and the heading that ends its text is dashed too."""
    strict_starts = {m.start(): canonical_article(" ".join(filter(None, m.groups()))) for m in _STRICT_HEADING.finditer(full)}
    own = [position for position, name in strict_starts.items() if name == identity]
    occurrences = [heading for heading in headings if heading.identity == identity]
    if len(own) != 1 or not occurrences or occurrences[0].start != own[0]:
        return False
    following = [heading for heading in headings if heading.start > own[0]]
    return bool(following) and following[0].start in strict_starts


def missing_articles(law: str, entry: dict) -> tuple[list[dict], str, Counter]:
    """The articles the official PDF has and the database lacks, each with its exact extracted text; plus why others were skipped."""
    full = fetch_official_pdf_text(entry['url'], timeout_seconds=40)
    headings = article_headings(full)
    identities = Counter(heading.identity for heading in headings)
    skipped: Counter = Counter()
    found = []
    for identity, count in identities.items():
        if identity in entry['have']:
            continue
        if count != 1 and not _unambiguous_repeat(full, headings, identity):
            skipped['identity_repeated_in_pdf'] += 1
            continue
        body = extract_article_text(full, identity)
        if not _MIN_CHARS <= len(body) <= _MAX_CHARS or primary_article(body) != identity:
            skipped['text_not_an_exact_single_article'] += 1
            continue
        if 'mülga' in body[:100].casefold():
            skipped['repealed'] += 1
            continue
        found.append(dict(article=identity, body=body, hash=content_hash(body)))
    return found, content_hash(full), skipped


def insert(db, law: str, entry: dict, article: dict, document_hash: str, now: datetime) -> str | None:
    proof = {'verified': True, 'url': entry['url'], 'article_no': article['article'], 'checked_at': now.isoformat(),
             'article_hash': article['hash'], 'document_text_hash': document_hash,
             'method': 'exact_official_article_extraction'}
    record = LegislationRecord(
        record_type='legislation', legislation_type='law', law_name=entry['name'], law_no=law, article_no=article['article'],
        article_title=None, title=article_title_line(entry['name'], article['article'], None), raw_text=article['body'],
        external_id=article_external_id(law, article['article'], portal_type='KANUN'), content_hash=article['hash'],
        source_url=entry['url'], scraped_at=now,
        metadata={'verified_against_mbs': True, 'mbs_text_verification': proof, 'source': 'official_mbs_pdf',
                  'mevzuat_tur': 'KANUN', 'import': 'missing_official_article_v1'})
    original = db.row_factory
    try:
        db.row_factory = tuple_row  # the ingestion store's documented cursor contract
        with db.transaction():
            source_id = upsert_legislation(db, record).legal_source_id
            db.execute("UPDATE legal_sources SET ingestion_method='official_mbs_pdf_http', ingest_status='ready', "
                       "metadata = metadata || %s, last_verified_at = NOW() WHERE id=%s",
                       (Jsonb({'verified_against_mbs': True, 'mbs_text_verification': proof}), source_id))
    finally:
        db.row_factory = original
    return str(source_id)


def _finished(log: str | None, key: str) -> set[str]:
    """The ids a previous run of this script already finished without an error (`--resume LOG`)."""
    done: set[str] = set()
    if not log:
        return done
    for line in Path(log).read_text(encoding='utf-8', errors='replace').splitlines():
        if line.startswith('{') and f'"{key}"' in line and '"error"' not in line:
            try:
                done.add(str(json.loads(line)[key]))
            except (ValueError, KeyError):
                continue
    return done


def main():
    args = sys.argv[1:]
    apply_requested = '--apply' in args
    only = set(args[args.index('--laws') + 1].split(',')) if '--laws' in args else None
    resume = args[args.index('--resume') + 1] if '--resume' in args else None
    now = datetime.now(timezone.utc)
    _BACKUPS.mkdir(parents=True, exist_ok=True)
    backup = _BACKUPS / ('missing-articles-' + now.strftime('%Y%m%dT%H%M%S') + '.jsonl')
    with admin_database_connection() as db:
        db.execute('SET TRANSACTION READ ONLY')
        db.execute("SET LOCAL statement_timeout = '120s'")
        laws = law_documents(db, only)
    for law in _finished(resume, 'law'):
        laws.pop(law, None)
    print(json.dumps(dict(laws=len(laws), apply=apply_requested, resumed=bool(resume)), ensure_ascii=False), flush=True)
    total = Counter()
    for law in sorted(laws):
        entry = laws[law]
        try:
            found, document_hash, skipped = missing_articles(law, entry)
            line = dict(law=law, name=entry['name'][:40], missing=len(found), skipped=dict(skipped),
                        sample=[a['article'] for a in found[:6]])
            total['missing'] += len(found)
            if apply_requested and found:
                # A fresh connection per law: a connection that something else terminated must not poison every later law.
                with admin_database_connection() as db:
                    db.execute("SET LOCAL statement_timeout = '120s'")
                    for article in found:
                        source_id = insert(db, law, entry, article, document_hash, now)
                        with backup.open('a', encoding='utf-8') as file:
                            file.write(json.dumps(dict(law=law, article=article['article'], source_id=source_id,
                                                       content_hash=article['hash']), ensure_ascii=False) + chr(10))
                line['inserted'] = len(found)
                total['inserted'] += len(found)
            print(json.dumps(line, ensure_ascii=False), flush=True)
        except Exception as exc:  # one law failing must not stop the others; its own inserts are separate transactions
            print(json.dumps(dict(law=law, error=type(exc).__name__, detail=str(exc)[:160]), ensure_ascii=False), flush=True)
        time.sleep(_PAUSE_SECONDS)
    print(json.dumps(dict(total=dict(total), backup=str(backup) if apply_requested else None), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
