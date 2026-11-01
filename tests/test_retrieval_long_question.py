"""Uzun soruda tüm sözcükleri birden arayan tam metin kolu atlanır (ağ/DB gerektirmez).

Ölçüldü (2026-10-30): 35 sözcüklü bir havale sorusunda "hepsi birden geçsin" sorgusu 0 satır döndürdü ama çok yaygın
sözcüklerin uzun listelerini okuyup 7,4 sn sürdü (tam sıralı 2,5 + katmanlı 4 + yalnız resmî 0,95) ve kullanıcıya
"aramanın bir bölümü zaman aşımına uğradı" uyarısını gösterdi. Aynı soruda karar vektörleri kolu zaten çalışıyordu.
Parçalara bölünmüş (planlayıcı) aramalar bu vektörü göndermez; karar bulmak için yalnız bu kola dayanırlar, atlanmaz.
"""

from __future__ import annotations

import pytest

from api.ai import retrieval
from api.ai.search_plan import SearchPlan
from tests.factories import court_decision_context

# plan_search sonrası 12'den çok sözcük kalan, konu niyeti ve madde numarası olmayan olay anlatımı
LONG_QUESTION = (
    "Bir kişi banka havalesiyle başka birine para gönderdi, dekontta yalnızca borç yazıyor, alıcı bunun eski bir borcun "
    "geri ödemesi olduğunu söylüyor, bu durumda karşı taraf hangi delillerle neyi ispatlamak zorundadır"
)
SHORT_QUESTION = "Haksız fiilde manevi tazminat şartları nelerdir?"
EMBEDDING = [0.01] * 768


def _record(monkeypatch, rows=()):
    calls: list[str] = []

    def execute(connection, sql, params, *, timeout="15s"):
        lexical = "legal_rag_current_lexical_hits(" in sql or "_tiered(" in sql
        calls.append("lexical" if lexical else "other")
        return list(rows) if lexical else []

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    return calls


def test_the_fixture_question_is_long_and_has_no_topic_or_article_shortcut():
    # Testin dayanağı: bu soru gerçekten "uzun" sayılıyor ve odaklı/maddeli yola girmiyor.
    assert len(retrieval.plan_search(LONG_QUESTION).text.split()) > retrieval._LONG_QUESTION_TERMS
    assert retrieval.question_intent(LONG_QUESTION) is None
    assert not retrieval.question_law_numbers(LONG_QUESTION)


def test_long_question_with_the_shared_decision_lane_skips_the_all_terms_lexical_lane(monkeypatch):
    calls = _record(monkeypatch)
    diagnostics: dict = {}

    retrieval.retrieve_contexts(None, question=LONG_QUESTION, top_k=5, query_embedding=EMBEDDING,
                                embedding_model="bge-m3", diagnostics=diagnostics)

    assert "lexical" not in calls
    assert diagnostics["lexical_strategy"] == "skipped_long_question"
    assert {"name": "lexical", "status": "skipped_long_question", "seconds": 0.0} in diagnostics["branches"]
    # Atlanan kol "zaman aşımı" değildir: kullanıcıya sahte uyarı gösterilmez.
    assert diagnostics["partial"] is False


def test_the_shared_decision_lane_still_runs_when_the_lexical_lane_is_skipped(monkeypatch):
    sql_seen: list[str] = []

    def execute(connection, sql, params, *, timeout="15s"):
        sql_seen.append(sql)
        return []

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    retrieval.retrieve_contexts(None, question=LONG_QUESTION, top_k=5, query_embedding=EMBEDDING,
                                embedding_model="bge-m3", diagnostics={})

    assert retrieval.SEMANTIC_RETRIEVAL_SQL in sql_seen  # kararlar anlam koluyla aranmaya devam eder


def test_a_part_search_without_the_shared_vector_keeps_its_lexical_lane_even_when_long(monkeypatch):
    # Planlayıcının parça aramaları ortak vektör göndermez; karar bulmak için bu kola dayanırlar.
    context = court_decision_context(content="Havale dekontunda borç yazması ispat yükünü değiştirmez.")
    calls = _record(monkeypatch, rows=[context])
    diagnostics: dict = {}

    retrieval.retrieve_contexts(None, question=LONG_QUESTION, top_k=5, diagnostics=diagnostics)

    assert "lexical" in calls
    assert diagnostics["lexical_strategy"] == "broad"


def test_a_short_question_with_the_shared_decision_lane_keeps_its_lexical_lane(monkeypatch):
    calls = _record(monkeypatch)
    diagnostics: dict = {}

    retrieval.retrieve_contexts(None, question=SHORT_QUESTION, top_k=5, query_embedding=EMBEDDING,
                                embedding_model="bge-m3", diagnostics=diagnostics)

    assert "lexical" in calls
    assert diagnostics["lexical_strategy"] == "broad"


@pytest.mark.parametrize("terms,skipped", [(retrieval._LONG_QUESTION_TERMS, False), (retrieval._LONG_QUESTION_TERMS + 1, True)])
def test_the_length_limit_counts_search_terms_not_raw_words(monkeypatch, terms, skipped):
    # Sınır sınırın kendisinde dahil değildir: tam 12 sözcük hâlâ aranır, 13. sözcükte atlanır.
    words = " ".join(f"ispat{chr(97 + i)}" for i in range(terms))
    monkeypatch.setattr(retrieval, "plan_search", lambda q: SearchPlan(text=words, phrase=""))
    calls = _record(monkeypatch)
    diagnostics: dict = {}

    retrieval.retrieve_contexts(None, question="ispat örneği", top_k=5, query_embedding=EMBEDDING,
                                embedding_model="bge-m3", diagnostics=diagnostics)

    assert ("lexical" not in calls) is skipped
