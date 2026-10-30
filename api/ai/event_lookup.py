"""Bounded, read-only temporal basis lookup for completed personal word problems."""
from dataclasses import dataclass
from datetime import date

import psycopg

from api.ai.event_context import EventContext, build_event_context, source_covers_date
from api.ai.rag import RAGContext


@dataclass(frozen=True)
class EventBasisLookup:
    event: EventContext
    references: tuple[tuple[str, str], ...]
    contexts: tuple[RAGContext, ...]
    complete: bool
    unavailable: bool = False


def _load(reference, target):
    from api.ai.retrieval import STATUTE_RETRIEVAL_SQL, _execute_retrieval
    from api.db import database_connection
    with database_connection() as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        return _execute_retrieval(connection, STATUTE_RETRIEVAL_SQL,
            dict(law_no=reference[0], article_no=reference[1], as_of=target, top_k=16), timeout="2s")


def lookup_event_basis(question, search_question, *, history=(), prior_questions=(), as_of=None,
                       loader=None, today=None):
    """Query exact known provision IDs, not a salary/year-as-law lexical search.

    An indexed historical lookup cannot establish absence from the whole corpus.
    Empty/error results only say this required proof was not obtained. No model,
    external portal, database write or current-version fallback occurs here.
    """
    event = build_event_context(question, (), history=history, prior_questions=prior_questions, as_of=as_of)
    if event is None or event.applicable_on is None or event.applicable_on >= (today or date.today()):
        return None
    from api.statute_hints import suggest
    references = tuple(dict.fromkeys((hint.law_no,hint.article_no) for hint in suggest(search_question)))[:3]
    if not references:
        return None
    found, complete, unavailable = [], True, False
    for reference in references:
        try:
            rows = (loader or _load)(reference, event.applicable_on)
        except psycopg.Error:
            rows, unavailable = [], True
        matching = [c for c in rows if c.source_type == "legislation" and c.verification == "official"
                    and (c.law_no,c.article_no) == reference and source_covers_date(c,event.applicable_on)]
        if not matching or len(rows) >= 16:
            complete = False
        found.extend(matching)
    return EventBasisLookup(event,references,tuple(found),complete,unavailable)


def load_current_event_reference(lookup: EventBasisLookup, *, loader=None):
    """Current text may explain a rule, NEVER prove a historical entitlement.

    Keep this separate from ``contexts``/``complete`` so successful current
    lookup cannot silently turn missing historical coverage into verification.
    The caller must disclose the narrow reference-only scope to both models
    and user. No external fetching or writes occur.
    """
    if lookup.complete:
        return []
    result = []
    for reference in lookup.references:
        try:
            rows = (loader or _load)(reference, None)
        except psycopg.Error:
            continue
        if len(rows) >= 16:
            continue  # an incomplete article cannot silently lose its exceptions
        result.extend(c for c in rows if c.source_type == "legislation"
                      and c.verification == "official"
                      and (c.law_no, c.article_no) == reference)
    return result
