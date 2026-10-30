"""Public-only official research, exact document ingestion, then normal RAG.

No raw user question is sent to a website: outbound searches contain numeric
statute references or phrases from a fixed legal vocabulary. Search snippets
are never evidence. Unsupported institutions are not marked searched.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import os
import re
import threading
from time import monotonic, sleep

from api.ai.official_sources import require_official_url
from api.ai.official_transport import OfficialOpener
from api.ai.rag import RAGContext
from api.ai.search_plan import normalize

# Routing vocabulary, NOT legal answers. Values, not substrings of the input,
# leave the machine. Names, amounts, addresses and case facts cannot leak.
_TOPICS = (
    (('muris muvazaa', 'muris muvazaası'), 'muris muvazaası'),
    (('kira', 'kiracı'), 'kira'),
    (('kıdem',), 'kıdem tazminatı'),
    (('ihbar',), 'ihbar tazminatı'),
    (('işe iade', 'işten çıkar', 'işveren'), 'işe iade'),
    (('icra', 'borç', 'borc', 'alacak'), 'itirazın iptali'),
    (('nafaka',), 'nafaka'), (('velayet',), 'velayet'),
    (('mal paylaş', 'mal rejimi'), 'mal rejimi'),
    (('boşan',), 'boşanma'), (('miras',), 'miras'),
    (('tapu',), 'tapu iptali'), (('tüketici', 'ayıplı'), 'ayıplı mal'),
    (('fazla mesai', 'fazla çalışma'), 'fazla çalışma'),
    (('yıllık izin',), 'yıllık izin ücreti'),
)
_LOCK = threading.Lock()
_LAST_REQUEST = 0.0
_CACHE_LOCK = threading.RLock()
_LAW_CACHE = {}
_COURT_CACHE = {}


def _cached(cache, key, fetch, *, ttl):
    # Public documents/IDs only. Single flight prevents simultaneous chats
    # repeating the same portal search. Failures cool down for one minute.
    with _CACHE_LOCK:
        entry = cache.get(key)
        if entry and entry[0] > monotonic():
            if not entry[1]:
                raise ValueError('Official source is cooling down after a failed request')
            return entry[2]
        try:
            result = fetch(key)
        except Exception:
            cache[key] = (monotonic() + 60, False, None)
            raise
        if len(cache) >= 16:
            cache.pop(next(iter(cache)))
        cache[key] = (monotonic() + ttl, True, result)
        return result


@dataclass(frozen=True)
class ResearchResult:
    contexts: tuple[RAGContext, ...] = ()
    statuses: tuple[dict, ...] = ()


def safe_topics(text):
    value = normalize(text)
    return tuple(dict.fromkeys(phrase for words, phrase in _TOPICS
                              if any(normalize(word) in value for word in words)))[:2]


def statute_references(queries, contexts):
    from api.ai.retrieval import question_article_numbers, question_law_numbers
    references = []
    for query in queries:
        laws = question_law_numbers(query)
        articles = question_article_numbers(query)
        if len(laws) == 1 and len(articles) == 1:
            references.append((laws[0], articles[0]))
    references.extend((c.law_no, c.article_no) for c in contexts if c.source_type == 'legislation')
    return tuple(dict.fromkeys((law, article) for law, article in references
        if isinstance(law, str) and re.fullmatch(r'\d{1,5}', law)
        and isinstance(article, str) and re.fullmatch(r'\d{1,3}(?:/[A-Za-z])?', article)))[:6]


class _PacedOpener(OfficialOpener):
    def open(self, request, timeout=30):
        global _LAST_REQUEST
        # A single public client across simultaneous conversations. No retry,
        # proxy, CAPTCHA bypass or parallel portal fan-out.
        with _LOCK:
            remaining = 4.5 - (monotonic() - _LAST_REQUEST)
            if remaining > 0:
                sleep(remaining)
            try:
                return super().open(request, timeout)
            finally:
                _LAST_REQUEST = monotonic()


def _load_contexts(source_ids):
    from api.db import database_connection
    from api.ai.retrieval import _SELECT_COLUMNS, _DETAIL_JOINS
    from api.legal import _VERIFIED_SOURCE_FILTER
    if not source_ids:
        return []
    with database_connection() as db:
        rows = db.execute(f'''SELECT {_SELECT_COLUMNS}, 1.0::float AS rank
            FROM legal_chunks chunk JOIN legal_sources ls ON ls.id=chunk.legal_source_id
            {_DETAIL_JOINS}
            WHERE ls.id=ANY(%s) AND ls.is_current AND ls.deleted_at IS NULL
              AND {_VERIFIED_SOURCE_FILTER}
            ORDER BY ls.id, chunk.chunk_index LIMIT 48''', (list(source_ids),)).fetchall()
    return [RAGContext(**row) for row in rows]


def _pdf_text(document):
    from pypdf import PdfReader
    from ingestion.text import normalize_text
    if document.content_type != 'application/pdf' or not document.body.startswith(b'%PDF'):
        raise ValueError('Official law is not a PDF')
    reader = PdfReader(BytesIO(document.body))
    if reader.is_encrypted or len(reader.pages) > 1500:
        raise ValueError('Unsupported official PDF')
    pages, total = [], 0
    for page in reader.pages:
        text = page.extract_text() or ''
        total += len(text)
        if total > 8_000_000:
            raise ValueError('Official text exceeds extraction limit')
        pages.append(text)
    return normalize_text('\n'.join(pages))


def validate_law_document(document, full):
    from ingestion.mevzuat.text_verify import _comparison_key
    from urllib.parse import urlsplit
    require_official_url(document.pdf_url)
    parsed = urlsplit(document.pdf_url)
    path = parsed.path
    if (document.legislation_type != 1 or not document.law_name
            or parsed.hostname not in {'www.mevzuat.gov.tr', 'mevzuat.gov.tr'}
            or parsed.query or parsed.fragment
            or not re.fullmatch(r'/MevzuatMetin/1\.\d+\.' + re.escape(document.law_no) + r'\.pdf', path, re.I)
            or _comparison_key(document.law_name) not in _comparison_key(full[:3000])
            or not re.search(r'Kanun\s+Numarası\s*:\s*' + re.escape(document.law_no) + r'\b', full[:3000], re.I)):
        raise ValueError('Official law identity mismatch')


def _fetch_law(law):
    from ingestion.mevzuat_bilgi_sistemi.portal import MbsClient
    from urllib.request import Request
    document = MbsClient(timeout_seconds=30, max_retries=1, opener=_PacedOpener()).search_law(law)
    if not document.pdf_url:
        raise ValueError('No observed official PDF')
    # Use the same public pacing and pinned TLS transport as the search request.
    payload = _PacedOpener().open(Request(document.pdf_url)).read()
    from api.ai.official_transport import PublicDocument
    full = _pdf_text(PublicDocument(document.pdf_url, 'application/pdf', payload, (document.pdf_url,)))
    validate_law_document(document, full)
    return document, full


def extract_article(full, article):
    """The exact text of one article from a validated official law document; raises when absent, ambiguous or incomplete."""
    from ingestion.mevzuat.identity import article_headings, canonical_article, primary_article
    from ingestion.text import normalize_text
    headings = article_headings(full)
    matches = [i for i, h in enumerate(headings) if h.identity == canonical_article(article)]
    if len(matches) != 1:
        raise ValueError('Official article absent or ambiguous')
    index = matches[0]
    end = headings[index + 1].start if index + 1 < len(headings) else len(full)
    body = normalize_text(full[headings[index].start:end])
    if not 40 <= len(body) <= 100000 or primary_article(body) != canonical_article(article):
        raise ValueError('Incomplete official article')
    return body


def fetch_law_cached(law):
    return _cached(_LAW_CACHE, law, _fetch_law, ttl=900)


def _store_article(document, full, article):
    from api.db import admin_database_connection
    from ingestion.mevzuat.models import LegislationRecord
    from ingestion.mevzuat.store import upsert_legislation
    from ingestion.text import content_hash
    from psycopg.rows import tuple_row
    body = extract_article(full, article)
    now = datetime.now(timezone.utc)
    proof = dict(verified=True, url=document.pdf_url, checked_at=now.isoformat(),
                 article_no=article, article_hash=content_hash(body),
                 document_text_hash=content_hash(full), method='exact_official_article_extraction')
    with admin_database_connection() as db:
        db.execute("SET LOCAL lock_timeout='2s'")
        db.execute("SET LOCAL statement_timeout='30s'")
        # Never overwrite a differing current source from an interactive chat.
        # Corpus repair/version review remains a separate, backed-up operation.
        existing = db.execute('''SELECT ls.id, ls.content_hash FROM legal_sources ls
            JOIN legislation_details d ON d.legal_source_id=ls.id
            WHERE ls.is_current AND ls.deleted_at IS NULL AND d.legislation_type='law'
              AND d.law_no=%s AND d.article_no=%s''', (document.law_no, article)).fetchall()
        if existing:
            if len(existing) != 1 or existing[0]['content_hash'] != content_hash(body):
                raise ValueError('Current article differs; separate version review required')
            return existing[0]['id']
        # Serialize concurrent chat imports; recheck under the lock.
        db.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('web-law:' + document.law_no,))
        if db.execute('''SELECT 1 FROM legislation_details d JOIN legal_sources ls ON ls.id=d.legal_source_id
            WHERE ls.is_current AND ls.deleted_at IS NULL AND d.legislation_type='law'
              AND d.law_no=%s AND d.article_no=%s''', (document.law_no, article)).fetchone():
            raise ValueError('Concurrent law import; retry on next question')
        record = LegislationRecord(record_type='legislation', legislation_type='law',
            law_no=document.law_no, law_name=document.law_name, article_no=article,
            article_title=None, title=document.law_name + ' m. ' + article,
            raw_text=body, external_id='mevzuat:kanun:' + document.law_no + ':m.' + article,
            content_hash=content_hash(body), source_url=document.pdf_url, scraped_at=now,
            metadata=dict(verified_against_mbs=True, mbs_text_verification=proof))
        db.row_factory = tuple_row
        result = upsert_legislation(db, record, max_chunk_chars=16000)
        db.execute("UPDATE legal_sources SET ingestion_method='official_mbs_pdf_http', ingest_status='ready' WHERE id=%s",
                   (result.legal_source_id,))
        return result.legal_source_id


def _court_search(topic):
    from ingestion.yargitay.portal import YargitayPortalClient
    from ingestion.yargitay.scraper import _search_filters, ScraperConfig, decision_from_portal_row
    from ingestion.yargitay.parser import parse_decision
    from pathlib import Path
    from api.db import admin_database_connection
    from ingestion.yargitay.store import upsert_decision
    from psycopg.rows import tuple_row
    filters = _search_filters(ScraperConfig(output_dir=Path('.local'), keyword=topic, chamber=''), page_number=1, page_size=2)
    client = YargitayPortalClient(max_retries=1, timeout_seconds=30, opener=_PacedOpener())
    client.begin_detailed_search(filters)
    page = client.search_page(filters)
    ids = []
    for row in page.rows[:2]:
        if not re.fullmatch(r'\d{1,30}', row.document_id):
            continue
        decision = decision_from_portal_row(row, client.fetch_document_html(row.document_id))
        require_official_url(decision.source_url)
        # Match header identities against the full document, not merely search metadata.
        parsed = parse_decision(body_text=decision.raw_text[:2500])
        if (parsed is None or parsed.docket_no != decision.docket_no
                or parsed.decision_no != decision.decision_no
                or (parsed.decision_date is not None and parsed.decision_date != decision.decision_date)
                or not 200 <= len(decision.raw_text) <= 500000):
            continue
        with admin_database_connection() as db:
            db.execute("SET LOCAL lock_timeout='2s'")
            db.execute("SET LOCAL statement_timeout='30s'")
            db.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('web-court:' + decision.external_id,))
            # Separate indexed lookups: OR across source/detail tables forced a
            # scan of the multi-million-row corpus in the live acceptance run.
            existing = db.execute('''SELECT ls.id, ls.content_hash FROM legal_sources ls
                WHERE ls.source_type='court_decision' AND ls.is_current AND ls.deleted_at IS NULL
                  AND ls.external_id=%s''', (decision.external_id,)).fetchall()
            if not existing:
                existing = db.execute('''SELECT ls.id, ls.content_hash FROM court_decision_details d
                    JOIN legal_sources ls ON ls.id=d.legal_source_id
                    WHERE ls.source_type='court_decision' AND ls.is_current AND ls.deleted_at IS NULL
                      AND lower(d.court_name)=lower(%s) AND lower(COALESCE(d.chamber,''))=lower(%s)
                      AND d.docket_no=%s AND d.decision_no=%s''',
                    (decision.court_name, decision.chamber or '', decision.docket_no, decision.decision_no)).fetchall()
            if existing:
                if len(existing) == 1 and existing[0]['content_hash'] == decision.content_hash:
                    ids.append(existing[0]['id'])
                continue  # Differing text requires the separate corpus review workflow.
            db.row_factory = tuple_row
            ids.append(upsert_decision(db, decision).legal_source_id)
    return ids, page.records_filtered


def research_official(queries, contexts, *, public_scope: bool,
                      fetch_law=None, store_article=None, court_search=None, load_contexts=None):
    """One request, sequential institutions; only persisted evidence returns.

    Explicit scope and offline guard apply before *any* outbound operation.
    Injectable adapters make the whole workflow testable without paid calls.
    """
    if not public_scope or any(c.source_type == 'document' for c in contexts):
        return ResearchResult(statuses=({'source': 'web', 'status': 'private_scope_blocked'},))
    if os.getenv('NHR_OFFLINE_AUDIT') == '1':
        return ResearchResult(statuses=({'source': 'web', 'status': 'offline'},))
    fetch_law = fetch_law or fetch_law_cached
    store_article = store_article or _store_article
    court_search = court_search or (lambda topic: _cached(_COURT_CACHE, topic, _court_search, ttl=300))
    load_contexts = load_contexts or _load_contexts
    ids, statuses, documents = [], [], {}
    # Keep admitted local law sources; web fills absent/incomplete provisions.
    from api.ai.free_answer import _usable
    present = {(c.law_no, c.article_no) for c in contexts if c.source_type == 'legislation' and _usable(c, 16000)}
    for law, article in statute_references(queries, contexts):
        if (law, article) in present:
            continue
        try:
            if law not in documents:
                documents[law] = fetch_law(law)
            ids.append(store_article(*documents[law], article))
            statuses.append(dict(source='mevzuat', status='document_verified'))
        except Exception as exc:
            # Never log raw questions, provider payloads, cookies or transport errors.
            statuses.append(dict(source='mevzuat', status='unavailable_or_unverified', failure_type=type(exc).__name__))
    for topic in safe_topics(' '.join(queries)):
        try:
            found, total = court_search(topic)
            ids.extend(found)
            statuses.append(dict(source='yargitay', status='searched', matched=total,
                                 documents=len(found), exhaustive=False))
        except Exception as exc:
            statuses.append(dict(source='yargitay', status='unavailable_or_unverified', exhaustive=False,
                                 failure_type=type(exc).__name__))
            break  # Do not retry a blocked/rate-limited institution with another keyword.
    try:
        result = tuple(load_contexts(tuple(dict.fromkeys(ids)))) if ids else ()
    except Exception:
        result = ()
        statuses.append(dict(source='corpus', status='read_failed'))
    return ResearchResult(result, tuple(statuses))
