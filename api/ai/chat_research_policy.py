"""Request-local routing; source readiness is never a completeness guarantee."""
import re

from api.ai.search_plan import normalize
from api.ai.evidence_readiness import requested_decisions_ready
from api.ai.decision_attribution import requested_court_evidence
from api.ai.trust import verified_contexts


def official_research_reasons(question, plan, contexts, *, usable, relevant):
    """Use official web for explicit freshness or structurally missing evidence.

    No user data is sent here. The existing outbound allowlist/sanitization and
    claim checker remain authoritative. Local readiness does not prove that
    every part can be answered; later verification can still reject claims.
    """
    value = normalize(question)
    if re.search(r'\bgüncel\w*|\bbugün\b|\bson değişiklik\w*|\byürürlük\w*|'
                 r'\b(?:19|20)\d{2}\s*(?:yılı?\s*)?itibarıyla', value):
        return ('freshness_requested',)
    available = [c for c in verified_contexts(contexts) if usable(c)]
    gaps = []
    for index, (text, queries) in enumerate(plan, 1):
        rows = [c for c in available if any(relevant(q, c) for q in (text, *queries))]
        rows = requested_court_evidence(text, rows)
        if not requested_decisions_ready(text, rows):
            gaps.append(f'part_{index}_source_gap')
    return tuple(gaps)
