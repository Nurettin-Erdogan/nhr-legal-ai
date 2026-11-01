"""Asistan aramasında tam sıralı sürüme kısa ilk süre: yetişmeyen sorgu 8 sn boşa beklemez (ağ/DB gerektirmez).

Ölçüldü (2026-10-08): altı olağan sorunun üçünde tam sıralı arama 8 sn'lik bütçeyi doldurup zaman aşımına uğruyor,
ardından katmanlı sürüm <1 sn'de cevap veriyordu. Yetişen sorgular 0,2-1,1 sn'de bitiyor.
"""

from __future__ import annotations

from dataclasses import replace

import psycopg
import pytest

from api.ai import retrieval
from tests.factories import court_decision_context

QUESTION = "Haksız fiilde manevi tazminat şartları nelerdir?"  # konu niyeti olmayan olağan soru: geniş arama kolu


@pytest.mark.parametrize(
    "budget,expected",
    [("8s", "2500ms"), ("5200ms", "2500ms"), ("900ms", "900ms"), ("2s", "2000ms"), ("1.5s", "1500ms"), ("bozuk", "bozuk")],
)
def test_a_budget_is_clipped_to_the_limit_and_never_extended(budget, expected):
    assert retrieval._capped_budget(budget, 2500) == expected


def _patched(monkeypatch, behaviour):
    calls: list[tuple[str, str]] = []

    def execute(connection, sql, params, *, timeout="15s"):
        kind = "tiered" if "_tiered(" in sql else "full" if "legal_rag_current_lexical_hits(" in sql else "other"
        calls.append((kind, timeout))
        return behaviour(sql)

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    return calls


def test_the_full_ranking_gets_a_short_first_budget_and_the_tiered_retry_the_long_one(monkeypatch):
    context = court_decision_context()

    def behaviour(sql):
        if "_tiered(" not in sql:
            raise psycopg.errors.QueryCanceled("statement timeout")
        return [context]

    context = replace(context, content="Haksız fiilde manevi tazminat şartları olayın özelliğine göre değerlendirilir.")
    calls = _patched(monkeypatch, behaviour)
    diagnostics: dict = {}

    result = retrieval.retrieve_contexts(None, question=QUESTION, top_k=5, diagnostics=diagnostics)

    full = [timeout for kind, timeout in calls if kind == "full"]
    tiered = [timeout for kind, timeout in calls if kind == "tiered"]
    assert full and all(timeout == f"{retrieval._FULL_RANKING_FIRST_BUDGET_MS}ms" for timeout in full)
    assert tiered == [retrieval._TIERED_RETRY_TIMEOUT]
    assert result and diagnostics["partial"] is True  # örneklenmiş sonuç açıkça bildirilir


def test_a_search_that_finishes_in_time_is_complete_and_not_marked_partial(monkeypatch):
    calls = _patched(monkeypatch, lambda sql: [court_decision_context()])
    diagnostics: dict = {}

    retrieval.retrieve_contexts(None, question=QUESTION, top_k=5, diagnostics=diagnostics)

    assert not [kind for kind, _ in calls if kind == "tiered"]
    assert diagnostics["partial"] is False


def test_the_statute_linked_focused_search_keeps_its_measured_shared_budget(monkeypatch):
    calls = _patched(monkeypatch, lambda sql: [])

    retrieval.retrieve_contexts(None, question="İcra takibinde itirazın iptali davası süresi nedir?", top_k=5, diagnostics={})

    assert ("full", "8s") in calls


def test_branches_without_a_tiered_variant_keep_their_own_budget(monkeypatch):
    calls = _patched(monkeypatch, lambda sql: [])

    retrieval.retrieve_contexts(None, question="4857 sayılı Kanun madde 18 neyi düzenler?", top_k=5, diagnostics={})

    assert calls == [("other", "3s")]  # açık madde sorusu: yalnız madde okunur, süresi kırpılmaz


def test_when_the_sampled_search_also_times_out_the_verified_tier_alone_still_answers(monkeypatch):
    # Yoğun diskte toplu katmanın dizini okunamıyor (ölçüldü: 2026-10-10); resmî katman tek başına hızlıdır.
    context = replace(court_decision_context(), content="Haksız fiilde manevi tazminat şartları olayın özelliğine göre değerlendirilir.")
    seen: list[tuple[str, str]] = []

    def execute(connection, sql, params, *, timeout="15s"):
        compact = sql.replace("\n", "").replace(" ", "")
        kind = "official" if "_tiered(" in sql and f",0,{retrieval._OFFICIAL_ONLY_CAP})" in compact else "tiered" if "_tiered(" in sql else "full"
        seen.append((kind, timeout))
        if kind != "official":
            raise psycopg.errors.QueryCanceled("statement timeout")
        return [context]

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    diagnostics: dict = {}

    result = retrieval.retrieve_contexts(None, question=QUESTION, top_k=5, diagnostics=diagnostics)

    assert [kind for kind, _ in seen] == ["full", "tiered", "official"]
    assert seen[1][1] == retrieval._TIERED_RETRY_TIMEOUT and seen[2][1] == retrieval._OFFICIAL_ONLY_TIMEOUT
    assert result and diagnostics["partial"] is True
    assert "timeout_then_official" in [branch["status"] for branch in diagnostics["branches"]]


def test_the_official_only_variant_scans_no_unverified_tier():
    official_only = retrieval._tiered_variant(retrieval.LEXICAL_RETRIEVAL_SQL, seed_cap=0)

    assert "legal_rag_current_lexical_hits_tiered(" in official_only
    assert official_only.replace("\n", "").replace(" ", "").count(",0)") == 1  # toplu katman sınırı 0: hiç taranmaz
    assert retrieval._VERIFIED_SOURCE_FILTER in official_only  # uygunluk süzgeci aynen kalır
    smaller = retrieval._tiered_variant(retrieval.LEXICAL_RETRIEVAL_SQL, seed_cap=0, official_cap=1500)
    assert ",0,1500)" in smaller.replace("\n", "").replace(" ", "")  # yük altında resmî katmandan da daha küçük örnek
