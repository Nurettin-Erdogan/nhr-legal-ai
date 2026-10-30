import pytest
from dataclasses import replace

from api.ai import retrieval
from api.ai.pipeline import _missing_requested_article
from tests.factories import legislation_context, court_decision_context


@pytest.mark.parametrize("articles", ["315", "315 ve 352"])
def test_explicit_article_with_case_law_does_not_stop_before_decision_search(monkeypatch, articles):
    provision = replace(legislation_context(), law_no="6098", article_no="315")
    decision = court_decision_context(content="Kira ihtarında sözleşmenin feshedileceğinin bildirilmesi gerekir.")
    seen = []
    def execute(conn, sql, params, *, timeout):
        seen.append(sql)
        return [provision] if sql == retrieval.STATUTE_RETRIEVAL_SQL else [decision]
    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    rows = retrieval.retrieve_contexts(None,
        question=f"6098 sayılı Kanun madde {articles} kira ihtarı için ilgili Yargıtay kararlarını göster", top_k=6)
    assert any(sql != retrieval.STATUTE_RETRIEVAL_SQL for sql in seen)
    assert any(c.source_type == "court_decision" for c in rows)


@pytest.mark.parametrize("law,article", [("4857", "100"), ("6098", "344"), ("6100", "107"), ("5237", "125")])
def test_three_digit_article_is_not_a_second_explicit_law(law, article, monkeypatch):
    question = f"{law} sayılı Kanun madde {article} neyi düzenler?"
    assert retrieval.question_law_numbers(question) == (law,)
    assert retrieval.question_article_numbers(question) == (article,)
    source = replace(legislation_context(), law_no=law, article_no=article)
    calls = []

    def execute(conn, sql, params, *, timeout):
        assert sql == retrieval.STATUTE_RETRIEVAL_SQL
        calls.append(params)
        return [source]

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    rows = retrieval.retrieve_contexts(None, question=question, top_k=6)
    assert len(calls) == 1
    assert calls[0]["law_no"] == law and calls[0]["article_no"] == article
    assert _missing_requested_article(question, rows) is None


def test_two_explicit_laws_remain_two_laws_without_the_article_or_an_incidental_year():
    q = "4857 ve 6098 sayılı kanunların 100. maddeleri 2023 yılında nasıldı?"
    assert retrieval.question_law_numbers(q) == ("4857", "6098")


def test_missing_article_still_does_not_become_a_fabricated_answer():
    q = "4857 sayılı İş Kanunu madde 999 neyi düzenler?"
    assert retrieval.question_law_numbers(q) == ("4857",)
    assert _missing_requested_article(q, []) == ("4857", "999")
