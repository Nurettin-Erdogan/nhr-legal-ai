"""Bounded candidate discovery is distinct from the final model context.

Counters describe only this request's returned candidates, never corpus totals.
No source text, private document metadata or user question is placed in them.
"""
from api.ai.rag import RAGContext
from api.ai.trust import verified_contexts


def candidate_pool_size(answer_size: int) -> int:
    return min(96, max(48, answer_size * 8))


def select_answer_contexts(contexts: list[RAGContext], limit: int) -> list[RAGContext]:
    """First take one chunk per source, then fill remaining slots in rank order."""
    unique, extra, seen = [], [], set()
    for context in verified_contexts(contexts):
        if context.source_id in seen:
            extra.append(context)
        else:
            unique.append(context)
            seen.add(context.source_id)
    return (unique + extra)[:limit]


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
        'lexical_candidates': retrieval.get('lexical_candidates', 0),
        'semantic_candidates': retrieval.get('semantic_candidates', 0),
        'exhaustive': False,
    }
