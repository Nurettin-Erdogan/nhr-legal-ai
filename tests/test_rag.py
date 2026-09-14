from __future__ import annotations

from datetime import date
from uuid import UUID

from api.ai.rag import RAGContext, build_grounded_prompt, generate_grounded_answer


CONTEXT = RAGContext(
    chunk_id=UUID("00000000-0000-0000-0000-000000000001"),
    source_id=UUID("00000000-0000-0000-0000-000000000002"),
    title="Yargıtay 9. Hukuk Dairesi, E. 2026/1, K. 2026/2",
    source_url="https://example.test/decision/1",
    chamber="9. Hukuk Dairesi",
    docket_no="2026/1",
    decision_no="2026/2",
    decision_date=date(2026, 1, 2),
    content="İşçi, haklı nedenle fesih hâlinde kıdem tazminatına hak kazanır.",
    rank=0.5,
)


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
    prompt = build_grounded_prompt("Kıdem tazminatı alınabilir mi?", [CONTEXT])

    assert "KULLANICI SORUSU" in prompt
    assert "Kıdem tazminatı alınabilir mi?" in prompt
    assert "[K1]" in prompt
    assert "Esas: 2026/1 | Karar: 2026/2" in prompt
    assert CONTEXT.content in prompt


def test_provider_receives_grounding_rules_and_context():
    provider = FakeProvider()

    answer = generate_grounded_answer(
        provider,
        question="Haklı fesih nedir?",
        contexts=[CONTEXT],
    )

    assert answer.endswith("[K1]")
    assert "bilgi veya karar uydurma" in provider.system_instruction
    assert CONTEXT.title in provider.prompt
