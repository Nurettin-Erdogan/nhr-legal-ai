"""Arama sırası ve istatistik sorgusu: veritabanı gerektirmeyen SQL metni denetimleri."""

from __future__ import annotations

import inspect

from api import legal


def test_current_search_prefers_the_article_whose_heading_is_the_query():
    # "kıdem tazminatı" aramasında İş Kanunu m. 14 (başlığı bu), ifadeyi yalnız başlık ortasında geçiren m. 112'den önce gelmeli.
    sql = legal._CURRENT_SEARCH_SQL
    assert "article_title ILIKE %(query)s" in sql
    assert sql.index("article_title ILIKE") > sql.index("WHEN court_name ~*")  # yetki katmanından sonra
    assert sql.index("article_title ILIKE") < sql.index("rank DESC,", sql.rindex("ORDER BY"))  # puandan önce


def test_latest_decision_date_ignores_dates_in_the_future():
    assert "ls.published_at <= now()" in inspect.getsource(legal._load_corpus_stats)
