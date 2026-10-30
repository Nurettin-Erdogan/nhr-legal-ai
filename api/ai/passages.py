"""Select whole source sentences; don't always feed the opening 600 characters."""

import re

from api.ai.search_plan import normalize, plan_search
from api.ai.query_vocabulary import expand_search_terms, definition_evidence_score


def is_duration_question(question: str) -> bool:
    return bool(re.search(r"\bsüre\w*|\bkaç (?:gün|ay|yıl|sene|hafta)", normalize(question)))


def contains_duration(text: str) -> bool:
    return bool(re.search(r"\b(?:\d+|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on|onbeş|yirmi|otuz|kırk|elli|altmış|doksan)\s+(?:gün|ay|yıl|sene|hafta)\w*", normalize(text)))


def sentence_score(sentence: str, question: str) -> float:
    """Relevance is a ranking heuristic, never a legal truth/verification flag."""
    plan = plan_search(question)
    normalized = normalize(expand_search_terms(sentence))
    terms = {word[:max(4, len(word) - 2)] for word in plan.text.split() if len(word) >= 4}
    overlap = sum(term in normalized for term in terms)
    phrase = 8 if plan.phrase and plan.phrase in normalized else 0
    allegation = 15 if re.search(r"iddia ederek|talep ve dava|dava dilekçesinde|cevap dilekçesinde", normalized) else 0
    duration = 0
    if is_duration_question(question):
        # Prefer an actual duration + starting event, not merely 'süresinde açıldı'.
        duration = 12 if contains_duration(normalized) else -5
        if duration > 0 and re.search(r"itibaren|tebliğ|başla", normalized):
            duration += 6
    return phrase + overlap + duration - allegation + definition_evidence_score(question, sentence)


def select_passage(text: str, question: str, budget: int) -> str:
    # Lazy import: source_support's type definitions depend on rag.
    from api.ai.source_support import _sentences

    sentences = _sentences(text, include_tail=False)

    def score(item):
        index, sentence = item
        return sentence_score(sentence, question), -index

    selected = []
    used = 0
    for index, sentence in sorted(enumerate(sentences), key=score, reverse=True):
        if len(re.findall(r"\w+", sentence)) < 4 or score((index, sentence))[0] <= 0:
            continue
        if used + len(sentence) + 1 > budget:
            continue
        selected.append((index, sentence))
        used += len(sentence) + 1
    return "\n".join(sentence for _, sentence in sorted(selected))
