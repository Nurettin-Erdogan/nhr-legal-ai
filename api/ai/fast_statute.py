"""Optional, bounded current-provision lookup before expensive discovery.

This supplies evidence, not an answer or a corpus-wide search result. Ambiguous,
historical, case-law and private-workspace questions keep the normal pipeline.
"""
import re
from time import monotonic

import psycopg

from api.ai.relevance import case_law_requested, question_intent
from api.ai.search_plan import normalize


def fast_reference(question):
    q = normalize(question)
    if len(q) > 200 or case_law_requested(q) or re.search(
        r'\b(?:delil\w*|ispat\w*|kanıt\w*|eski\w*|tarih\w*|önceki|ayrıca|ve|karar\w*)\b|\b(?:19|20)\d{2}\b', q
    ):
        return None
    intent = question_intent(q)
    if not intent or not intent.statute:
        return None
    from api.ai.passages import is_duration_question
    if intent.name == 'rent_increase':
        return intent.statute
    if intent.name == 'severance' and re.search(r'\b(?:şart\w*|koşul\w*|hak kazan\w*)', q):
        return intent.statute
    if intent.name == 'objection_annulment' and is_duration_question(q):
        return intent.statute
    return None


def _load(reference, limit):
    from api.db import database_connection
    from api.ai.retrieval import _execute_retrieval, STATUTE_RETRIEVAL_SQL
    # Keep the ordinary source-trust, deletion and current-version predicates.
    with database_connection() as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        return _execute_retrieval(connection, STATUTE_RETRIEVAL_SQL,
            dict(law_no=reference[0], article_no=reference[1], as_of=None, top_k=limit),
            timeout='1s')


def try_fast_statute(*, question, as_of=None, project_id=None, conversation_id=None,
                     max_chunks=6, max_chars=6000, diagnostics=None, loader=None):
    info = diagnostics if diagnostics is not None else {}
    if as_of is not None or project_id is not None or conversation_id is not None:
        return []
    reference = fast_reference(question)
    if reference is None:
        return []
    started = monotonic()
    try:
        # One extra row detects clipping instead of silently losing exceptions.
        rows = (loader or _load)(reference, max_chunks + 1)
    except psycopg.Error:
        info['fast_statute_status'] = 'unavailable'
        return []
    finally:
        info['fast_statute_ms'] = round((monotonic() - started) * 1000, 1)
    if (not rows or len(rows) > max_chunks or len({c.source_id for c in rows}) != 1
            or any(c.source_type != 'legislation' or c.verification != 'official'
                   or (c.law_no, c.article_no) != reference or not c.content.strip() for c in rows)):
        info['fast_statute_status'] = 'not_sufficient'
        return []
    from datetime import date
    if any((c.effective_from and c.effective_from > date.today())
           or (c.effective_to and c.effective_to < date.today()) for c in rows):
        return []
    from api.ai.evidence_selection import evidence_candidates, preserve_statutory_scope
    evidence = evidence_candidates(question, rows, total_chars=max_chars)
    if not evidence or not preserve_statutory_scope(f'[K{evidence[0].marker}]', rows, question):
        info['fast_statute_status'] = 'not_sufficient'
        return []
    info.update(fast_statute_status='hit', strategy='verified_statute',
                research_deferred=True, partial=False, exhaustive=False,
                lexical_candidates=0, semantic_candidates=0)
    return rows
