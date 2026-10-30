"""Bounded candidate discovery is distinct from the final model context.

Counters describe only this request's returned candidates, never corpus totals.
No source text, private document metadata or user question is placed in them.
"""
import re
from api.ai.rag import RAGContext
from api.ai.trust import verified_contexts


def candidate_pool_size(answer_size: int) -> int:
    return min(96, max(48, answer_size * 8))


def select_answer_contexts(contexts: list[RAGContext], limit: int, *, question: str = '') -> list[RAGContext]:
    """First take one chunk per source, then fill remaining slots in rank order."""
    from api.ai.authority import primary_legislation_markers
    eligible = verified_contexts(contexts)
    if question:
        from api.ai.decision_attribution import decision_matches_question
        eligible = [c for c in eligible if decision_matches_question(question, c)]
    primary = primary_legislation_markers(question, eligible) if question else set()
    if primary:
        # Kullanıcının kendi belgeleri mevzuat odağıyla elenmez: belge sorusunda asıl kanıt odur.
        eligible = [c for i, c in enumerate(eligible, 1) if i in primary or c.source_type == 'document']
    if question:
        from api.ai.relevance import case_law_requested
        from api.ai.search_plan import normalize
        from api.ai.retrieval import _is_secondary_regulation
        q = normalize(question)
        # A request for case law should not spend its few decision slots on
        # administrative/public-procurement records merely sharing keywords.
        # Preserve those regimes when explicitly requested and never drop them
        # from the candidate pool. User documents keep their original priority.
        if case_law_requested(question) and not re.search(
                r'sayıştay|kamu denet|\bkdk\b|kamu ihale|belediye|kamu kurum', q):
            secondary_asked = bool(re.search(r'yönetmelik|tebliğ|genelge', q))
            eligible = sorted(eligible, key=lambda c: (
                c.source_type == 'other' or
                (not secondary_asked and _is_secondary_regulation(c))))
        # Reorder only decision positions: retain statute/document priorities.
        # Party allegations are searchable but should not exhaust the model's
        # decision slots before the court's relevant reasoning is considered.
        from api.ai.decision_attribution import decision_selection_key
        decisions = iter(sorted((c for c in eligible if c.source_type == 'court_decision'),
                                key=lambda c: decision_selection_key(c, question)))
        eligible = [next(decisions) if c.source_type == 'court_decision' else c for c in eligible]
    unique, extra, seen = [], [], set()
    for context in eligible:
        if context.source_id in seen:
            extra.append(context)
        else:
            unique.append(context)
            seen.add(context.source_id)
    return (unique + extra)[:limit]


# What the user is told about a search that did not run to completion. A lane that fell back to a bounded sample still
# delivered ranked-by-term results from a sample; a lane that returned nothing (time out, broken connection, missing index)
# is a different, graver statement. Measured 2026-10-30: about half of everyday questions hit the first kind, because a
# decision search on ~29 M chunks cannot rank every match of a common legal term within the time budget.
LIMIT_NONE, LIMIT_SAMPLED, LIMIT_FAILED = 'none', 'sampled', 'failed'
_SAMPLED_STATUSES = frozenset({'timeout_then_tiered', 'timeout_then_official', 'official_only'})
_FAILED_STATUSES = frozenset({'timeout', 'connection_error', 'error', 'skipped_unindexed'})
_LIMIT_ORDER = (LIMIT_NONE, LIMIT_SAMPLED, LIMIT_FAILED)


def worse_limit(*limits: str | None) -> str:
    """The graver of several limits; unknown values count as none."""
    return max((value for value in limits if value in _LIMIT_ORDER), key=_LIMIT_ORDER.index, default=LIMIT_NONE)


def retrieval_limit(info: dict) -> str:
    """Classify one search's diagnostics: ``failed`` > ``sampled`` > ``none``.

    A search flagged partial without lane detail (an older code path, or the outer timeout fallback) is ``failed``: the
    stronger statement is the safe one when the reason is unknown.
    """
    statuses = {branch.get('status') for branch in info.get('branches') or () if isinstance(branch, dict)}
    if info.get('decision_search') == 'timeout' or statuses & _FAILED_STATUSES:
        return LIMIT_FAILED
    if statuses & _SAMPLED_STATUSES:
        return LIMIT_SAMPLED
    return LIMIT_FAILED if info.get('partial') else LIMIT_NONE


def search_summary(candidates, verified, selected, retrieval, verification):
    return {
        'candidate_chunks': len(candidates),
        'candidate_documents': len({c.source_id for c in candidates}),
        'pending_documents': len({c.source_id for c in candidates if c.verification == 'third_party'}),
        'verified_documents': len({c.source_id for c in verified}),
        'selected_documents': len({c.source_id for c in selected}),
        'unverified_excluded': len({c.source_id for c in candidates} - {c.source_id for c in verified}),
        'verification_attempted': verification.get('attempted', 0),
        'verification_promoted': verification.get('promoted', 0),
        'verification_stop': verification.get('stop_reason', 'no_pending'),
        'retrieval_partial': bool(retrieval.get('partial', False)),
        'retrieval_limit': retrieval_limit(retrieval),
        'lexical_candidates': retrieval.get('lexical_candidates', 0),
        'semantic_candidates': retrieval.get('semantic_candidates', 0),
        'exhaustive': False,
        'retrieval_strategy': retrieval.get('strategy', 'full_candidates'),
        'research_deferred': bool(retrieval.get('research_deferred', False)),
    }
