"""Pre-writing source readiness, not a proof of legal answer completeness."""
from concurrent.futures import ThreadPoolExecutor

from api.ai.evidence_pool import balanced_evidence
from api.ai.trust import verified_contexts


def requested_decisions_ready(question, rows):
    """Structural readiness only; matching holdings still require checking."""
    if not rows:
        return False
    from api.ai.decision_requirements import distinct_decisions, requested_decision_count
    return distinct_decisions(question, rows) >= requested_decision_count(question)


def prepare_parts(parts, contexts, retrieve, *, usable, normalize=lambda rows: rows,
                  ready=lambda text, rows: bool(rows)):
    """Repair empty/unusable part bindings once, before spending a write call.

    Existing checked sources remain available. Newly found sources are bound
    only to the part searched; no generated answer is evidence. Readiness only
    means there is a usable source, not that every legal claim is supported.
    """
    pool = list(contexts)
    by_id = {c.chunk_id: c for c in verified_contexts(pool) if usable(c)}
    missing = [(text, ids) for text, ids in parts
               if not ready(text, [by_id[key] for key in ids if key in by_id])]

    def search(item):
        text, _ = item
        try:
            return text, [c for c in verified_contexts(normalize(retrieve(text))) if usable(c)]
        except Exception:
            return text, []

    repairs = {}
    if missing:
        with ThreadPoolExecutor(max_workers=min(2, len(missing))) as executor:
            repairs = dict(executor.map(search, missing))
    known = {c.chunk_id for c in pool}
    for lane in repairs.values():
        for context in lane:
            if context.chunk_id not in known:
                known.add(context.chunk_id)
                pool.append(context)
    bindings = [(text, frozenset(key for key in ids if key in by_id)
                 | frozenset(c.chunk_id for c in repairs.get(text, ()))) for text, ids in parts]
    # Place one usable source from every part before optional background text.
    by_id = {c.chunk_id: c for c in pool}
    lanes = [[by_id[key] for key in by_id if key in ids] for _, ids in bindings]
    prioritized = balanced_evidence(lanes, len(pool))
    selected = {c.chunk_id for c in prioritized}
    ready_count = sum(ready(text, [by_id[key] for key in ids if key in by_id]) for text, ids in bindings)
    return prioritized + [c for c in pool if c.chunk_id not in selected], bindings, {
        'parts': len(parts), 'targeted_searches': len(missing),
        'ready_parts': ready_count,
        'unready_parts': len(parts) - ready_count,
    }
