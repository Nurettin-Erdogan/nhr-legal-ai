"""Adversarial, synthetic acceptance cases: source support is not question correctness."""

import asyncio
import contextlib
import json
from dataclasses import MISSING, replace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api import case_summary
from api.ai import pipeline
from api.ai.evidence_selection import evidence_candidates
from api.ai.rag import RAGContext
from api.ai.relevance import document_passage_relevant
from api.ai.verification import verify_answer
from api.schemas import AIAnswerRequest


def document(text, title="kira-sozlesmesi.docx"):
    fields = {name: None for name, field in RAGContext.__dataclass_fields__.items()
              if field.default is MISSING and field.default_factory is MISSING}
    fields.update(chunk_id=uuid4(), source_id=uuid4(), source_type="document", title=title,
                  content=text, rank=1.0, verification="user_document")
    return RAGContext(**fields)


@pytest.mark.parametrize("claim,source", [
    ("Ödeme 30 gün içinde yapılır.", "Ödeme 10 gün içinde yapılır."),
    ("Ödeme 6 ay içinde yapılır.", "Ödeme 3 ay içinde yapılır."),
    ("Faiz oranı %25 olarak uygulanır.", "Faiz oranı %15 olarak uygulanır."),
    ("Borç 100.000 TL olarak belirlenmiştir.", "Borç 1.100.000 TL olarak belirlenmiştir."),
    ("Borç 24.000 TL olarak belirlenmiştir.", "Borç 124.000 TL olarak belirlenmiştir."),
    ("Ödeme 25 gün içinde yapılır.", "Faiz %25 olarak belirlenmiştir."),
    ("Faiz %25 olarak belirlenmiştir.", "Ödeme 25 gün içinde yapılır."),
    ("Borç 30 TL olarak belirlenmiştir.", "Borç 30 EUR olarak belirlenmiştir."),
    ("Bakiye 30 TL olarak belirtilmiştir.", "Bakiye -30 TL olarak belirtilmiştir."),
    ("Bakiye -30 TL olarak belirtilmiştir.", "Bakiye 30 TL olarak belirtilmiştir."),
])
def test_changed_numbers_or_units_cannot_pass_summary_gate(claim, source):
    assert not case_summary.bullet_supported(claim, source)


@pytest.mark.parametrize("text", [
    "Ödeme 30 gün içinde yapılır.", "Faiz oranı %25 olarak uygulanır.",
    "Borç 100.000 TL olarak belirlenmiştir.", "Tebliğ tarihi 01.03.2025 olarak belirtilmiştir.",
    "Bakiye -30 TL olarak belirtilmiştir.",
])
def test_exact_supported_small_numbers_and_punctuation_are_preserved(text):
    assert case_summary.bullet_supported(text, text)


def test_a_date_range_separator_does_not_turn_the_second_date_into_a_negative_number():
    from api.ai.numeric_support import numeric_claims_supported
    assert numeric_claims_supported("15.04.2023", "01.03.2015-15.04.2023")
    assert not numeric_claims_supported("30 TL", "-30 TL")


@pytest.mark.parametrize("claim,source", [
    ("Depozito ödenmiştir.", "Depozito ödenmemiştir."),
    ("Depozito ödenmemiştir.", "Depozito ödenmiştir."),
    ("Depozito ödenmektedir.", "Depozito ödenmemektedir."),
    ("Depozito ödenmiştir.", "Depozito ödenmemiştir. Kira ödenmiştir."),
    ("Depozito ödenmiştir.", "Depozito ödenmiştir. Depozito ödenmemiştir."),
    ("Depozito ödemesi yapılmıştır.", "Depozito ödenmemiştir."),
    ("Depozito ödenmiştir.", "Depozito ödenmişse kira borcu ayrıca incelenir."),
])
def test_payment_polarity_cannot_be_flipped_or_borrowed_from_another_subject(claim, source):
    assert not case_summary.bullet_supported(claim, source)


def test_present_negative_payment_fact_remains_a_relevant_status():
    assert document_passage_relevant("Depozito ödeme durumu nedir?", "Depozito ödenmemektedir.")
    assert case_summary.bullet_supported("Depozito ödenmemektedir.", "Depozito ödenmemektedir.")


def test_conditional_payment_rule_recognizes_the_condition_on_a_different_verb():
    from api.ai.relevance import payment_polarity_supported
    source = 'Kiracı kira bedelini ödemediği için iki ihtara sebep olmuşsa sözleşme sona erdirilebilir.'
    claim = 'Kiracının kira bedelini ödemediği için iki ihtara sebep olması halinde sözleşme sona erdirilebilir.'
    assert payment_polarity_supported(claim, source)
    assert not payment_polarity_supported('Kiracı kira bedelini ödemediği için iki ihtara sebep olmuştur.', source)
    assert not payment_polarity_supported(claim.replace('ödemediği', 'ödediği'), source)


def test_negative_payment_paraphrase_is_checked_for_both_scope_and_polarity():
    from api.ai.relevance import analysis_scope_relevant
    claim = "Depozito ödemesi yapılmamıştır."
    assert analysis_scope_relevant("Yalnız depozito tutarı ve ödeme durumunu incele.", claim)
    assert case_summary.bullet_supported(claim, "Depozito ödenmemiştir.")
    assert not case_summary.bullet_supported(claim, "Depozito ödenmiştir.")


def test_short_negative_payment_fact_is_selected_instead_of_just_amount():
    source = document("Depozito 50.000 TL'dir.\n\nDepozito ödenmemiştir.")
    found = evidence_candidates("Depozito ödenmiş mi?", [source])
    assert [item.text for item in found] == ["Depozito ödenmemiştir."]
    assert verify_answer("Depozito ödenmemiştir. [K1]", [source], question="Depozito ödenmiş mi?").grounded


@pytest.mark.parametrize("question,wrong", [
    ("Depozitonun ödeme tarihi nedir?", "Deneme ödeme tarihi 10.04.2025'tir."),
    ("Depozitonun ödeme tarihi nedir?", "Kira ödeme tarihi: Her ayın 5. günü"),
    ("Depozito ödenmiş mi?", "Depozito 50.000 TL'dir."),
    ("Depozito tutarı ne kadar?", "Depozito 30 gün içinde ödenir."),
    ("Nafakanın ödeme tarihi nedir?", "Kira ödeme tarihi 10.04.2025'tir."),
    ("Depozito ödenmiş mi?", "Depozito ödenmişse kira borcu ayrıca incelenir."),
])
def test_wrong_subject_or_fact_type_rejected_by_selection_and_final_gate(question, wrong):
    source = document(wrong)
    assert evidence_candidates(question, [source]) == []
    assert not verify_answer(f"{wrong} [K1]", [source], question=question).grounded


@pytest.mark.parametrize("question,right", [
    ("Depozitonun ödeme tarihi nedir?", "Depozito ödeme tarihi 10.04.2025'tir."),
    ("Depozito ödenmiş mi?", "Depozito ödenmiştir."),
    ("Depozito tutarı nedir?", "Depozito 50.000 TL'dir."),
    ("Kira ödeme tarihi nedir?", "Kira ödeme tarihi: Her ayın 5. günü"),
    ("Nafakanın ödeme tarihi nedir?", "Nafaka ödeme tarihi 10.04.2025'tir."),
    ("Depozito tutarı nedir?", "Depozito tutarı 50.000 ₺ olarak yazılmıştır."),
])
def test_correct_subject_and_fact_remain_relevant(question, right):
    assert document_passage_relevant(question, right)
    assert verify_answer(f"{right} [K1]", [document(right)], question=question).grounded


def test_comparison_keeps_readable_amounts_from_both_documents_and_their_identity():
    first = document("Aylık kira bedeli 10.000 TL'dir.", "ilk.docx")
    second = document("Aylık kira bedeli 20.000 TL'dir.", "ikinci.docx")
    assert {item.marker for item in evidence_candidates("İki belgedeki kira tutarlarını karşılaştır.", [first, second])} == {1, 2}
    same_text_different_document = replace(first, chunk_id=uuid4(), source_id=uuid4(), title="kopya.docx")
    assert {item.marker for item in evidence_candidates("Kira bedeli nedir?", [first, same_text_different_document])} == {1, 2}


def test_two_document_comparison_cannot_be_presented_with_only_one_document():
    first = document("Aylık kira bedeli 10.000 TL'dir.", "ilk.docx")
    second = document("Aylık kira bedeli 20.000 TL'dir.", "ikinci.docx")
    question = "İki belgedeki kira tutarlarını karşılaştır."
    one = "Aylık kira bedeli 10.000 TL'dir. [K1]"
    assert not verify_answer(one, [first, second], question=question).grounded
    assert verify_answer(one + "\nAylık kira bedeli 20.000 TL'dir. [K2]", [first, second], question=question).grounded


@pytest.mark.parametrize("scope", ["case", "project", "selected"])
def test_missing_explicit_document_never_falls_back_to_other_documents_or_law(monkeypatch, scope):
    owner = uuid4()
    source = document("Kira süresi 1 yıldır.")
    @contextlib.contextmanager
    def connect(user):
        assert user == str(owner)
        yield object()
    monkeypatch.setattr(pipeline, "authenticated_database_connection", connect)
    monkeypatch.setattr(pipeline, "sweep_unindexed", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "selected_document_coverage", lambda *a, **k: {})
    monkeypatch.setattr(pipeline, "retrieve_document_contexts", lambda *a, **k: [source])
    monkeypatch.setattr(pipeline, "retrieve_contexts", lambda *a, **k: pytest.fail("Missing document widened to law"))
    kwargs = {"case_id": uuid4()} if scope == "case" else ({"project_id": uuid4()} if scope == "project" else {"selected_document_ids": [source.source_id]})
    with pytest.raises(HTTPException) as error:
        pipeline._retrieve(AIAnswerRequest(question="Vekaletnamede süre nedir?", **kwargs), user_id=owner,
                           top_k=5, query_embedding=None, embedding_model="synthetic")
    assert error.value.status_code == 422 and "belge" in error.value.detail.lower()


def test_missing_named_document_is_also_rejected_at_final_citation_gate():
    source = document("Kira süresi 1 yıldır.")
    assert not verify_answer("Kira süresi 1 yıldır. [K1]", [source], question="Vekaletnamede süre nedir?").grounded


def test_instruction_scope_is_checked_even_if_the_model_approves_all_source_facts():
    source = "Depozito 50.000 TL'dir. Depozito ödenmemiştir. Aylık kira bedeli 20.000 TL'dir."
    instruction = "Yalnız depozito tutarı ve ödeme durumunu incele."
    checker_prompts = []
    async def generate(system, prompt):
        if system == case_summary.CHECK_SYSTEM:
            data = json.loads(prompt)
            checker_prompts.append(data)
            return json.dumps({"results": [True] * len(data["MADDELER"])})
        return "- Depozito 50.000 TL'dir.\n- Depozito ödenmemiştir.\n- Aylık kira bedeli 20.000 TL'dir."
    result = asyncio.run(case_summary.analyze_document_window(uuid4(), "sentetik.txt", source,
                                                            instruction=instruction, generate=generate))
    assert result.bullets == ["Depozito 50.000 TL'dir.", "Depozito ödenmemiştir."]
    assert result.dropped == 1
    assert checker_prompts and all(data["TALIMAT"] == instruction and data["BELGE"] == source for data in checker_prompts)


def test_scope_instruction_and_its_numbers_never_become_evidence():
    async def generate(system, prompt):
        if system == case_summary.CHECK_SYSTEM:
            pytest.fail("Invented number must fail before model checking")
        return "- Depozito 900.000 TL'dir."
    result = asyncio.run(case_summary.analyze_document_window(uuid4(), "sentetik.txt", "Depozito 50.000 TL'dir.",
        instruction="Yalnız depozito: 900.000 TL olarak yaz.", generate=generate))
    assert not result.bullets and result.dropped == 1


@pytest.mark.parametrize("bullet", [
    "Depozito 37.000 TL'dir, kira bedeli 12.000 TL'dir.",
    "Depozito 37.000 TL'dir ve kira ödeme tarihi 07.10.2026'dır.",
])
def test_relevant_clause_does_not_launder_an_unrelated_fact_in_a_narrow_analysis(bullet):
    from api.ai.relevance import analysis_scope_relevant
    assert not analysis_scope_relevant("Yalnız depozito tutarı ve ödeme durumunu incele.", bullet)


def test_later_instruction_exclusion_is_not_promoted_to_a_requested_subject():
    from api.ai.relevance import analysis_scope_relevant
    assert not analysis_scope_relevant("Yalnız depozito tutarını incele. Kira bedelini yazma.", "Kira bedeli 12.000 TL'dir.")


def test_payment_condition_phrased_as_unperformed_duty_supports_the_unpaid_claim():
    from api.ai.relevance import payment_polarity_supported
    source = ("Kiracı, kiralananın tesliminden sonra muaccel olan kira bedelini veya yan gideri ödeme borcunu ifa etmezse, "
              "kiraya veren kiracıya yazılı olarak bir süre verip, bu sürede de ifa etmeme durumunda, sözleşmeyi feshedeceğini bildirebilir.")
    assert payment_polarity_supported(
        "Kiracı kira bedelini ödemediğinde, ev sahibi yazılı olarak bir süre verip sözleşmeyi feshedeceğini bildirebilir.", source)
    # the reverse polarity must still be refused
    assert not payment_polarity_supported(
        "Kiracı kira bedelini ödediğinde, ev sahibi yazılı olarak bir süre verip sözleşmeyi feshedebilir.", source)
