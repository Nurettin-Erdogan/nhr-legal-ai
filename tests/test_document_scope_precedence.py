"""Kullanıcının kendi belgesi, soru bir mevzuat niyetine benzese bile elenmemeli.

Ölçüldü (2026-10-02): "Bu kira sözleşmesinde aylık kira bedeli ne kadar ve ne zaman ödenir?"
sorusundaki "ne zaman" içindeki "zam", kira artışı niyetini (TBK m.344) tetikliyor ve proje
belgesi cevap kaynaklarından çıkarılıyordu; sonuç "yeterli bilgi yok" oluyordu.
"""

from dataclasses import replace

import pytest

from api.ai.authority import answer_uses_primary_basis, primary_legislation_markers
from api.ai.discovery import select_answer_contexts
from api.ai.evidence_selection import evidence_candidates, preserve_statutory_scope
from api.ai.relevance import question_intent
from api.ai.verification import verify_answer
from tests.factories import document_context, legislation_context

DOC_TEXT = "Aylık kira bedeli 25.000 TL'dir. Kira bedeli her ayın beşine kadar ödenir."
RENT_QUESTION = "Bu kira sözleşmesinde aylık kira bedeli ne kadar ve ne zaman ödenir?"
INCREASE_QUESTION = "Kira sözleşmesinde TÜFE üzerinde artış istenirse ne yapılır?"


def statute():
    return replace(
        legislation_context(content="Kira artışı bu sentetik örnekte tüketici fiyat endeksine bağlıdır."),
        law_no="6098",
        article_no="344",
    )


def user_document():
    return document_context(content=DOC_TEXT)


@pytest.mark.parametrize(
    "question",
    [
        RENT_QUESTION,
        "Kira bedeli ne zaman ödenir?",
        "Kira alacağında zamanaşımı süresi nedir?",
        "Kiracı zamanında ödeme yapmazsa ne olur?",
    ],
)
def test_zaman_is_not_a_rent_increase(question):
    assert question_intent(question) is None


@pytest.mark.parametrize(
    "question",
    [
        INCREASE_QUESTION,
        "Kiraya zam yapılabilir mi?",
        "Ev sahibi kira zammı isterse ne olur?",
        "Kira artırımı nasıl hesaplanır?",
    ],
)
def test_real_rent_increase_questions_still_match(question):
    intent = question_intent(question)
    assert intent is not None and intent.statute == ("6098", "344")


def test_user_document_survives_primary_statute_focus():
    pool = [user_document(), statute()]
    assert primary_legislation_markers(INCREASE_QUESTION, pool) == {2}
    selected = select_answer_contexts(pool, 6, question=INCREASE_QUESTION)
    assert pool[0] in selected and pool[1] in selected


def test_rent_question_without_increase_selects_the_document():
    pool = [user_document(), statute()]
    assert pool[0] in select_answer_contexts(pool, 6, question=RENT_QUESTION)


def test_document_sentences_stay_evidence_when_a_statute_is_primary():
    pool = [user_document(), statute()]
    markers = {e.marker for e in evidence_candidates(INCREASE_QUESTION, pool)}
    assert 2 in markers


def test_document_citation_does_not_break_the_primary_basis_check():
    pool = [user_document(), statute()]
    assert answer_uses_primary_basis(INCREASE_QUESTION, [pool[0]], pool)
    assert answer_uses_primary_basis(INCREASE_QUESTION, [pool[0], pool[1]], pool)


def test_foreign_case_law_still_cannot_replace_the_primary_statute():
    from tests.factories import court_decision_context

    case = court_decision_context(content="Kira sözleşmesinde artış üretici fiyat endeksine bağlıdır.")
    pool = [case, statute()]
    assert not answer_uses_primary_basis(INCREASE_QUESTION, [pool[0]], pool)


def test_answer_citing_the_document_is_grounded_for_a_document_question():
    pool = [user_document()]
    checked = verify_answer("Aylık kira bedeli 25.000 TL'dir. [K1]", pool, question=RENT_QUESTION)
    assert checked.grounded and checked.contexts == (pool[0],)


def test_scope_rebuild_keeps_a_mixed_document_and_statute_selection():
    pool = [user_document(), statute()]
    answer = "Aylık kira bedeli 25.000 TL'dir. [K1]\nKira artışı bu sentetik örnekte tüketici fiyat endeksine bağlıdır. [K2]"
    assert preserve_statutory_scope(answer, pool, INCREASE_QUESTION) == answer
