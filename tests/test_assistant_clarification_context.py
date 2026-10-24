"""Targeted follow-up and multi-article retrieval regressions.

Synthetic only: no real corpus writes, networks, cloud models or workers.
"""
from dataclasses import replace
from uuid import UUID

from api.ai.authority import answer_uses_primary_basis
from api.ai.dialogue import resume_question
from api.ai.rag import HistoryTurn
from api.ai import retrieval
from tests.factories import legislation_context


REINSTATEMENT = (
    "İşveren beni geçerli bir neden göstermeden işten çıkardı. "
    "İşe iade davası açabilir miyim? Başvuru süresi ve şartları nelerdir?"
)


def statute(article, law="4857", part=0):
    return replace(
        legislation_context(),
        law_no=law, article_no=str(article),
        source_id=UUID(int=article + 10000),
        chunk_id=UUID(int=article * 100 + part),
        content=f"Sentetik kanun maddesi {article}, parça {part}.",
    )


def test_clarification_reply_preserves_all_parts_of_original_question():
    turns = [HistoryTurn(
        question=REINSTATEMENT,
        answer="Tebliğ size hangi tarihte ulaştı?",
        answer_kind="clarification",
    )]
    result = resume_question("dün", turns, (REINSTATEMENT,))
    assert result is not None
    assert REINSTATEMENT[:-1] in result
    assert result.endswith("— dün")
    assert "süresi ve şartları" in result


def test_second_clarification_recovers_original_substantive_question():
    turns = [HistoryTurn(
        question="dün",
        answer="İşyerinde kaç çalışan var?",
        answer_kind="clarification",
    )]
    result = resume_question(
        "35 kişi", turns, (REINSTATEMENT, "dün"),
    )
    assert result is not None
    assert "İşe iade davası" in result
    assert "süresi ve şartları" in result
    assert result.endswith("— 35 kişi")


def test_new_topic_is_not_forced_into_old_clarification():
    turns = [HistoryTurn(
        question=REINSTATEMENT,
        answer="Tebliğ size hangi tarihte ulaştı?",
        answer_kind="clarification",
    )]
    assert resume_question("Kira artışı nasıl belirlenir?", turns, (REINSTATEMENT,)) is None
    assert resume_question("Yeni bir konu: kira artışı", turns, (REINSTATEMENT,)) is None


def test_only_true_clarification_is_resumed():
    turns = [HistoryTurn(question=REINSTATEMENT, answer="Kural şöyledir.", answer_kind="legal")]
    assert resume_question("dün", turns, (REINSTATEMENT,)) is None


def test_explicit_two_articles_are_retrieved_with_independent_budgets(monkeypatch):
    a18 = [statute(18, part=i) for i in range(4)]
    a20 = [statute(20)]
    calls = []

    def execute(connection, sql, params, **kwargs):
        calls.append((sql, params))
        if sql == retrieval.STATUTE_RETRIEVAL_SQL:
            return {"18": a18, "20": a20}[params["article_no"]]
        return []

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    question = "4857 sayılı İş Kanunu m. 18 ve m. 20 hükümlerini açıklar mısın?"
    results = retrieval.retrieve_contexts(object(), question=question, top_k=4)

    # A single article's many chunks cannot hide the other requested article.
    assert [c.article_no for c in results] == ["18", "20", "18", "18"]
    assert len(calls) == 2
    assert {call[1]["article_no"] for call in calls} == {"18", "20"}


def test_both_available_articles_required_in_answer_citations():
    question = "4857 sayılı İş Kanunu m.18 ve m.20 hükümleri nedir?"
    a18, a20 = statute(18), statute(20)
    assert not answer_uses_primary_basis(question, [a18], [a18, a20])
    assert answer_uses_primary_basis(question, [a18, a20], [a18, a20])


def test_single_explicit_article_retains_original_direct_lookup(monkeypatch):
    calls = []

    def execute(connection, sql, params, **kwargs):
        calls.append((sql, params))
        return [statute(20)]

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    results = retrieval.retrieve_contexts(
        object(), question="4857 sayılı İş Kanunu m.20 nedir?", top_k=6,
    )
    assert len(calls) == 1 and results[0].article_no == "20"
