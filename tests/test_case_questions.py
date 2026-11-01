"""Dava kapsamlı sohbet: kendi dosyasına dair olgu soruları başka davaların kararlarından cevaplanmaz."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4

import pytest

from api.ai import pipeline
from api.ai.case_questions import is_case_file_question
from api.schemas import AIAnswerRequest
from tests.factories import court_decision_context, legislation_context

FILE_QUESTIONS = [
    "Bilirkişi kıdem tazminatını ne kadar hesaplamış?",
    "Davalının adresi nedir?",
    "Davacı kaç yıl çalışmış?",
    "Dilekçede ne talep edilmiş?",
    "Mahkeme ne karar vermiş?",
    "davacinin vekili kimdir",
    "bilirkisi raporunda hangi tutarlar hesaplanmis",
    "İhtarnamede ne kadar süre verilmiş?",
    "Sözleşmede cezai şart var mı?",
    "Kiracının telefon numarası nedir?",
    "Kiraya verenin IBAN'ı nedir?",
]
LAW_OR_MIXED_QUESTIONS = [
    "Kıdem tazminatı şartları nelerdir?",
    "TBK 344. madde kira artış oranı nedir?",
    "Davacı kıdem tazminatına hak kazanır mı?",
    "Davalının sorumluluğu Yargıtay içtihadına göre nasıl değerlendirilir?",
    "Haksız fesihte ihbar süresi kaç hafta?",
    "İhbar tazminatı zamanaşımı ne kadar?",
    "Bu dosyada zamanaşımı itirazı yerinde mi?",
    "İhtarnamede verilen süre kanuna uygun mu?",
    "İhtarname süresi kaç gün olmalı?",
    "Kiracı tahliye edilebilir mi?",
    "Sözleşmedeki cezai şart geçersiz sayılır mı?",
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
    # Konuya göre madde ekleme ayrı sınanır (aşağıda); burada veritabanına gitmesin.
    monkeypatch.setattr(pipeline, "_case_statute_contexts", lambda *a, **k: [])
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


CONTRACT = "Kira başlangıç tarihi 01.03.2024, süre 1 yıldır. Depozito 37.000 TL'dir."


def _with_contract(monkeypatch):
    monkeypatch.setattr(
        pipeline, "retrieve_document_contexts",
        lambda *a, **k: [replace(_context("user_document", 0.2, "kira sözleşmesi"), source_type="document", content=CONTRACT)],
    )


def test_a_fact_whose_answer_is_in_the_case_documents_is_answered_from_them_alone(fake_retrieval, monkeypatch):
    # "Dosya" sözcüğü taşımayan olgu sorusu: karışık aramada model başka bir davanın kararındaki tutarı seçebiliyordu.
    _with_contract(monkeypatch)

    result, diagnostics = _retrieve("Depozito tutarı nedir?")

    assert "legal" not in fake_retrieval
    assert [c.verification for c in result] == ["user_document"]
    assert diagnostics["case_file_only"] is True


def test_a_fact_the_documents_do_not_mention_still_searches_legal_sources(fake_retrieval, monkeypatch):
    _with_contract(monkeypatch)

    result, diagnostics = _retrieve("Arabuluculuk başvuru süresi kaç gün?")

    assert "legal" in fake_retrieval
    assert [c.verification for c in result] == ["user_document", "official", "third_party"]
    assert diagnostics["case_file_only"] is False


@pytest.mark.parametrize("question", [
    "Depozito iadesi için dava açabilir miyiz?",
    "Depozito kesintisi hukuka uygun mu?",
    "Depozito için TBK madde 342 ne diyor?",
    "Depozito iade edilmezse risklerimiz neler?",
])
def test_a_question_asking_for_legal_assessment_is_never_document_only(fake_retrieval, monkeypatch, question):
    # Belgede konu geçse bile değerlendirme belgede yazmaz: hukuk kaynakları da aranır.
    _with_contract(monkeypatch)

    result, diagnostics = _retrieve(question)

    assert "legal" in fake_retrieval and diagnostics["case_file_only"] is False


def test_document_only_decision_is_reported_with_the_document_scope(fake_retrieval, monkeypatch):
    _with_contract(monkeypatch)
    monkeypatch.setattr(pipeline, "case_document_coverage", lambda *a, **k: {"total": 1, "ready": 1})

    _, diagnostics = _retrieve("Depozito tutarı nedir?")
    assert diagnostics["document_scope"] == {"total": 1, "ready": 1, "file_only": True}

    _, diagnostics = _retrieve("Depozito iadesi için dava açabilir miyiz?")
    assert diagnostics["document_scope"]["file_only"] is False


def _two_documents(monkeypatch):
    notice = replace(_context("user_document", 0.3, "ihtarname.txt"), source_type="document",
                     content="İHTARNAME\nKonu: Kira borcunun 30 gün içinde ödenmesi ihtarıdır.\nTarih: 10.04.2025")
    contract = replace(_context("user_document", 0.2, "kira-sozlesmesi.docx"), source_type="document", content=CONTRACT)
    monkeypatch.setattr(pipeline, "retrieve_document_contexts", lambda *a, **k: [contract, notice])


def test_a_question_naming_a_document_reads_only_that_document(fake_retrieval, monkeypatch):
    # "İhtarnamede 10 gün süre verilmiş" diyen başka bir davanın kararı cevap diye seçilebiliyordu (ölçüldü: 2026-10-06).
    _two_documents(monkeypatch)

    result, diagnostics = _retrieve("İhtarnamede ne kadar süre verilmiş?")

    assert "legal" not in fake_retrieval
    assert [c.title for c in result] == ["ihtarname.txt"]
    assert diagnostics["case_file_only"] is True


def _legal_mix(monkeypatch):
    statute = replace(legislation_context(), title="kanun maddesi")
    decision = _context("official", 9.5, "başka davanın kararı")
    monkeypatch.setattr(pipeline, "retrieve_contexts", lambda *a, **k: [decision, statute])


def test_a_legal_question_about_the_users_own_document_uses_statutes_but_not_other_cases_decisions(fake_retrieval, monkeypatch):
    # Başka bir davanın kararındaki "ihtarnamede 30 günlük süre verilmiş olması nedeniyle…" cümlesi kullanıcının
    # ihtarnamesi hakkında söylenmiş gibi okunuyordu (ölçüldü: 2026-10-06).
    _two_documents(monkeypatch)
    _legal_mix(monkeypatch)

    result, diagnostics = _retrieve("İhtarnamede verilen süre kanuna uygun mu?")

    assert diagnostics["case_file_only"] is False
    assert [c.title for c in result] == ["ihtarname.txt", "kanun maddesi"]


def test_decisions_stay_when_the_user_asks_for_case_law_or_names_no_document(fake_retrieval, monkeypatch):
    _two_documents(monkeypatch)
    _legal_mix(monkeypatch)

    asked_for_case_law, _ = _retrieve("İhtarnamede verilen süre Yargıtay kararlarına göre uygun mu?")
    assert "başka davanın kararı" in [c.title for c in asked_for_case_law]

    general, _ = _retrieve("Kiracı tahliye edilebilir mi?")
    assert "başka davanın kararı" in [c.title for c in general]


# --- Karışık arama: belgeler hukuk kaynaklarını dışarıda bırakmaz; konuya uyan resmî madde öne gelir -----------------------


def test_documents_and_legal_sources_alternate_so_neither_crowds_out_the_other():
    a, b, c = (_context("user_document", 0.1, name) for name in "abc")
    x, y = (_context("official", 0.1, name) for name in "xy")
    assert [item.title for item in pipeline._interleave([a, b, c], [x, y])] == ["a", "x", "b", "y", "c"]
    assert pipeline._interleave([], [x]) == [x] and pipeline._interleave([a], []) == [a]


def test_many_case_documents_no_longer_push_every_legal_source_out(fake_retrieval, monkeypatch):
    many = [replace(_context("user_document", 1.0 - i / 10, f"belge {i}"), source_type="document", content="Kıdem tazminatı talep edilmiştir.") for i in range(5)]
    monkeypatch.setattr(pipeline, "retrieve_document_contexts", lambda *a, **k: many)

    result, _ = _retrieve("Davacı kıdem tazminatına hak kazanır mı?")  # top_k = 5

    assert [c.title for c in result] == ["belge 0", "kanun", "belge 1", "başka dava", "belge 2"]


def test_topic_statutes_come_right_after_the_first_document_in_a_legal_case_question(fake_retrieval, monkeypatch):
    _two_documents(monkeypatch)
    statute = replace(legislation_context(content="Kiracıya verilecek süre en az on gün, konut kiralarında en az otuz gündür."), title="TBK m. 315")
    seen = {}

    def statutes(connection, question, named):
        seen["named"] = [c.title for c in named]
        return [statute]

    monkeypatch.setattr(pipeline, "_case_statute_contexts", statutes)

    result, _ = _retrieve("İhtarnamede verilen süre kanuna uygun mu?")

    assert seen["named"] == ["ihtarname.txt"]
    # Konuya uyan madde hukuk kaynaklarının başındadır; başka davaların kararları bu soruda yer almaz.
    assert [c.title for c in result] == ["ihtarname.txt", "TBK m. 315"]


class _StatuteConnection:
    @contextmanager
    def transaction(self):
        yield


def _statute_rows(monkeypatch, rows_by_article):
    from api.ai import retrieval

    asked = []

    def fake(connection, sql, params, *, timeout):
        asked.append((params["law_no"], params["article_no"]))
        return rows_by_article.get((params["law_no"], params["article_no"]), [])

    monkeypatch.setattr(retrieval, "_execute_retrieval", fake)
    return asked


def _article(law_no, article_no, content, verification="official"):
    return replace(legislation_context(content=content), law_no=law_no, article_no=article_no, verification=verification,
                   title=f"{law_no} m. {article_no}")


TBK_315 = "Kiracı, kira bedelini ödeme borcunu ifa etmezse kiraya veren yazılı olarak süre verip sözleşmeyi feshedeceğini bildirebilir."
TBK_352 = "Kiracı, bir kira yılı içinde iki haklı ihtara sebep olmuşsa kiraya veren tahliye davası açabilir."


def test_case_statutes_follow_the_topic_of_the_question(monkeypatch):
    asked = _statute_rows(monkeypatch, {("6098", "315"): [_article("6098", "315", TBK_315)], ("6098", "352"): [_article("6098", "352", TBK_352)]})

    found = pipeline._case_statute_contexts(_StatuteConnection(), "Kiracı kirayı ödemiyor, tahliye edilebilir mi?", [])

    assert asked == [("6098", "315"), ("6098", "352")]
    assert [(c.law_no, c.article_no) for c in found] == [("6098", "315"), ("6098", "352")]


def test_case_statutes_fall_back_to_the_named_document_but_never_to_the_whole_file(monkeypatch):
    asked = _statute_rows(monkeypatch, {("6098", "315"): [_article("6098", "315", TBK_315)]})
    notice = replace(_context("user_document", 0.3, "ihtarname.txt"), source_type="document",
                     content="İHTARNAME\nKonu: Kira borcunun 30 gün içinde ödenmesi, aksi halde tahliye davası açılacağı ihtarıdır.")
    question = "İhtarnamede verilen süre kanuna uygun mu?"

    assert pipeline._case_statute_contexts(_StatuteConnection(), question, []) == [] and asked == []
    found = pipeline._case_statute_contexts(_StatuteConnection(), question, [notice])
    assert [(c.law_no, c.article_no) for c in found] == [("6098", "315")]


def test_a_statute_whose_text_does_not_carry_the_expected_topic_or_is_unverified_is_not_added(monkeypatch):
    question = "Kiracı kirayı ödemiyor, tahliye edilebilir mi?"
    _statute_rows(monkeypatch, {("6098", "315"): [_article("6098", "315", "Bu madde bambaşka bir konuyu düzenler.")],
                                ("6098", "352"): [_article("6098", "352", TBK_352, verification="third_party")]})

    assert pipeline._case_statute_contexts(_StatuteConnection(), question, []) == []


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


# --- Genel sohbet: konuya uyan resmî madde adayların başında ------------------------------------------------------------


def _general(monkeypatch, question, *, as_of=None, statutes=()):
    decision = _context("official", 9.0, "eski karar")
    calls = []
    monkeypatch.setattr(pipeline, "database_connection", lambda: _plain())
    monkeypatch.setattr(pipeline, "retrieve_contexts", lambda *a, **k: [decision, *statutes[:1]])

    def topic(connection, text, named):
        calls.append((text, named))
        return list(statutes)

    monkeypatch.setattr(pipeline, "_case_statute_contexts", topic)
    diagnostics: dict = {}
    result = pipeline._retrieve(
        AIAnswerRequest(question=question, as_of=as_of), user_id=None, query_embedding=None, top_k=5,
        embedding_model="m", diagnostics=diagnostics,
    )
    return result, calls, diagnostics


def test_a_general_question_gets_its_topic_statute_ahead_of_old_decisions(monkeypatch):
    # "İşe iade davası açma süresi" yalnız 2015-2016 kararlarıyla cevaplanıyordu; güncel kural kanun maddesindedir.
    statute = replace(legislation_context(content="İşçi bir ay içinde arabulucuya başvurmak zorundadır."), title="İş Kanunu m. 20")

    result, calls, diagnostics = _general(monkeypatch, "İşe iade davası açma süresi nedir?", statutes=(statute,))

    assert calls == [("İşe iade davası açma süresi nedir?", [])]
    assert [c.title for c in result] == ["İş Kanunu m. 20", "eski karar"]  # aynı parça iki kez yer almaz
    assert diagnostics["topic_statutes"] == 1


def test_a_dated_question_reads_no_current_statute_and_no_topic_changes_nothing(monkeypatch):
    from datetime import date

    statute = replace(legislation_context(), title="güncel madde")
    result, calls, diagnostics = _general(monkeypatch, "İşe iade davası açma süresi nedir?", as_of=date(2016, 1, 1), statutes=(statute,))
    assert calls == [] and "topic_statutes" not in diagnostics
    assert [c.title for c in result] == ["eski karar", "güncel madde"]  # yalnız aramanın getirdiği sıra

    result, calls, diagnostics = _general(monkeypatch, "Fazla mesai ücreti nasıl ispatlanır?")
    assert [c.title for c in result] == ["eski karar"] and "topic_statutes" not in diagnostics
