"""Explicit decision cardinality; never a substitute for relevance checking."""
import re

from api.ai.search_plan import normalize

_NUMBERS = {'bir': 1, 'iki': 2, 'üç': 3, 'dört': 4, 'beş': 5,
            'altı': 6, 'yedi': 7, 'sekiz': 8, 'dokuz': 9, 'on': 10}
_COUNT = re.compile(
    r'\b(\d+|' + '|'.join(_NUMBERS) + r')\s+'
    r'(?:(?:ayrı|farklı|gerçek|ilgili|doğrudan|konuyla|doğrulanabilir|doğrulanmış|'
    r'güncel|resmi|resmî|yargıtay|danıştay|sayıştay|aym|emsal)\s+){0,8}'
    r'(?:karar\w*|içtihat\w*)\b'
)


def requested_decision_count(question: str) -> int:
    from api.ai.relevance import case_law_requested
    text = normalize(question)
    counts = [int(token) if token.isdecimal() else _NUMBERS[token]
              for token in _COUNT.findall(text)]
    return max(counts, default=1 if case_law_requested(question) else 0)


def distinct_decisions(question, contexts):
    from api.ai.decision_attribution import requested_court_evidence
    identities = set()
    seen_sources = set()
    for context in requested_court_evidence(question, contexts):
        if context.source_type != 'court_decision':
            continue
        if context.source_id in seen_sources:
            continue
        seen_sources.add(context.source_id)
        # Different chunks (or duplicate corpus records) of one judgment are
        # still one judgment. Fall back to source ID only without a full caption.
        caption = tuple(normalize(value or '') for value in
                        (context.court_name, context.chamber, context.docket_no, context.decision_no))
        key = ('caption', *caption) if all(caption) else ('source', str(context.source_id))
        identities.add(key)
    return len(identities)
