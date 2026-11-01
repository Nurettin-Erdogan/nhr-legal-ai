"""GEÇİCİ / EK / "/A" articles are different articles from the plain number, however a lawyer writes the reference.

Measured 2026-10-31: "6769 sayılı Kanunun geçici 6. maddesi" was read as article 6 (the optional prefix was only accepted in front of
the word "madde"), so a question about a transitional article would have been answered from the wrong article.
"""

import pytest

from api.ai.on_demand_verify import explicit_statute_reference
from api.ai.retrieval import question_article_numbers


@pytest.mark.parametrize("question, expected", [
    ("6769 sayılı Kanunun geçici 6. maddesi ne diyor?", ("GEÇİCİ 6",)),
    ("6769 sayılı Kanun geçici madde 6", ("GEÇİCİ 6",)),
    ("4857 sayılı Kanunun Geçici 6. maddesi", ("GEÇİCİ 6",)),
    ("193 sayılı Kanun ek 3. madde", ("EK 3",)),
    ("ek madde 3", ("EK 3",)),
    ("6769 sayılı kanun 6. madde", ("6",)),
    ("TBK m. 17/A", ("17/A",)),
])
def test_prefixed_article_references_keep_their_identity(question, expected):
    assert question_article_numbers(question) == expected


@pytest.mark.parametrize("question", [
    "6769 sayılı Kanunun geçici 6. maddesi", "6769 sayılı Kanun geçici madde 6", "193 sayılı Kanun ek 3. madde"])
def test_the_legacy_explicit_reference_never_guesses_the_plain_article_for_a_prefixed_one(question):
    assert explicit_statute_reference(question) is None


def test_the_plain_explicit_reference_still_works():
    assert explicit_statute_reference("6769 sayılı kanun 6. madde") == ("6769", "6")
    assert explicit_statute_reference("4857 sayılı Kanunun madde 17") == ("4857", "17")
