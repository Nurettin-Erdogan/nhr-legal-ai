"""Regressions for multi-part legal questions and independent chat turns.

Only synthetic source fixtures; does not access real database, cloud or workers.
"""
from dataclasses import replace
from uuid import UUID

import pytest

from api.ai.authority import primary_legislation_markers
from api.ai.conversation_history import needs_standalone_rewrite
from api.ai.discovery import select_answer_contexts
from api.ai.fast_statute import fast_reference
from api.ai.relevance import question_intent
from tests.factories import court_decision_context, legislation_context


def statute(article: int, *, law: str = "4857"):
    return replace(
        legislation_context(),
        law_no=law,
        article_no=str(article),
        source_id=UUID(int=1000 + article),
        chunk_id=UUID(int=2000 + article),
    )


def test_explicit_two_articles_are_both_primary_not_first_only():
    question = "4857 sayılı İş Kanunu m. 18 ve m. 20 hükümleri nelerdir?"
    contexts = [court_decision_context(), statute(18), statute(20)]
    assert primary_legislation_markers(question, contexts) == {2, 3}
    assert select_answer_contexts(contexts, 6, question=question) == contexts[1:]


def test_ambiguous_multiple_explicit_laws_do_not_get_incorrectly_paired():
    question = "4857 sayılı Kanun m. 20 ve 7036 sayılı Kanun m. 3 hükümlerini karşılaştır."
    contexts = [statute(20), statute(3, law="7036")]
    assert primary_legislation_markers(question, contexts) == set()
    assert select_answer_contexts(contexts, 6, question=question) == contexts


def test_combined_reinstatement_conditions_and_deadline_keep_both_statutes():
    question = "İşe iade davası açma süresi ve şartları nelerdir?"
    contexts = [statute(18), statute(20), court_decision_context()]
    assert question_intent(question) is None
    assert fast_reference(question) is None
    assert primary_legislation_markers(question, contexts) == set()
    assert select_answer_contexts(contexts, 6, question=question) == contexts


def test_single_deadline_keeps_fast_statute_and_current_primary():
    question = "İşe iade davası açma süresi nedir?"
    contexts = [statute(18), statute(20), court_decision_context()]
    assert question_intent(question).statute == ("4857", "20")
    assert fast_reference(question) == ("4857", "20")
    assert primary_legislation_markers(question, contexts) == {2}
    assert select_answer_contexts(contexts, 6, question=question) == contexts[1:2]


def test_severance_plus_notice_pay_does_not_exclude_notice_provision():
    question = "Kıdem ve ihbar tazminatı birlikte istenebilir mi?"
    contexts = [statute(14, law="1475"), statute(17)]
    assert primary_legislation_markers(question, contexts) == set()
    assert select_answer_contexts(contexts, 6, question=question) == contexts


def test_severance_only_still_has_its_primary_provision():
    question = "Kıdem tazminatına hak kazanma şartları nelerdir?"
    assert question_intent(question).statute == ("1475", "14")


@pytest.mark.parametrize("question", [
    "Kira artış oranı nasıl belirlenir?",
    "İşe iade davasının şartları nelerdir?",
    "2026 yılında yıllık izin hakkı nasıl hesaplanır?",
])
def test_standalone_new_question_does_not_need_extra_model_call(question):
    assert not needs_standalone_rewrite(question)


@pytest.mark.parametrize("question", [
    "Peki bunun süresi ne kadar?",
    "Bunun koşulları neler?",
    "Ne kadar?",
    "Aynı durumda ne yapmalıyım?",
])
def test_context_dependent_followup_still_uses_rewrite(question):
    assert needs_standalone_rewrite(question)
