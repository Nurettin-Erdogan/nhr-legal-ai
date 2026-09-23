from __future__ import annotations

from api.ai import retrieval
from tests.factories import court_decision_context


def test_explicit_statute_question_does_not_fall_back_to_court_decisions(monkeypatch):
    calls: list[str] = []

    def execute(connection, sql, params):
        calls.append(sql)
        return [court_decision_context(content="Dava açma süresi kararda tartışılmıştır.")]

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    monkeypatch.setattr(
        retrieval,
        "_retrieve_statute_contexts",
        lambda *args, **kwargs: [],
    )

    result = retrieval.retrieve_contexts(
        object(),
        question="2577 sayılı Kanun madde 7 dava açma süresini nasıl düzenler?",
        top_k=2,
    )

    assert result == []
    assert len(calls) == 1, "broad court-decision fallback must not run"
