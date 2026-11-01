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


def _context(source_type, title, law_no=None, article_no=None, rank=0.5):
    from types import SimpleNamespace
    from uuid import uuid4

    return SimpleNamespace(
        source_id=uuid4(), source_type=source_type, title=title, source_url=None, authority=None, court_name=None, chamber=None,
        docket_no=None, decision_no=None, decision_date=None, law_name=None, law_no=law_no, article_no=article_no, article_title=None,
        version_date=None, effective_from=None, effective_to=None, source_version=None, revision=1, content="", rank=rank,
        verification="official",
    )


def test_narrative_results_put_topical_articles_first_and_unrelated_laws_last(monkeypatch):
    from uuid import uuid4

    topical = {"id": uuid4(), "law_name": "İŞ KANUNU", "law_no": "4857", "article_no": "17", "article_title": "Süreli fesih",
               "source_url": None, "content": "Madde 17 ..."}
    monkeypatch.setattr(legal.statute_hints, "suggest", lambda text: [object()])
    monkeypatch.setattr(legal.statute_hints, "load_rows", lambda connection, hints: [topical])

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(legal, "database_connection", lambda: _Connection())
    contexts = [
        _context("legislation", "PETROL OFİSİ KEFALET SANDIĞI TÜZÜĞÜ m. 23", "x", "23", rank=0.81),
        _context("legislation", "İŞ KANUNU m. 17 (aynı madde, getirmeden)", "4857", "17"),
        _context("court_decision", "Yargıtay 9. HD E. 2020/1"),
    ]
    titles = [hit["title"] for hit in legal._narrative_hits("işçi çıkarıldı", contexts)]
    assert titles == ["İŞ KANUNU m. 17 — Süreli fesih", "Yargıtay 9. HD E. 2020/1", "PETROL OFİSİ KEFALET SANDIĞI TÜZÜĞÜ m. 23"]


def test_search_offset_is_capped_so_a_huge_offset_cannot_trigger_a_giant_candidate_scan():
    # candidate_limit = (offset + limit) * 10; sınırsız offset tek isteği dakikalarca meşgul ederdi (ölçüldü: 99.999.999 → 44 sn).
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    for path in ("/api/legal/search?q=kira&offset=201", "/api/legal/semantic?q=kira&offset=99999999"):
        response = client.get(path)
        assert response.status_code in (401, 422)  # oturum yoksa 401; oturum varsa 422 (sınır)
