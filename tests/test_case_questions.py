"""Dava kapsamlı sohbet: kendi dosyasına dair olgu soruları başka davaların kararlarından cevaplanmaz."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4

import pytest

from api.ai import pipeline
from api.ai.case_questions import is_case_file_question
from api.schemas import AIAnswerRequest
from tests.factories import court_decision_context

FILE_QUESTIONS = [
    "Bilirkişi kıdem tazminatını ne kadar hesaplamış?",
    "Davalının adresi nedir?",
    "Davacı kaç yıl çalışmış?",
    "Dilekçede ne talep edilmiş?",
    "Mahkeme ne karar vermiş?",
    "davacinin vekili kimdir",
    "bilirkisi raporunda hangi tutarlar hesaplanmis",
]
LAW_OR_MIXED_QUESTIONS = [
    "Kıdem tazminatı şartları nelerdir?",
    "TBK 344. madde kira artış oranı nedir?",
    "Davacı kıdem tazminatına hak kazanır mı?",
    "Davalının sorumluluğu Yargıtay içtihadına göre nasıl değerlendirilir?",
    "Haksız fesihte ihbar süresi kaç hafta?",
    "İhbar tazminatı zamanaşımı ne kadar?",
    "Bu dosyada zamanaşımı itirazı yerinde mi?",
]


@pytest.mark.parametrize("question", FILE_QUESTIONS)
def test_questions_about_the_users_own_file_are_document_only(question):
    assert is_case_file_question(question) is True


@pytest.mark.parametrize("question", LAW_OR_MIXED_QUESTIONS)
def test_legal_or_mixed_questions_still_use_legal_sources(question):
    assert is_case_file_question(question) is False


def _context(verification: str, rank: float, label: str):
    return replace(court_decision_context(), verification=verification, rank=rank, title=label)


@pytest.fixture
def fake_retrieval(monkeypatch):
    calls: list[str] = []

    @contextmanager
    def connection(user_id):
        yield object()

    monkeypatch.setattr(pipeline, "authenticated_database_connection", connection)
    monkeypatch.setattr(pipeline, "sweep_unindexed", lambda *a, **k: 0)
    monkeypatch.setattr(pipeline, "case_document_coverage", lambda *a, **k: {})

    def legal(*args, **kwargs):
        calls.append("legal")
        return [_context("official", 9.0, "kanun"), _context("third_party", 8.0, "başka dava")]

    def documents(*args, **kwargs):
        calls.append("documents")
        return [_context("user_document", 0.2, "bilirkişi raporu")]

    monkeypatch.setattr(pipeline, "retrieve_contexts", legal)
    monkeypatch.setattr(pipeline, "retrieve_document_contexts", documents)
    return calls


def _retrieve(question):
    request = AIAnswerRequest(question=question, case_id=uuid4())
    diagnostics: dict = {}
    result = pipeline._retrieve(
        request, user_id=uuid4(), query_embedding=None, top_k=5,
        embedding_model="m", question=question, diagnostics=diagnostics,
    )
    return result, diagnostics


def test_a_file_question_never_searches_the_public_corpus(fake_retrieval):
    result, diagnostics = _retrieve("Davalının adresi nedir?")

    assert fake_retrieval == ["documents"]  # genel korpus hiç sorgulanmaz
    assert [c.verification for c in result] == ["user_document"]
    assert diagnostics["case_file_only"] is True


def test_a_mixed_question_puts_the_users_documents_first_and_keeps_legal_sources(fake_retrieval):
    result, diagnostics = _retrieve("Davacı kıdem tazminatına hak kazanır mı?")

    assert set(fake_retrieval) == {"legal", "documents"}
    # Puan ölçekleri farklı olsa da kullanıcının kendi belgesi önce gelir.
    assert [c.verification for c in result] == ["user_document", "official", "third_party"]
    assert diagnostics["case_file_only"] is False


def test_questions_without_a_case_are_untouched(monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "database_connection", lambda: _plain())
    monkeypatch.setattr(pipeline, "retrieve_contexts", lambda *a, **k: seen.append("legal") or [])
    request = AIAnswerRequest(question="Davalının adresi nedir?")

    pipeline._retrieve(request, user_id=None, query_embedding=None, top_k=5, embedding_model="m")

    assert seen == ["legal"]


@contextmanager
def _plain():
    yield object()
