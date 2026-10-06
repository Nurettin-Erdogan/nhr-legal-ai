"""Karar aramasında sıra: açık madde atfı ve mahkeme düzeyi (yalnız sıralama; kayıt eklenmez/çıkarılmaz)."""

from __future__ import annotations

import pytest

from api import legal


@pytest.mark.parametrize(
    "query,expected",
    [
        ("4857 sayılı Kanun 25", ("4857", "25")),
        ("6098 m. 344", ("6098", "344")),
        ("4857 sayılı İş Kanunu madde 18", ("4857", "18")),
        ("6100 sayılı Hukuk Muhakemeleri Kanunu 389. madde", ("6100", "389")),
        ("2004 sayılı kanun 67", ("2004", "67")),
    ],
)
def test_explicit_statute_references_are_recognised(query, expected):
    assert legal.explicit_article_reference(query) == expected


@pytest.mark.parametrize(
    "query",
    ["kıdem tazminatı", "2019/1234", "Yargıtay 9. Hukuk Dairesi 2015/1234", "E. 2019/1234 K. 2020/55", "ihtiyati tedbir 389", "işçi 2020 yılında 15 gün çalıştı"],
)
def test_docket_numbers_and_ordinary_queries_are_not_mistaken_for_a_statute_reference(query):
    assert legal.explicit_article_reference(query) is None


def test_search_orders_by_authority_within_relevant_candidates_and_prefers_verified_records():
    for sql in (legal._CURRENT_SEARCH_SQL, legal._CURRENT_SEARCH_OR_SQL, legal._HISTORICAL_SEARCH_SQL):
        order = sql[sql.rindex("ORDER BY") :]
        assert "max(rank) OVER ()" in order and "seed_pending" in order
        # Katman, puan ve tarih sırasından ÖNCE gelir; doğrulanmamış kayıt aynı katmanda sona düşer.
        assert order.index("max(rank) OVER ()") < order.index("seed_pending") < order.index("rank DESC")
        assert "yargıtay|danıştay|anayasa mahkemesi" in order
    assert "seed_pending" not in legal.LegalSearchResponse.model_fields  # yalnız sıralama alanı; yanıta girmez
    assert legal._SEARCH_MIN_CANDIDATES >= 300

