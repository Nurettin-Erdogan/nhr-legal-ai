"""Fair, bounded selection of verified evidence across independent searches.

One query's hints must not consume every slot before another query's semantic
results are considered. Chunk identity (not a model supplied source number) is
the only deduplication key. This module performs no generation or network I/O.
"""
from collections.abc import Sequence

from api.ai.rag import RAGContext
from api.ai.trust import verified_contexts


def query_scoped_evidence(query: str, contexts: Sequence[RAGContext]) -> list[RAGContext]:
    """Scope one explicitly named-law lane, never the whole answer pool.

    Independent concept/facet queries and initial sources remain available.
    Decisions may interpret the named law, so are not filtered by law metadata.
    Apply court/regime constraints before bounded selection, not after an
    irrelevant candidate has already consumed a slot. Text relevance is only
    a stable ranking preference, never a trust or entailment declaration.
    """
    from api.ai.retrieval import question_law_numbers
    from api.ai.decision_attribution import requested_court_evidence
    from api.ai.relevance import context_relevant
    laws = question_law_numbers(query)
    scoped = requested_court_evidence(query, [c for c in contexts
        if not laws or c.source_type != 'legislation' or c.law_no in laws])
    return sorted(scoped, key=lambda c: not context_relevant(query, c))


def balanced_evidence(lanes: Sequence[Sequence[RAGContext]], limit: int) -> list[RAGContext]:
    if limit <= 0:
        return []
    queues = []
    for lane in lanes:
        first, extra, sources = [], [], set()
        for context in verified_contexts(list(lane)):
            (extra if context.source_id in sources else first).append(context)
            sources.add(context.source_id)
        queues.append(first + extra)
    result, seen = [], set()
    for rank in range(max((len(lane) for lane in queues), default=0)):
        for lane in queues:
            if rank >= len(lane):
                continue
            context = lane[rank]
            if context.chunk_id not in seen:
                seen.add(context.chunk_id)
                result.append(context)
                if len(result) >= limit:
                    return result
    return result
