"""Doğrulanmamış toplu katman sigortası: katman art arda zaman aşımına uğrarsa bir süre denenmez (ağ/DB gerektirmez).

Ölçüldü (2026-10-10): arkada yoğun veri işi çalışırken toplu katmanın 31 GB'lık dizini bellekte kalamıyor; her arama o katmanı
bekleyip zaman aşımına düşüyor, sonra resmî katmanla dönüyordu (on iki aramanın on biri; ortanca 5,6 sn, 4 sn'si boşa bekleme).
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

import psycopg
from psycopg.errors import QueryCanceled

from api import legal
from api.ai import retrieval
from api.ai.seed_tier import TierBreaker, seed_tier
from tests.factories import court_decision_context

QUESTION = "Haksız fiilde manevi tazminat şartları nelerdir?"  # konu niyeti olmayan olağan soru: geniş arama kolu
CONTEXT = replace(court_decision_context(), content="Haksız fiilde manevi tazminat şartları olayın özelliğine göre değerlendirilir.")


def test_the_breaker_opens_after_consecutive_timeouts_and_a_success_resets_the_count():
    breaker = TierBreaker(threshold=3, cooldown=120, clock=lambda: 0.0)

    breaker.record(False)
    breaker.record(False)
    assert breaker.allow() is True  # iki zaman aşımı yetmez
    breaker.record(True)
    breaker.record(False)
    breaker.record(False)
    assert breaker.allow() is True  # araya giren başarı sayacı sıfırlar
    breaker.record(False)
    assert breaker.allow() is False and breaker.is_open is True


def test_after_the_cooldown_one_probe_decides_whether_it_closes_or_reopens():
    now = [0.0]
    breaker = TierBreaker(threshold=2, cooldown=60, clock=lambda: now[0])
    breaker.record(False)
    breaker.record(False)
    assert breaker.allow() is False

    now[0] = 59.0
    assert breaker.allow() is False
    now[0] = 61.0
    assert breaker.allow() is True  # süre doldu: bir kez denenir
    breaker.record(False)  # yine yetişmedi: yeniden açılır, süre baştan sayılır
    assert breaker.allow() is False
    now[0] = 122.0
    assert breaker.allow() is True
    breaker.record(True)  # yetişti: sigorta kapanır
    now[0] = 123.0
    assert breaker.allow() is True and breaker.is_open is False


def _kind(sql: str) -> str:
    compact = sql.replace("\n", "").replace(" ", "")
    if "_tiered(" not in sql:
        return "full" if "legal_rag_current_lexical_hits(" in sql else "other"
    return "official" if f",0,{retrieval._OFFICIAL_ONLY_CAP})" in compact else "tiered"


def _patched(monkeypatch, behaviour):
    calls: list[str] = []

    def execute(connection, sql, params, *, timeout="15s"):
        calls.append(_kind(sql))
        return behaviour(_kind(sql))

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    return calls


def _timeout(*kinds):
    def behaviour(kind):
        if kind in kinds:
            raise psycopg.errors.QueryCanceled("statement timeout")
        return [CONTEXT]

    return behaviour


def test_while_the_breaker_is_open_the_assistant_goes_straight_to_the_verified_tier(monkeypatch):
    for _ in range(seed_tier.threshold):
        seed_tier.record(False)
    calls = _patched(monkeypatch, _timeout())
    diagnostics: dict = {}

    result = retrieval.retrieve_contexts(None, question=QUESTION, top_k=5, diagnostics=diagnostics)

    assert calls == ["official"]  # ne tam sıralı sürüm ne toplu katman denenir
    assert result and diagnostics["partial"] is True  # toplu katman taranmadı: açıkça "kısmi"
    assert [branch["status"] for branch in diagnostics["branches"]] == ["official_only"]


def test_repeated_timeouts_of_the_sampled_search_open_the_breaker(monkeypatch):
    calls = _patched(monkeypatch, _timeout("full", "tiered"))

    for _ in range(seed_tier.threshold):
        assert seed_tier.allow() is True
        retrieval.retrieve_contexts(None, question=QUESTION, top_k=5, diagnostics={})

    assert calls[:3] == ["full", "tiered", "official"]
    assert seed_tier.allow() is False
    calls.clear()
    retrieval.retrieve_contexts(None, question=QUESTION, top_k=5, diagnostics={})
    assert calls == ["official"]


def test_a_slow_full_ranking_alone_does_not_open_the_breaker(monkeypatch):
    # Tam sıralı sürüm olağan koşulda da sık sık yetişmez (bütün eşleşmeleri puanlar); sigorta yalnız SINIRLI toplu katman
    # taramasının yetişmemesine bakar.
    _patched(monkeypatch, _timeout("full"))

    for _ in range(seed_tier.threshold + 2):
        retrieval.retrieve_contexts(None, question=QUESTION, top_k=5, diagnostics={})

    assert seed_tier.allow() is True


def test_branches_without_tiers_never_touch_the_breaker(monkeypatch):
    _patched(monkeypatch, _timeout("other"))

    for _ in range(seed_tier.threshold + 1):
        try:
            retrieval.retrieve_contexts(None, question="4857 sayılı Kanun madde 18 neyi düzenler?", top_k=5, diagnostics={})
        except psycopg.errors.QueryCanceled:
            pass

    assert seed_tier.allow() is True


class _SearchConnection:
    def __init__(self, attempts, fail):
        self.attempts, self.fail = attempts, fail

    def execute(self, statement, params=None):
        if isinstance(params, dict) and "query" in params:
            self.attempts.append({key: params[key] for key in ("seed_cap", "official_cap")})
            if self.fail(self.attempts[-1]):
                raise QueryCanceled("canceling statement due to statement timeout")
        return self

    def fetchall(self):
        return []


def _search(monkeypatch, query, fail):
    attempts: list[dict] = []

    @contextmanager
    def database_connection():
        yield _SearchConnection(attempts, fail)

    monkeypatch.setattr(legal, "database_connection", database_connection)
    legal._search_cache.clear()
    try:
        legal.search_legal_sources(q=query, limit=5, offset=0, as_of=None)
    finally:
        legal._search_cache.clear()
    return attempts


def test_search_skips_the_unverified_tier_while_the_breaker_is_open_and_tries_it_again_afterwards(monkeypatch):
    seeds_time_out = lambda attempt: attempt["seed_cap"] > 0  # noqa: E731

    for number in range(seed_tier.threshold):
        attempts = _search(monkeypatch, f"sigorta denemesi {number}", seeds_time_out)
        assert attempts[0]["seed_cap"] == legal._SEARCH_SEED_CAP  # kapalıyken toplu katman denenir
        assert attempts[1] == {"seed_cap": 0, "official_cap": legal._SEARCH_FALLBACK_OFFICIAL_CAP}
    assert seed_tier.allow() is False

    attempts = _search(monkeypatch, "sigorta açıkken arama", seeds_time_out)
    # İlk deneme doğrudan küçük resmî örnektir; sonuç boş olduğu için ardından gelen geniş (VEYA) yedek ayrı bir sorgudur.
    assert attempts[0] == {"seed_cap": 0, "official_cap": legal._SEARCH_FALLBACK_OFFICIAL_CAP}

    seed_tier.reset()
    attempts = _search(monkeypatch, "sigorta kapandıktan sonra", lambda attempt: False)
    assert attempts[0]["seed_cap"] == legal._SEARCH_SEED_CAP and seed_tier.allow() is True


# --- Resmî sonuç azsa doğrulanmamış katman beklenir ----------------------------------------------------------------------

from uuid import UUID  # noqa: E402


def _row(number: int, total: int) -> dict:
    return {
        "id": UUID(int=number), "source_type": "court_decision", "title": f"Karar {number}", "source_url": None, "authority": "Yargıtay",
        "court_name": "Yargıtay", "chamber": None, "docket_no": None, "decision_no": None, "decision_date": None, "legislation_type": None,
        "law_name": None, "law_no": None, "article_no": None, "article_title": None, "official_gazette_date": None, "version_date": None,
        "effective_from": None, "effective_to": None, "source_version": None, "revision": 1, "excerpt": "metin", "rank": 0.5,
        "seed_pending": False, "total": total, "partial": True,
    }


class _RowsConnection:
    """Resmî katman `official` kadar, iki katman birlikte `both` kadar sonuç verir; toplu katman `seed_fails` kez yetişmez."""

    def __init__(self, attempts, official, both, seed_fails):
        self.attempts, self.official, self.both, self.seed_fails = attempts, official, both, seed_fails
        self.rows: list[dict] = []

    def execute(self, statement, params=None):
        self.rows = []
        if isinstance(params, dict) and "query" in params:
            with_seeds = params["seed_cap"] > 0
            self.attempts.append("iki katman" if with_seeds else "resmî")
            if with_seeds and self.seed_fails[0] > 0:
                self.seed_fails[0] -= 1
                raise QueryCanceled("canceling statement due to statement timeout")
            count = self.both if with_seeds else self.official
            self.rows = [_row(n, count) for n in range(1, min(count, params["limit"]) + 1)]
        return self

    def fetchall(self):
        return self.rows


def _search_rows(monkeypatch, query, *, official, both, seed_fails, limit=5):
    attempts: list[str] = []
    failures = [seed_fails]

    @contextmanager
    def database_connection():
        yield _RowsConnection(attempts, official, both, failures)

    monkeypatch.setattr(legal, "database_connection", database_connection)
    monkeypatch.setattr(legal, "_verification_labels", lambda ids: {})
    monkeypatch.setattr(legal, "_explicit_article_hit", lambda query: None)
    legal._search_cache.clear()
    try:
        response = legal.search_legal_sources(q=query, limit=limit, offset=0, as_of=None)
    finally:
        legal._search_cache.clear()
    return attempts, response


def test_a_nearly_empty_verified_page_waits_for_the_unverified_tier(monkeypatch):
    # Katmanlı arama ilk denemede yetişmedi; resmî katmanda yalnız 2 sonuç var: liste boş kalmasın diye toplu katman
    # daha uzun süreyle bir kez daha denenir ve yetişince iki katmanın sonucu döner.
    attempts, response = _search_rows(monkeypatch, "az sonuçlu arama", official=2, both=40, seed_fails=1)

    assert attempts == ["iki katman", "resmî", "iki katman"]
    assert response.total == 40 and len(response.results) == 5


def test_a_full_verified_page_does_not_wait(monkeypatch):
    attempts, response = _search_rows(monkeypatch, "çok sonuçlu arama", official=30, both=60, seed_fails=1)

    assert attempts == ["iki katman", "resmî"]  # sayfa resmî sonuçla doldu: toplu katman ikinci kez beklenmez
    assert response.total == 30 and response.partial is True


def test_when_the_unverified_tier_still_does_not_finish_the_few_verified_results_are_returned(monkeypatch):
    attempts, response = _search_rows(monkeypatch, "az sonuçlu, yük altında", official=2, both=40, seed_fails=2)

    assert attempts == ["iki katman", "resmî", "iki katman"]
    assert response.total == 2 and response.partial is True  # eldeki resmî sonuç kaybolmaz


def test_with_the_breaker_open_a_sparse_search_still_gets_one_longer_try(monkeypatch):
    for _ in range(seed_tier.threshold):
        seed_tier.record(False)

    attempts, response = _search_rows(monkeypatch, "sigorta açık, az sonuç", official=1, both=25, seed_fails=0)

    assert attempts == ["resmî", "iki katman"]
    assert response.total == 25 and seed_tier.allow() is True  # toplu katman yetişti: sigorta kapanır
