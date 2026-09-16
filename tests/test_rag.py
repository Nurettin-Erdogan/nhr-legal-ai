from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.ai.providers import GeminiProvider
from api.ai.rag import RAGContext, build_grounded_prompt, generate_grounded_answer
from api.ai.routes import _require_project_access
from tests.factories import court_decision_context, document_context, legislation_context

DECISION = court_decision_context()
LEGISLATION = legislation_context()
DOCUMENT = document_context()


class FakeProvider:
    name = "fake"
    model = "test-model"

    def __init__(self) -> None:
        self.system_instruction = ""
        self.prompt = ""

    def generate(self, *, system_instruction: str, prompt: str) -> str:
        self.system_instruction = system_instruction
        self.prompt = prompt
        return "İşçi kıdem tazminatına hak kazanabilir. [K1]"


def test_prompt_contains_question_and_stable_source_marker():
    prompt = build_grounded_prompt("Kıdem tazminatı alınabilir mi?", [DECISION])

    assert "KULLANICI SORUSU" in prompt
    assert "Kıdem tazminatı alınabilir mi?" in prompt
    assert "[K1] Yargıtay 9. Hukuk Dairesi, E. 2026/1, K. 2026/2, T. 02.01.2026" in prompt
    assert "Tür: Mahkeme kararı" in prompt
    assert DECISION.content in prompt


def test_prompt_labels_legislation_with_law_and_article():
    prompt = build_grounded_prompt("Haklı fesih nedir?", [LEGISLATION])

    assert "[K1] İş Kanunu (4857) m. 25 — İşverenin haklı nedenle derhal fesih hakkı" in prompt
    assert "Tür: Mevzuat" in prompt


def test_aym_reference_uses_application_number_not_fake_case_number():
    context = replace(
        DECISION,
        court_name="Anayasa Mahkemesi",
        chamber="İkinci Bölüm",
        docket_no="2099/123",
        decision_no=None,
    )

    assert context.reference_line.startswith(
        "Anayasa Mahkemesi İkinci Bölüm, B. No: 2099/123"
    )
    assert "E. 2099/123" not in context.reference_line


def test_prompt_numbers_mixed_source_types_in_order():
    prompt = build_grounded_prompt("Fesih", [LEGISLATION, DECISION])

    assert prompt.index("[K1] İş Kanunu") < prompt.index("[K2] Yargıtay")


def test_prompt_labels_user_document_with_page_and_section():
    prompt = build_grounded_prompt("Fesih tarihi nedir?", [DOCUMENT])

    assert "[K1] iş_sözleşmesi.pdf, s. 3, Fesih" in prompt
    assert "Tür: Kullanıcı belgesi" in prompt


def test_prompt_labels_kdk_as_administrative_official_source():
    context = RAGContext(
        chunk_id=uuid4(),
        source_id=uuid4(),
        source_type="other",
        title="KDK, 2099/1 — Tavsiye Kararı",
        source_url="https://kararlar.ombudsman.gov.tr/Arama/Download?id=1",
        authority="Kamu Denetçiliği Kurumu",
        court_name="Kamu Denetçiliği Kurumu",
        chamber=None,
        docket_no=None,
        decision_no="2099/1",
        decision_date=None,
        law_name=None,
        law_no=None,
        article_no=None,
        article_title=None,
        content="Sentetik KDK karar metni.",
        rank=1.0,
    )

    prompt = build_grounded_prompt("İdarenin işlemi uygun mu?", [context])

    assert "Tür: İdarî karar / resmî kaynak" in prompt
    assert "Kamu Denetçiliği Kurumu" in prompt


def test_project_rag_requires_authentication_before_retrieval():
    with pytest.raises(HTTPException) as error:
        _require_project_access(None, uuid4())

    assert error.value.status_code == 401


def test_provider_receives_grounding_rules_and_context():
    provider = FakeProvider()

    answer = generate_grounded_answer(
        provider,
        question="Haklı fesih nedir?",
        contexts=[DECISION],
    )

    assert answer.endswith("[K1]")
    assert "bilgi, karar veya madde uydurma" in provider.system_instruction
    assert "olmayan bir kaynağa atıf yapma" in provider.system_instruction
    assert DECISION.content in provider.prompt


def test_gemini_provider_classifies_transient_errors():
    assert GeminiProvider._is_transient(RuntimeError("503 high demand"))
    assert GeminiProvider._is_transient(RuntimeError("429 rate limit"))
    assert not GeminiProvider._is_transient(RuntimeError("invalid API key"))
    assert not GeminiProvider._is_transient(
        RuntimeError("429 prepayment credits are depleted")
    )


def test_gemini_provider_hides_raw_billing_error():
    error = GeminiProvider._public_error(
        RuntimeError("429 RESOURCE_EXHAUSTED: prepayment credits are depleted; raw-data")
    )

    assert error.status_code == 429
    assert "kredisi tükenmiş" in str(error)
    assert "raw-data" not in str(error)
