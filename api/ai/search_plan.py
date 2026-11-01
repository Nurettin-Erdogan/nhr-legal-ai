"""Deterministic search intent; never throw away the third content word."""

from dataclasses import dataclass
import re
from api.ai.query_vocabulary import expand_search_terms


def normalize(text: str) -> str:
    # PDF line wrapping is presentation, not a phrase boundary. Do not join
    # characters within words or remove punctuation/numbers/negation.
    return " ".join(text.replace("İ", "i").lower().translate(str.maketrans("âîû", "aiu")).split())


_WORDS = re.compile(r"[\w]+", re.UNICODE)
_QUESTION_WORDS = frozenset("hangi nasıl nasil ne nedir nelerdir neden mi mı mu mü bir ve veya ile için icin hakkında konusunda göre hangi şartlarda şartları şartlar şart koşullarda koşulları koşullar verilir verilebilir yapılır yapılabilir gerekir gerekiyor olur olabilir alınır alabilir nelere bana açıkla anlat".split())
_PHRASES = (
    "ortak velayet", "kıdem tazminatı", "yıllık izin", "işe iade",
    "haklı fesih", "haksız fesih", "adil yargılanma", "bireysel başvuru",
    "itirazın iptali", "aile konutu", "idari işlem", "fazla çalışma",
    "muris muvazaası",
)
_ARTICLE_315 = re.compile(r"\b(?:tbk|türk\s*borçlar\s*kanunu|6098\s*(?:sayılı\s*)?(?:türk\s*)?borçlar\s*kanunu)\s*(?:m\.?\s*)?315\b", re.IGNORECASE)
_CASE_LAW_REQUEST = re.compile(r"\b(?:yargıtay|içtihat|emsal|karar(?:ları|larla|larıyla)?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class SearchPlan:
    text: str
    phrase: str


def plan_search(question: str) -> SearchPlan:
    words = _WORDS.findall(normalize(expand_search_terms(question)))
    text = " ".join(word for word in words if word not in _QUESTION_WORDS)
    phrase = next((p for p in _PHRASES if re.search(r"(?<!\w)" + re.escape(p) + r"\w*", " ".join(words))), "")
    return SearchPlan(text=text, phrase=phrase)


def research_queries(question: str) -> tuple[str, ...]:
    """Search the legal concept independently of a verbose research request.

    Instruction words such as 'deliller ve değerlendirme ölçütleri' need not
    occur in the same chunk as the actual explanation. Never drop the original
    query: the concept lane complements it and is not answer evidence.
    """
    queries = [question]
    phrase = plan_search(question).phrase
    if phrase and normalize(question).strip(' ?.!') != phrase:
        queries.append(phrase)

    # Long fact-pattern questions can over-constrain Turkish full-text search
    # (especially when asking for a specific statute plus case law). Keep the
    # original question for precise retrieval, and add one compact local lane
    # for TBK 315 cases. This only discovers candidates; the source/evidence
    # checks still decide what may support an answer.
    normalized = normalize(expand_search_terms(question))
    if _ARTICLE_315.search(normalized) and _CASE_LAW_REQUEST.search(normalized):
        queries.append("TBK 315 temerrüt fesih")

    return tuple(dict.fromkeys(queries))


# Both conditions are parameterized. A phrase requirement is never silently
# relaxed to OR: "ortak çocuk ... velayet" is not "ortak velayet".
SEARCH_QUERY_SQL = """
SELECT CASE WHEN %(phrase)s <> ''
    THEN plainto_tsquery('turkish', %(query)s) && phraseto_tsquery('turkish', %(phrase)s)
    ELSE plainto_tsquery('turkish', %(query)s)
END AS value
"""
