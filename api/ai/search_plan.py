"""Deterministic search intent; never throw away the third content word."""

from dataclasses import dataclass
import re


def normalize(text: str) -> str:
    return text.replace("İ", "i").lower().translate(str.maketrans("âîû", "aiu"))


_WORDS = re.compile(r"[\w]+", re.UNICODE)
_QUESTION_WORDS = frozenset("hangi nasıl nasil ne nedir nelerdir neden mi mı mu mü bir ve veya ile için icin hakkında konusunda göre hangi şartlarda şartları şartlar şart koşullarda koşulları koşullar verilir verilebilir yapılır yapılabilir gerekir gerekiyor olur olabilir alınır alabilir nelere bana açıkla anlat".split())
_PHRASES = (
    "ortak velayet", "kıdem tazminatı", "yıllık izin", "işe iade",
    "haklı fesih", "haksız fesih", "adil yargılanma", "bireysel başvuru",
    "itirazın iptali", "aile konutu", "idari işlem", "fazla çalışma",
)


@dataclass(frozen=True)
class SearchPlan:
    text: str
    phrase: str


def plan_search(question: str) -> SearchPlan:
    words = _WORDS.findall(normalize(question))
    text = " ".join(word for word in words if word not in _QUESTION_WORDS)
    phrase = next((p for p in _PHRASES if re.search(r"(?<!\w)" + re.escape(p) + r"\w*", " ".join(words))), "")
    return SearchPlan(text=text, phrase=phrase)


# Both conditions are parameterized. A phrase requirement is never silently
# relaxed to OR: "ortak çocuk ... velayet" is not "ortak velayet".
SEARCH_QUERY_SQL = """
SELECT CASE WHEN %(phrase)s <> ''
    THEN plainto_tsquery('turkish', %(query)s) && phraseto_tsquery('turkish', %(phrase)s)
    ELSE plainto_tsquery('turkish', %(query)s)
END AS value
"""
