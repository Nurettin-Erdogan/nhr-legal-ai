"""Select whole source sentences; don't always feed the opening 600 characters."""

import re

from api.ai.search_plan import normalize, plan_search


def select_passage(text: str, question: str, budget: int) -> str:
    # Lazy import: source_support's type definitions depend on rag.
    from api.ai.source_support import _sentences

    plan = plan_search(question)
    terms = [word[:max(4, len(word) - 2)] for word in plan.text.split() if len(word) >= 4]
    sentences = _sentences(text, include_tail=False)

    def score(item):
        index, sentence = item
        normalized = normalize(sentence)
        overlap = sum(term in normalized for term in terms)
        phrase = 8 if plan.phrase and plan.phrase in normalized else 0
        allegation = 4 if re.search(r"iddia|talep ve dava|dava dilekçesinde", normalized) else 0
        return phrase + overlap - allegation, -index

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
