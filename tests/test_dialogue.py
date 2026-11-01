"""Input controls are not legal answers; user facts are not legal evidence."""
from dataclasses import replace

import pytest

from api.ai.dialogue import missing_input_plan, resume_question, user_inputs
from api.ai.rag import HistoryTurn
from api.ai.synthesis import synthesize_answer
from tests.factories import legislation_context, document_context


JOB = "İşçinin işe başladığı tarihten itibaren her geçen tam yıl için ücreti tutarında kıdem tazminatı ödenir."
RENT = "Kiracının kira bedelindeki artış tüketici fiyat endeksindeki değişim oranını geçemez."
JOB_QUESTION = "Ben 10 sene çalıştım çıkarıldım ne kadar toplu para alırım?"


def plan(question=JOB_QUESTION, **kwargs):
    return missing_input_plan(question, [legislation_context(content=JOB)], **kwargs)


def test_personal_amount_collects_inputs_without_inventing_a_legal_result():
    value = plan()
    assert value.missing == ("gross_pay", "employment_dates", "termination_reason")
    assert "brüt" in value.question and "tarihlerinizi" in value.question and "nedeninizi" in value.question
    assert value.question.count("?") == 1
    assert not any(word in value.question for word in ("hak kazan", "zorunda", "tazminat öden", "10", "otuz"))


@pytest.mark.parametrize("question", [
    "İşyerimden kovuldum ne kadar para alırım?", "İşten atıldım kaç lira alabilirim?",
    "Ben on yıl çalıştım, işveren beni çıkardı, ne kadar alırım?",
])
def test_everyday_variations_collect_facts_without_a_topic_specific_legal_answer(question):
    value = missing_input_plan(question, (), allow_source_free=True)
    assert value and "gross_pay" in value.missing
    assert "tazminat ödenir" not in value.question


@pytest.mark.parametrize("question", ["Evden kovuldum kaç para alırım?", "Okuldan atıldım ne kadar öderim?"])
def test_nonemployment_removal_does_not_turn_into_a_salary_form(question):
    assert missing_input_plan(question, (), allow_source_free=True) is None


@pytest.mark.parametrize("question", [
    "Kıdem tazminatı nasıl hesaplanır?", "İşçinin hangi hakları vardır?",
    "Kıdem tazminatının şartları nelerdir?", "Genel olarak ne kadar kıdem tazminatı ödenir?",
    "Bu belgedeki ücret bilgisine göre ne kadar tazminat alırım?",
])
def test_general_law_and_document_questions_are_not_forced_into_an_intake_form(question):
    assert plan(question) is None


def test_source_example_salary_dates_and_reason_never_become_user_facts():
    source = legislation_context(content=JOB + " İşçi brüt 50000 TL almış, 01.01.2010 ve 01.01.2020 arasında çalışmış ve istifa etmiştir.")
    value = missing_input_plan(JOB_QUESTION, [source])
    assert value.missing == ("gross_pay", "employment_dates", "termination_reason")
    assert "50000" not in value.question


@pytest.mark.parametrize("verification", ["third_party", "unknown"])
def test_unverified_sources_cannot_activate_source_bound_controls(verification):
    context = replace(legislation_context(content=JOB), verification=verification)
    assert missing_input_plan(JOB_QUESTION, [context]) is None


def test_user_document_requires_the_document_reading_route_not_generic_intake():
    assert missing_input_plan(JOB_QUESTION, [document_context(content=JOB)]) is None


def test_known_user_inputs_survive_multiple_clarifications_and_are_not_reasked():
    original = JOB_QUESTION
    questions = [original, "Son brüt ücretim 40000 TL", "01.01.2016'da girdim, 20.10.2026'da çıktım"]
    value = plan("Gerekçe gösterilmedi", prior_questions=questions)
    assert value is None  # enough event inputs: the grounded writer must now decide what sources support
    value = plan("Son brüt ücretim 40000 TL", prior_questions=[original])
    assert "gross_pay" not in value.missing and "brüt ücretinizi" not in value.question
    assert value.missing == ("employment_dates", "termination_reason")


def test_net_salary_does_not_become_gross_and_a_correction_overrides_old_gross():
    value = plan("Maaşım net 40000 TL", prior_questions=[JOB_QUESTION, "Maaşım brüt 50000 TL"])
    assert "gross_pay" in value.missing
    value = plan("Ücretim brüt değil, net 40000 TL", prior_questions=[JOB_QUESTION])
    assert "gross_pay" in value.missing


@pytest.mark.parametrize("answer", ["Bilmiyorum", "Hatırlamıyorum", "Paylaşmak istemiyorum"])
def test_unknown_or_declined_information_does_not_trigger_the_same_form_again(answer):
    assert plan(answer, prior_questions=[JOB_QUESTION]) is None


def test_topic_switch_and_new_event_do_not_inherit_another_events_salary():
    earlier = [JOB_QUESTION, "Son brüt ücretim 40000 TL", "Kira artış oranı nasıl belirlenir?"]
    value = plan(JOB_QUESTION, prior_questions=earlier)
    assert "gross_pay" in value.missing
    value = plan("Başka bir işçi için: ben çıkarıldım ne kadar para alırım?", prior_questions=earlier[:2])
    assert "gross_pay" in value.missing


def test_assistant_answer_is_never_used_to_fill_user_fields():
    history = [HistoryTurn(JOB_QUESTION, "Brüt ücretiniz 50000 TL ve çıkışınız 20.10.2026.", "clarification")]
    assert "gross_pay" in plan("İşten çıkarıldım", history=history).missing
    assert all("50000" not in text for text in user_inputs("Çıkarıldım", history))


def test_clarification_reply_continues_original_question_without_a_model_rewrite():
    history = [HistoryTurn(JOB_QUESTION, "Son brüt ücretinizi paylaşır mısınız?", "clarification")]
    result = resume_question("Son brüt ücretim 40000 TL", history, [JOB_QUESTION])
    assert JOB_QUESTION.rstrip("?") in result and result.endswith("Son brüt ücretim 40000 TL")
    assert resume_question("Kira artış oranı nedir?", history, [JOB_QUESTION]) is None
    assert resume_question("Yeni konu: icra dosyam var", history, [JOB_QUESTION]) is None
    assert resume_question("40000 TL", [HistoryTurn(JOB_QUESTION, "Kaynak yok.")]) is None


def test_rent_user_inputs_do_not_ask_the_user_for_the_official_rate():
    value = missing_input_plan("18 bin kira alıyorum ne kadar zam yapabilirim?", [legislation_context(content=RENT)])
    assert value.missing == ("renewal_period", "property_type")
    assert "oran" not in value.question and "TÜFE" not in value.question
    value = missing_input_plan("Konut, Kasım 2026'da yenilenecek", [legislation_context(content=RENT)],
                               prior_questions=["18 bin kira alıyorum ne kadar zam yapabilirim?"])
    assert value is None  # a missing official index is a source gap, not an event input


def test_input_control_never_calls_a_writer_or_claim_checker_and_is_not_grounded():
    class Forbidden:
        def generate(self, **kwargs):
            pytest.fail("Neutral input control must not call a model")
    diagnostics = {}
    answer = synthesize_answer(Forbidden(), question=JOB_QUESTION,
                              contexts=[legislation_context(content=JOB)], diagnostics=diagnostics)
    assert answer.answer_kind == "clarification" and not answer.grounded
    assert answer.contexts == answer.unverified_markers == ()
    assert diagnostics["missing_inputs"] == ["gross_pay", "employment_dates", "termination_reason"]


def test_source_free_mode_is_only_a_neutral_user_input_control():
    value = missing_input_plan(JOB_QUESTION, (), allow_source_free=True)
    assert value.missing == ("gross_pay", "employment_dates", "termination_reason")
    assert missing_input_plan("İşçinin kıdem tazminatı nasıl hesaplanır?", (), allow_source_free=True) is None
    assert missing_input_plan("18 bin kira alıyorum, %20 artışla kaç olur?", (), allow_source_free=True) is None


def test_colloquial_retrieval_adds_candidates_not_a_primary_entitlement_rule():
    from api.ai.relevance import question_intent, semantic_search_text
    from api.statute_hints import suggest
    intent = question_intent(JOB_QUESTION)
    assert intent.name == "employment_termination" and intent.statute is None
    assert "iş sözleşmesinin feshi" in semantic_search_text(JOB_QUESTION)
    assert {(hint.law_no, hint.article_no) for hint in suggest(JOB_QUESTION)} >= {("4857", "17"), ("1475", "14")}
    assert question_intent("Duruşma salonundan çıkarıldım ne kadar beklerim?") is None
