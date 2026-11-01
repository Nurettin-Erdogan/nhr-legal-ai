"""Preview/import the portal documents the corpus does not have at all (regulations, CB decisions, communiqués, ...), from their official PDF.

The portal (MBS) lists 19 162 documents; the corpus holds about 4 800 (measured 2026-11-01). Everything it lacks and that has an
official PDF with real "MADDE" articles is imported here with the same rules as the other official-PDF importers:

  * the document list comes from the portal itself; a document is "known" when its (number, type, series) -- read from the stored
    portal link -- is already in the corpus, and a document whose number already exists for the same stored type is never added twice;
  * the PDF address is OBSERVED (the list entry, or the detail page with exactly one PDF), never guessed; the PDF's first page must
    carry the document's title; repealed collections ("... YÜRÜRLÜKTEN KALDIRILMIŞ HÜKÜMLERİ") are not in force and are skipped;
  * every article is the exact PDF extract (identity occurs exactly once, or is the unambiguous dashed heading), repealed text is left out;
  * the proof is the usual `mbs_text_verification` record (article hash + document hash); one transaction per article; backup of ids;
  * Word-only documents (most communiqués) and documents without "MADDE" headings (circulars) are skipped and counted, not guessed.

Default is a read-only preview. Chunks are created by the ordinary ingestion store; their embeddings stay empty for the embedding job.

  python scripts/import_new_documents_from_portal.py --tur 3,7,20 --limit 20           # preview of 20 documents
  python scripts/import_new_documents_from_portal.py --tur 3,7,20 --apply               # import
  python scripts/import_new_documents_from_portal.py --tur 3 --apply --resume LOG       # continue after an interruption
"""

import base64
import importlib.util
import json
import re
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psycopg.rows import tuple_row  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from api.db import admin_database_connection  # noqa: E402
from ingestion.mevzuat.identity import article_headings, canonical_article, primary_article  # noqa: E402
from ingestion.mevzuat.models import LegislationRecord  # noqa: E402
from ingestion.mevzuat.parser import article_external_id, article_title_line, map_legislation_type  # noqa: E402
from ingestion.mevzuat.store import upsert_legislation  # noqa: E402
from ingestion.mevzuat.text_verify import extract_article_text, fetch_official_pdf_text  # noqa: E402
from ingestion.mevzuat_bilgi_sistemi import portal as mbs  # noqa: E402
from ingestion.text import content_hash  # noqa: E402

spec = importlib.util.spec_from_file_location("import_missing", ROOT / "scripts" / "import_missing_official_articles.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

_KIND = {1: 'KANUN', 2: 'TUZUK', 3: 'YONETMELIK', 4: 'KHK', 7: 'KKY', 8: 'UY', 9: 'TEBLIGLER', 19: 'CB_KARARNAME', 20: 'CB_KARAR',
         21: 'CB_YONETMELIK'}
_PAUSE_SECONDS = 2.5
_BACKUPS = ROOT / ".local" / "corpus-repair-backups"
_LINK = re.compile(r"MevzuatNo=(\d+)&MevzuatTur=(\d+)&MevzuatTertip=(\d+)", re.I)
_PDF_NAME = re.compile(r"MevzuatMetin/(\d+)\.(\d+)\.(\d+)\.pdf", re.I)
_MIN_CHARS, _MAX_CHARS = 40, 30000


def _date(value) -> date | None:
    try:
        day, month, year = str(value).strip().split('.')
        return date(int(year), int(month), int(day))
    except (ValueError, AttributeError):
        return None


_LIST_CACHE = ROOT / ".local" / "mbs_lists"
_LIST_CACHE_HOURS = 12


def listing(client, tur: int) -> list[dict]:
    """The portal's list of one type, cached on disk for 12 hours: many workers asking the portal for the same list at the same
    moment made it answer with empty bodies and stopped them (measured 2026-11-01), so the list is fetched once and shared."""
    cache = _LIST_CACHE / f"tur_{tur}.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < _LIST_CACHE_HOURS * 3600:
        try:
            return json.loads(cache.read_text(encoding='utf-8'))
        except ValueError:
            pass
    items, start = [], 0
    while True:
        body = {"draw": 1, "start": start, "length": 100, "parameters": {
            "AranacakIfade": base64.b64encode(b'').decode(), "AranacakYer": "Baslik", "TamCumle": False,
            "MevzuatTur": tur, "GenelArama": True}}
        for attempt in range(8):  # the portal now and then answers with an empty body: wait and ask again, never guess
            try:
                page = json.loads(client._request(mbs.urljoin(client.base_url, mbs.SEARCH_PATH), body=body).decode('utf-8-sig'))
                break
            except (ValueError, mbs.MbsError):
                if attempt == 7:
                    raise
                time.sleep(20 * (attempt + 1))
        items.extend(page['data'])
        start += 100
        if start >= page['recordsTotal'] or not page['data']:
            _LIST_CACHE.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(items, ensure_ascii=False), encoding='utf-8')
            return items
        time.sleep(1.5)


def key_of(item: dict) -> tuple[str, int, str] | None:
    """(number, type, series) of a list entry, from its own link."""
    url = str(item.get('url') or '')
    match = _LINK.search(url)
    if match:
        return match.group(1), int(match.group(2)), match.group(3)
    match = _PDF_NAME.search(url)
    if match:
        return match.group(3), int(match.group(1)), match.group(2)
    return None


def known(db) -> tuple[set[tuple[str, int, str]], set[tuple[str, str]]]:
    """Stored (number, type, series) triples and stored (legislation type, number) pairs."""
    triples, pairs = set(), set()
    for row in db.execute("SELECT DISTINCT d.legislation_type AS t, d.law_no, s.source_url FROM legislation_details d "
                          "JOIN legal_sources s ON s.id = d.legal_source_id WHERE s.deleted_at IS NULL AND d.law_no IS NOT NULL").fetchall():
        pairs.add((row['t'], row['law_no']))
        url = row['source_url'] or ''
        match = _LINK.search(url)
        if match:
            triples.add((match.group(1), int(match.group(2)), match.group(3)))
        else:
            match = _PDF_NAME.search(url)
            if match:
                triples.add((match.group(3), int(match.group(1)), match.group(2)))
    return triples, pairs


def official_pdf(client, item: dict) -> tuple[str | None, str | None, str]:
    """(document address, detail address, kind 'pdf' | 'docx') the portal itself offers for this entry.

    One PDF wins; with no PDF, one .docx (the portal lists a .doc and a .docx copy of the same text) is used. Anything else
    returns (None, reason, '')."""
    url = str(item.get('url') or '')
    if url.startswith('http'):
        path = mbs.urlparse(url).path.casefold()
        if path.startswith('/mevzuatmetin/') and path.endswith('.pdf'):
            return url, url, 'pdf'
        return None, 'direct_link_is_not_an_official_pdf', ''
    detail = mbs._official_url(url, base_url=client.base_url, expected_path='/mevzuat')
    parser = mbs._DocumentLinkParser()
    parser.feed(client._request(detail).decode('utf-8', errors='replace'))

    def links(*suffixes: str) -> list[str]:
        return list(dict.fromkeys(mbs._official_url(link, base_url=client.base_url, expected_path='/MevzuatMetin/')
                                  for link in parser.links
                                  if mbs.urlparse(mbs.urljoin(client.base_url, link)).path.casefold().endswith(suffixes)))

    pdfs, docx, old_doc = links('.pdf'), links('.docx'), links('.doc')
    if len(pdfs) == 1:
        return pdfs[0], detail, 'pdf'
    if not pdfs and len(docx) == 1:
        return docx[0], detail, 'docx'
    if not pdfs and not docx and len(old_doc) == 1:
        return old_doc[0], detail, 'doc'
    return None, 'no_unique_document', ''


def _antiword_text(payload: bytes) -> str:
    """Text of a binary .doc through the antiword program (Turkish mapping, no hard wrapping); refused when it is not installed."""
    import shutil
    import subprocess
    import tempfile
    program = shutil.which('antiword')
    if program is None:
        raise ValueError('binary_word_document')
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'official.doc'
        path.write_bytes(payload)
        result = subprocess.run([program, '-m', 'UTF-8.txt', '-w', '0', str(path)], capture_output=True, timeout=60)
    if result.returncode != 0 or not result.stdout.strip():
        raise ValueError('binary_word_document')
    from ingestion.text import normalize_text
    return normalize_text(result.stdout.decode('utf-8', errors='replace'))


def fetch_official_word_text(url: str, kind: str) -> str:
    """Text of the portal's own Word copy (/MevzuatMetin/ only, bounded size).

    `.docx`: paragraphs in document order. `.doc`: the portal serves these as a saved web page (UTF-16 HTML), whose hard-wrapped
    source lines are joined before the tags are turned into paragraphs; a real binary Word file is refused, not guessed at."""
    import io
    import re as _re
    from urllib.request import Request, build_opener

    parsed = mbs.urlparse(url)
    if (parsed.scheme != 'https' or parsed.hostname not in {'mevzuat.gov.tr', 'www.mevzuat.gov.tr'}
            or not parsed.path.casefold().startswith('/mevzuatmetin/') or not parsed.path.casefold().endswith(('.docx', '.doc'))):
        raise ValueError('not an official Word address')
    request = Request(url, headers={'Referer': 'https://www.mevzuat.gov.tr/', 'User-Agent': 'nhr-legal-ai/0.1 (official-text)'})
    with build_opener().open(request, timeout=60) as response:
        payload = response.read(15 * 1024 * 1024 + 1)
    if len(payload) > 15 * 1024 * 1024:
        raise ValueError('official Word file too large')
    if kind == 'docx':
        if not payload.startswith(b'PK'):
            raise ValueError('official .docx is not a .docx')
        from docx import Document
        return chr(10).join(p.text for p in Document(io.BytesIO(payload)).paragraphs if p.text.strip())
    if payload.startswith(bytes.fromhex('d0cf11e0')):
        return _antiword_text(payload)  # a real binary Word file: read by antiword, unwrapped to one line per paragraph
    if payload.startswith(b'{' + bytes([92]) + b'rtf'):
        raise ValueError('binary_word_document')
    from ingestion.text import html_to_text, normalize_text
    if payload.startswith((bytes.fromhex('fffe'), bytes.fromhex('feff'))):
        html = payload.decode('utf-16')
    else:
        try:
            html = payload.decode('utf-8')
        except UnicodeDecodeError:
            html = payload.decode('cp1254')
    # the saved web page is hard-wrapped in its source: join those lines so a sentence is not cut into paragraphs
    html = _re.sub(chr(92) + 's*' + chr(13) + '?' + chr(10) + chr(92) + 's*', ' ', html)
    return normalize_text(html_to_text(html))


def articles_of(full: str) -> tuple[list[dict], Counter]:
    headings = article_headings(full)
    identities = Counter(h.identity for h in headings)
    skipped: Counter = Counter()
    found = []
    for identity, count in identities.items():
        if count != 1 and not base._unambiguous_repeat(full, headings, identity):
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
    return found, skipped


def insert_document(db, item: dict, key, pdf_url: str, detail_url: str, articles: list[dict], document_hash: str, now: datetime,
                    backup: Path, method: str = 'exact_official_article_extraction') -> int:
    """Write every article of one document in ONE transaction: a refused or interrupted document leaves nothing behind, and the
    single commit (instead of one per article) is what keeps the import fast on a database busy with embeddings."""
    number, tur, _series = key
    kind = _KIND[tur]
    name = mbs.normalize_text(mbs.html_to_text(str(item.get('mevAdi') or ''))) if hasattr(mbs, 'normalize_text') else str(item.get('mevAdi'))
    legislation_type = map_legislation_type(kind, law_no=number, law_name=name)
    gazette_date, accepted = _date(item.get('resmiGazeteTarihi')), _date(item.get('kabulTarih'))
    gazette_no = str(item.get('resmiGazeteSayisi') or '').strip() or None
    identity = {'accepted': accepted.isoformat() if accepted else None, 'gazette_date': gazette_date.isoformat() if gazette_date else None,
                'gazette_no': gazette_no, 'source': 'mbs_list'}
    written: list[tuple[str, str, str]] = []
    original = db.row_factory
    try:
        db.row_factory = tuple_row
        with db.transaction():
            for article in articles:
                proof = {'verified': True, 'url': pdf_url, 'article_no': article['article'], 'checked_at': now.isoformat(),
                         'article_hash': article['hash'], 'document_text_hash': document_hash, 'method': method}
                record = LegislationRecord(
                    record_type='legislation', legislation_type=legislation_type, law_name=name, law_no=number,
                    article_no=article['article'], article_title=None, title=article_title_line(name, article['article'], None),
                    raw_text=article['body'], external_id=article_external_id(number, article['article'], portal_type=kind),
                    content_hash=article['hash'], source_url=detail_url, official_gazette_no=gazette_no,
                    official_gazette_date=gazette_date, scraped_at=now,
                    metadata={'verified_against_mbs': True, 'mbs_text_verification': proof, 'source': 'official_mbs_pdf',
                              'mevzuat_tur': kind, 'import': 'new_document_v1', 'law_identity': identity})
                source_id = upsert_legislation(db, record).legal_source_id
                db.execute("UPDATE legal_sources SET ingestion_method='official_mbs_pdf_http', ingest_status='ready', "
                           "metadata = metadata || %s, last_verified_at = NOW() WHERE id=%s",
                           (Jsonb({'verified_against_mbs': True, 'mbs_text_verification': proof}), source_id))
                written.append((article['article'], str(source_id), article['hash']))
    finally:
        db.row_factory = original
    with backup.open('a', encoding='utf-8') as file:
        for article_no, source_id, content in written:
            file.write(json.dumps(dict(doc='/'.join(map(str, key)), article=article_no, source_id=source_id, content_hash=content),
                                  ensure_ascii=False) + chr(10))
    return len(written)


def main() -> None:
    args = sys.argv[1:]
    apply_requested = '--apply' in args
    turs = [int(x) for x in args[args.index('--tur') + 1].split(',')] if '--tur' in args else [3, 7, 20]
    limit = int(args[args.index('--limit') + 1]) if '--limit' in args else 0
    resume = args[args.index('--resume') + 1].split(',') if '--resume' in args else []
    shard_index, shard_count = (int(x) for x in args[args.index('--shard') + 1].split('/')) if '--shard' in args else (0, 1)
    now = datetime.now(timezone.utc)
    _BACKUPS.mkdir(parents=True, exist_ok=True)
    backup = _BACKUPS / ('new-documents-' + now.strftime('%Y%m%dT%H%M%S') + '.jsonl')
    client = mbs.MbsClient(timeout_seconds=40, max_retries=2)
    finished: set[str] = set()
    for log in resume:  # logs of earlier runs (and of the other shards): their finished documents are not repeated
        if not Path(log).exists():
            continue
        for line in Path(log).read_text(encoding='utf-8', errors='replace').splitlines():
            # a document skipped only because it was Word-only is tried again now that .docx copies are read
            if line.startswith('{') and '"doc"' in line and '"error"' not in line and '"word_only"' not in line and '"title_not_in_pdf"' not in line:
                try:
                    finished.add(json.loads(line)['doc'])
                except (ValueError, KeyError):
                    continue
    with admin_database_connection() as db:
        db.execute('SET TRANSACTION READ ONLY')
        db.execute("SET LOCAL statement_timeout = '1200s'")  # the stored-document list is large and the database may be busy
        triples, pairs = known(db)
    total: Counter = Counter()
    done = 0
    for tur in turs:
        entries = listing(client, tur)
        todo = []
        for item in entries:
            key = key_of(item)
            if key is None or key[1] != tur or key in triples or 'YÜRÜRLÜKTEN KALDIRILMIŞ' in str(item.get('mevAdi') or '').upper():
                continue
            if '/'.join(map(str, key)) in finished:
                continue
            todo.append((key, item))
        todo = [entry for position, entry in enumerate(sorted(todo, key=lambda e: e[0])) if position % shard_count == shard_index]
        print(json.dumps(dict(tur=tur, shard=f'{shard_index}/{shard_count}', portal=len(entries), to_import_candidates=len(todo), apply=apply_requested)), flush=True)
        for key, item in todo:
            if limit and done >= limit:
                break
            done += 1
            line = dict(doc='/'.join(map(str, key)), name=str(item.get('mevAdi') or '')[:50])
            try:
                legislation_type = map_legislation_type(_KIND[tur], law_no=key[0], law_name=str(item.get('mevAdi') or ''))
                if (legislation_type, key[0]) in pairs:
                    line['skipped'] = 'number_already_stored_for_this_type'
                else:
                    pdf_url, detail, kind = official_pdf(client, item)
                    if pdf_url is None:
                        line['skipped'] = detail
                    else:
                        full = fetch_official_pdf_text(pdf_url, timeout_seconds=60) if kind == 'pdf' else fetch_official_word_text(pdf_url, kind)
                        line['source'] = kind
                        head = mbs._title_key(full[:4000])
                        # An entry whose own list link IS the PDF (Cumhurbaşkanı Kararları) cannot point at another document: the title
                        # is not needed to tell them apart. Every other entry is found through a search or a detail page, so its PDF
                        # must carry the stored title.
                        direct = str(item.get('url') or '').startswith('http')
                        if not direct and mbs._title_key(str(item.get('mevAdi') or ''))[:50] not in head:
                            line['skipped'] = 'title_not_in_pdf'
                        else:
                            articles, skipped = articles_of(full)
                            line.update(articles=len(articles), skipped_articles=dict(skipped))
                            if not articles:
                                line['skipped'] = 'no_articles'
                            elif apply_requested:
                                with admin_database_connection() as db:
                                    db.execute("SET LOCAL statement_timeout = '120s'")
                                    line['inserted'] = insert_document(db, item, key, pdf_url, detail, articles, content_hash(full), now, backup,
                                                                       method='exact_official_article_extraction' if kind == 'pdf'
                                                                       else 'official_word_article_extraction')
                                pairs.add((legislation_type, key[0]))
                if line.get('skipped'):
                    total['skipped_' + str(line['skipped'])] += 1
                else:
                    total['documents'] += 1
                    total['articles'] += line.get('articles', 0)
            except Exception as exc:  # one document failing must not stop the others
                if str(exc) == 'binary_word_document':  # a real binary Word file: not readable here, not an error to retry
                    line['skipped'] = 'binary_word_document'
                    total['skipped_binary_word_document'] += 1
                else:
                    line['error'] = type(exc).__name__ + ': ' + str(exc)[:110]
                    total['errors'] += 1
            print(json.dumps(line, ensure_ascii=False), flush=True)
            time.sleep(_PAUSE_SECONDS)
    print(json.dumps(dict(total=dict(total), backup=str(backup) if apply_requested else None), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
