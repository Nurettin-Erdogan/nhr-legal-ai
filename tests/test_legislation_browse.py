"""Mevzuat gezgini: arama, madde sıralaması ve yalnız doğrulanmış güncel mevzuatın listelenmesi."""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager

import pytest
from fastapi import HTTPException

from api import legal
from api import legislation_browse as browse
from tests.test_ai_persistence import TEST_LAW_NO, _seed_legislation, connection as _connection_fixture

connection = _connection_fixture


def law(no, name, kind="law", articles=10):
    return browse.Law(no, name, kind, articles, None, None, browse.fold(f"{name} {no}"))


LAWS = [
    law("4857", "İŞ KANUNU", articles=120),
    law("6098", "TÜRK BORÇLAR KANUNU", articles=649),
    law("1475", "ESKİ İŞ KANUNU", articles=100),
    law("5510", "SOSYAL SİGORTALAR VE GENEL SAĞLIK SİGORTASI KANUNU", articles=106),
    law("20147052", "GENEL YÖNETİM MUHASEBE YÖNETMELİĞİ", "regulation", 355),
]


def test_fold_makes_ascii_queries_match_turkish_names():
    assert browse.fold("İŞ KANUNU") == browse.fold("is kanunu") == "is kanunu"
    assert browse.fold("  Türk   Borçlar ") == "turk borclar"


def test_search_ranks_number_then_prefix_then_containment():
    assert [item.law_no for item in browse.search_laws(LAWS, "4857", None)] == ["4857"]
    assert [item.law_no for item in browse.search_laws(LAWS, "is kanunu", None)] == ["4857", "1475"]  # başlangıç, sonra içinde geçen
    assert [item.law_no for item in browse.search_laws(LAWS, "borclar", None)] == ["6098"]
    assert browse.search_laws(LAWS, "yok boyle bir kanun", None) == []
    assert [item.law_no for item in browse.search_laws(LAWS, "", "regulation")] == ["20147052"]
    assert [item.law_no for item in browse.search_laws(LAWS, "", None)][0] == "6098"  # boş sorgu: madde sayısı çok olan önde


def test_a_law_and_article_reference_is_recognised():
    assert browse.parse_reference("4857 m. 18") == ("4857", "18")
    assert browse.parse_reference("4857 sayılı İş Kanunu madde 18") == ("4857", "18")
    assert browse.parse_reference("6098 md.344") == ("6098", "344")
    assert browse.parse_reference("5237 madde 53/A") == ("5237", "53/A")
    assert browse.parse_reference("kıdem tazminatı") is None
    assert browse.parse_reference("madde 18") is None
    assert [item.law_no for item in browse.search_laws(LAWS, "4857 m. 18", None)] == ["4857"]


def test_articles_sort_numerically_with_suffixes_then_temporary_and_additional():
    numbers = ["14", "2", "14/A", "Geçici Madde 1", "1", "Ek Madde 2", "100", "Geçici Madde 10", "Ek Madde 1", "14/B", None]
    ordered = sorted(numbers, key=browse.article_sort_key)
    assert ordered[:7] == ["1", "2", "14", "14/A", "14/B", "100", None] or ordered[:6] == ["1", "2", "14", "14/A", "14/B", "100"]
    tail = [item for item in ordered if item and (item.startswith("Geçici") or item.startswith("Ek"))]
    assert tail == ["Geçici Madde 1", "Geçici Madde 10", "Ek Madde 1", "Ek Madde 2"]  # Geçici önce, her grupta sayısal sıra


# --- Veritabanı: yalnız doğrulanmış, güncel mevzuat -------------------------------------------------

needs_db = pytest.mark.skipif(not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured")


@pytest.fixture
def api(connection, monkeypatch):  # noqa: F811
    @contextmanager
    def database_connection():
        yield connection

    monkeypatch.setattr(legal, "database_connection", database_connection)
    monkeypatch.setattr(legal, "_LAWS_FILE", None)  # testler gerçek disk önbelleğini okuyup yazmasın
    browse.reset_cache()
    yield connection
    browse.reset_cache()


@needs_db
def test_a_verified_current_law_is_listed_and_its_articles_are_returned(api):
    _seed_legislation(api)
    listed = asyncio.run(legal.list_laws(q=TEST_LAW_NO, kind=None, limit=30, offset=0))
    assert listed["total"] == 1 and listed["results"][0]["law_name"] == "İş Kanunu" and listed["results"][0]["articles"] == 1
    detail = asyncio.run(legal.law_articles(TEST_LAW_NO))
    assert detail["law_name"] == "İş Kanunu" and [a["article_no"] for a in detail["articles"]] == ["25"]
    assert detail["articles"][0]["article_title"].startswith("İşverenin") and detail["truncated"] is False


@needs_db
@pytest.mark.parametrize("change", ["metadata = '{}'::jsonb", "is_current = false", "deleted_at = now()", "ingest_status = 'pending'"])
def test_unverified_or_ineligible_laws_are_never_listed(api, change):
    _seed_legislation(api)
    api.execute(f"UPDATE legal_sources SET {change} WHERE external_id LIKE %s", (f"test/%/law/{TEST_LAW_NO}/%",))
    browse.reset_cache()
    assert asyncio.run(legal.list_laws(q=TEST_LAW_NO, kind=None, limit=30, offset=0))["total"] == 0
    with pytest.raises(HTTPException) as missing:
        asyncio.run(legal.law_articles(TEST_LAW_NO))
    assert missing.value.status_code == 404


@needs_db
def test_the_article_reference_in_a_query_is_reported_back(api):
    _seed_legislation(api)
    listed = asyncio.run(legal.list_laws(q=f"{TEST_LAW_NO} m. 25", kind=None, limit=30, offset=0))
    assert listed["article_reference"] == {"law_no": TEST_LAW_NO, "article_no": "25"}
    assert asyncio.run(legal.list_laws(q="İş Kanunu", kind=None, limit=30, offset=0))["article_reference"] is None


@needs_db
def test_the_cached_list_survives_a_database_failure(api, monkeypatch):
    import psycopg

    _seed_legislation(api)
    asyncio.run(legal.list_laws(q="", kind=None, limit=5, offset=0))
    browse._cache = (browse._cache[0] - browse.LAWS_TTL_SECONDS - 1, browse._cache[1])  # süresi dolmuş

    def broken(connection):
        raise psycopg.OperationalError("bağlantı koptu")

    monkeypatch.setattr(browse, "load_laws", broken)
    assert asyncio.run(legal.list_laws(q="", kind=None, limit=5, offset=0))["total"] >= 1  # eski liste sunulur


def test_a_bare_law_number_matches_only_that_law():
    laws = [law("4857", "İŞ KANUNU"), law("34857", "İTHALATTA HAKSIZ REKABET TEBLİĞİ", "communique")]
    assert [item.law_no for item in browse.search_laws(laws, "4857", None)] == ["4857"]
    assert [item.law_no for item in browse.search_laws(laws, "4857 ", "communique")] == ["34857"]  # tür süzgeci o kanunu dışarıda bırakırsa içerenler aranır


def test_an_expired_list_is_served_immediately_and_refreshed_in_the_background(monkeypatch):
    """Mevzuat sayfası her saat başı ~20 sn bekletiyordu: süresi dolan liste hemen döner, yenisi arka planda çıkarılır."""
    import threading
    import time

    browse.reset_cache()
    old, new = [object()], [object(), object()]
    started, release = threading.Event(), threading.Event()

    def slow_loader():
        started.set()
        release.wait(5)
        return new

    assert browse.cached_laws(lambda: old) is old  # ilk çağrı listeyi çıkarır
    monkeypatch.setattr(browse, "LAWS_TTL_SECONDS", 0.0)  # liste artık "süresi dolmuş"
    assert browse.cached_laws(slow_loader) is old  # beklemeden eski liste
    assert started.wait(5)
    assert browse.cached_laws(slow_loader) is old  # yenileme sürerken ikinci yenileme başlatılmaz, yine eski liste
    release.set()
    for _ in range(100):
        if browse._cache[1] is new:
            break
        time.sleep(0.02)
    monkeypatch.setattr(browse, "LAWS_TTL_SECONDS", 3600.0)
    assert browse.cached_laws(slow_loader) is new
    browse.reset_cache()


def test_a_failed_background_refresh_keeps_the_old_list(monkeypatch):
    import time

    browse.reset_cache()
    old = [object()]

    def failing():
        raise RuntimeError("veritabanı yok")

    assert browse.cached_laws(lambda: old) is old
    monkeypatch.setattr(browse, "LAWS_TTL_SECONDS", 0.0)
    assert browse.cached_laws(failing) is old
    for _ in range(100):
        if not browse._refreshing:
            break
        time.sleep(0.02)
    assert browse.cached_laws(lambda: old) is old
    browse.reset_cache()


def test_laws_list_survives_a_restart_through_the_disk_copy(tmp_path):
    """Bellek boşken (yeniden başlatma) diskteki liste hemen kullanılır; çıkarıcı (yavaş sorgu) beklenmez."""
    import api.legislation_browse as browse

    path = tmp_path / "laws.json"
    law = browse.Law("6098", "TÜRK BORÇLAR KANUNU", "law", 649, "2024-01-01", None, browse.fold("TÜRK BORÇLAR KANUNU 6098"))
    browse.reset_cache()
    first = browse.cached_laws(lambda: [law], path)
    assert [item.law_no for item in first] == ["6098"] and path.exists()
    browse.reset_cache()  # sunucu yeniden başladı
    calls = []

    def slow_loader():
        calls.append(1)
        return [law]

    second = browse.cached_laws(slow_loader, path)
    assert [item.law_no for item in second] == ["6098"]
    assert second[0].folded == law.folded
    import time

    deadline = time.time() + 5
    while not calls and time.time() < deadline:  # eski sayılan liste arka planda tazelenir
        time.sleep(0.05)
    assert calls, "diskten gelen liste arka planda yenilenmeli"
    browse.reset_cache()


def test_the_unfiltered_list_opens_with_constitution_then_laws_before_bigger_regulations():
    crowded = LAWS + [
        law("2709", "TÜRKİYE CUMHURİYETİ ANAYASASI", "constitution", 177),
        law("700", "BİR KANUN HÜKMÜNDE KARARNAME", "decree", 900),
        law("315481", "GIDA YÖNETMELİĞİ", "regulation", 721),
    ]
    order = [item.law_no for item in browse.search_laws(crowded, "", None)]
    assert order[:2] == ["2709", "6098"]  # Anayasa, sonra en çok maddeli kanun
    assert order.index("1475") < order.index("700") < order.index("315481") < order.index("20147052")

