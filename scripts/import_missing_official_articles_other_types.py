"""Preview/import GEÇİCİ / EK / "/A" articles of KHK, regulations and other non-law documents from their official MBS PDF.

Same rules as `import_missing_official_articles.py` (exact official PDF extract, first heading is the identity, no repealed text,
nothing existing changed, each insert its own transaction, backup of inserted ids, read-only preview by default), with one change in
how the document is found: a law's PDF address has a fixed shape, other types do not, so the address is never guessed. The portal
search is asked for the document's own number AND type AND series (all three read from the document's stored portal link), exactly
one hit must come back, and its detail page must offer exactly one PDF. The PDF's first page must carry the stored title. Anything
else (no PDF, several PDFs, no unique hit, another title) is skipped.

Communiqués (tebliğ) are left out by default: most are offered as a Word copy only.

  python scripts/import_missing_official_articles_other_types.py --types decree            # preview
  python scripts/import_missing_official_articles_other_types.py --types decree --apply    # import
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
from ingestion.mevzuat.identity import canonical_article  # noqa: E402
from ingestion.mevzuat.models import LegislationRecord  # noqa: E402
from ingestion.mevzuat.parser import article_external_id, article_title_line  # noqa: E402
from ingestion.mevzuat.store import upsert_legislation  # noqa: E402
from ingestion.mevzuat_bilgi_sistemi import portal as mbs  # noqa: E402

spec = importlib.util.spec_from_file_location("import_missing", ROOT / "scripts" / "import_missing_official_articles.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

_LINK = re.compile(r"MevzuatNo=(\d+)&MevzuatTur=(\d+)&MevzuatTertip=(\d+)", re.I)
_PAUSE_SECONDS = 2.5
_BACKUPS = ROOT / ".local" / "corpus-repair-backups"


def documents(db, types: set[str], only: set[str] | None) -> dict[tuple, dict]:
    """{(type, number, portal type, series): {name, portal_kind, have}} of the stored non-law documents."""
    rows = db.execute("""
        SELECT d.legislation_type, d.law_name, d.article_no, s.source_url, s.metadata->>'mevzuat_tur' AS kind
        FROM legislation_details d JOIN legal_sources s ON s.id = d.legal_source_id
        WHERE d.legislation_type = ANY(%s) AND d.law_no IS NOT NULL AND s.deleted_at IS NULL AND s.source_url IS NOT NULL
    """, (sorted(types),)).fetchall()
    found: dict[tuple, dict] = {}
    for row in rows:
        link = _LINK.search(row['source_url'] or '')
        if not link:
            continue
        number, tur, tertip = link.groups()
        if only and number not in only:
            continue
        key = (row['legislation_type'], number, tur, tertip)
        entry = found.setdefault(key, dict(name=row['law_name'], kind=row['kind'], have=set()))
        entry['have'].add(canonical_article(row['article_no'] or ''))
    return found


def observed_pdf(client, number: str, tur: str, tertip: str) -> str | None:
    """The one official PDF the portal offers for exactly this number + type + series, else None."""
    import base64
    body = {"draw": 1, "start": 0, "length": 25, "parameters": {
        "AranacakIfade": base64.b64encode(number.encode()).decode(), "AranacakYer": "Baslik", "TamCumle": False,
        "MevzuatTur": 0, "GenelArama": True}}
    payload = json.loads(client._request(mbs.urljoin(client.base_url, mbs.SEARCH_PATH), body=body).decode("utf-8-sig"))
    exact = [item for item in payload.get("data", []) if isinstance(item, dict)
             and str(item.get("mevzuatNo") or "").strip() == number
             and str(item.get("mevzuatTur") or "") == tur and str(item.get("mevzuatTertip") or "") == tertip]
    if len(exact) != 1:
        return None
    detail = mbs._official_url(exact[0].get("url"), base_url=client.base_url, expected_path="/mevzuat")
    path = mbs.urlparse(detail).path.casefold()
    if path.startswith("/mevzuatmetin/"):
        return detail if path.endswith(".pdf") else None
    parser = mbs._DocumentLinkParser()
    parser.feed(client._request(detail).decode("utf-8", errors="replace"))
    pdfs = list(dict.fromkeys(
        mbs._official_url(link, base_url=client.base_url, expected_path="/MevzuatMetin/")
        for link in parser.links if mbs.urlparse(mbs.urljoin(client.base_url, link)).path.casefold().endswith(".pdf")))
    return pdfs[0] if len(pdfs) == 1 else None


def insert(db, key, entry, url, article, document_hash, now) -> str:
    legislation_type, number, _tur, _tertip = key
    proof = {'verified': True, 'url': url, 'article_no': article['article'], 'checked_at': now.isoformat(),
             'article_hash': article['hash'], 'document_text_hash': document_hash, 'method': 'exact_official_article_extraction'}
    record = LegislationRecord(
        record_type='legislation', legislation_type=legislation_type, law_name=entry['name'], law_no=number,
        article_no=article['article'], article_title=None, title=article_title_line(entry['name'], article['article'], None),
        raw_text=article['body'], external_id=article_external_id(number, article['article'], portal_type=entry['kind']),
        content_hash=article['hash'], source_url=url, scraped_at=now,
        metadata={'verified_against_mbs': True, 'mbs_text_verification': proof, 'source': 'official_mbs_pdf',
                  'mevzuat_tur': entry['kind'], 'import': 'missing_official_article_v1'})
    original = db.row_factory
    try:
        db.row_factory = tuple_row
        with db.transaction():
            source_id = upsert_legislation(db, record).legal_source_id
            db.execute("UPDATE legal_sources SET ingestion_method='official_mbs_pdf_http', ingest_status='ready', "
                       "metadata = metadata || %s, last_verified_at = NOW() WHERE id=%s",
                       (Jsonb({'verified_against_mbs': True, 'mbs_text_verification': proof}), source_id))
    finally:
        db.row_factory = original
    return str(source_id)


def main():
    args = sys.argv[1:]
    apply_requested = '--apply' in args
    types = set(args[args.index('--types') + 1].split(',')) if '--types' in args else {'decree', 'regulation', 'other'}
    only = set(args[args.index('--laws') + 1].split(',')) if '--laws' in args else None
    resume = args[args.index('--resume') + 1] if '--resume' in args else None
    now = datetime.now(timezone.utc)
    _BACKUPS.mkdir(parents=True, exist_ok=True)
    backup = _BACKUPS / ('missing-articles-other-' + now.strftime('%Y%m%dT%H%M%S') + '.jsonl')
    client = mbs.MbsClient(timeout_seconds=30, max_retries=1)
    total: Counter = Counter()
    with admin_database_connection() as db:
        db.execute('SET TRANSACTION READ ONLY')
        db.execute("SET LOCAL statement_timeout = '120s'")
        docs = documents(db, types, only)
    for done in base._finished(resume, 'doc'):
        docs = {key: value for key, value in docs.items() if '/'.join(key) != done}
    print(json.dumps(dict(documents=len(docs), types=sorted(types), apply=apply_requested, resumed=bool(resume)),
                     ensure_ascii=False), flush=True)
    for key in sorted(docs):
        entry = docs[key]
        line = dict(doc='/'.join(key))
        try:
            url = observed_pdf(client, key[1], key[2], key[3])
            if url is None:
                line['skipped'] = 'no_unique_official_pdf'
                total['no_unique_official_pdf'] += 1
            else:
                entry['url'] = url
                full_head = base.fetch_official_pdf_text(url, timeout_seconds=40)[:4000]
                if mbs._title_key(entry['name'])[:60] not in mbs._title_key(full_head):
                    line['skipped'] = 'title_not_in_pdf'
                    total['title_not_in_pdf'] += 1
                else:
                    found, document_hash, skipped = base.missing_articles(key[1], entry)
                    line.update(missing=len(found), skipped_articles=dict(skipped), sample=[a['article'] for a in found[:6]])
                    total['missing'] += len(found)
                    if apply_requested and found:
                        with admin_database_connection() as db:  # fresh connection per document
                            db.execute("SET LOCAL statement_timeout = '120s'")
                            for article in found:
                                source_id = insert(db, key, entry, url, article, document_hash, now)
                                with backup.open('a', encoding='utf-8') as file:
                                    file.write(json.dumps(dict(doc='/'.join(key), article=article['article'], source_id=source_id,
                                                               content_hash=article['hash']), ensure_ascii=False) + chr(10))
                        line['inserted'] = len(found)
                        total['inserted'] += len(found)
        except Exception as exc:  # one document failing must not stop the others
            line['error'] = type(exc).__name__ + ': ' + str(exc)[:120]
        print(json.dumps(line, ensure_ascii=False), flush=True)
        time.sleep(_PAUSE_SECONDS)
    print(json.dumps(dict(total=dict(total), backup=str(backup) if apply_requested else None), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
