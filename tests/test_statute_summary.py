"""Uzun kanun maddesi cevabının üstündeki kısa özet: yalnız denetimden geçen maddeler gösterilir, cevap metni değişmez."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from uuid import uuid4

from api.ai import statute_summary
from api.ai.rag import RAGContext
from api.ai.verification import VerifiedAnswer

ARTICLE = (
    "Fazla çalışma ücreti Madde 41 - Ülkenin genel yararları yahut işin niteliği veya üretimin artırılması gibi nedenlerle fazla "
    "çalışma yapılabilir. Fazla çalışma, Kanunda yazılı koşullar çerçevesinde, haftalık kırkbeş saati aşan çalışmalardır. "
    "Her bir saat fazla çalışma için verilecek ücret normal çalışma ücretinin saat başına düşen miktarının yüzde elli "
    "yükseltilmesi suretiyle ödenir. Fazla çalışma süresinin toplamı bir yılda ikiyüzyetmiş saatten fazla olamaz. "
) * 4


def _context(**overrides) -> RAGContext:
    values = dict(
        chunk_id=uuid4(), source_id=uuid4(), source_type="legislation", title="İş Kanunu", source_url=None, authority=None,
        court_name=None, chamber=None, docket_no=None, decision_no=None, decision_date=None, law_name="İŞ KANUNU", law_no="4857",
        article_no="41", article_title="Fazla çalışma ücreti", content=ARTICLE, rank=1.0,
    )
    values.update(overrides)
    return RAGContext(**values)


def _answer(text: str = ARTICLE, contexts=None) -> VerifiedAnswer:
    marked = "\n\n".join(f"{sentence.strip()}. [K1]" for sentence in text.split(". ") if sentence.strip())
    return VerifiedAnswer(text=marked, contexts=tuple(contexts or (_context(),)), unverified_markers=())


def _generate(summary: str, verdicts: list[bool] | None = None, calls: list | None = None):
    async def generate(system: str, prompt: str) -> str:
        if calls is not None:
            calls.append(system)
        if "denetçisisin" in system:
            items = json.loads(prompt)["MADDELER"]
            return json.dumps({"results": verdicts if verdicts is not None else [True] * len(items)})
        return summary

    return generate


def test_a_long_single_article_answer_gets_a_checked_summary():
    summary = (
        "- Fazla çalışma ücreti normal çalışma ücretinin saat başına düşen miktarının yüzde elli yükseltilmesi suretiyle ödenir.\n"
        "- Fazla çalışma süresinin toplamı bir yılda ikiyüzyetmiş saatten fazla olamaz."
    )
    bullets = asyncio.run(statute_summary.build("Fazla çalışma ücreti nasıl ödenir?", _answer(), _generate(summary)))
    assert len(bullets) == 2 and bullets[0].startswith("Fazla çalışma ücreti normal")


def test_invented_numbers_and_rejected_bullets_never_appear():
    summary = (
        "- Fazla çalışma ücreti yüzde 75 zamlı ödenir.\n"  # maddede olmayan oran: kod eler (sayı < 3 hane olduğundan örtüşme ile)
        "- Fazla çalışma süresinin toplamı bir yılda 1500 saatten fazla olamaz.\n"  # maddede olmayan sayı
        "- Fazla çalışma süresinin toplamı bir yılda ikiyüzyetmiş saatten fazla olamaz."
    )
    bullets = asyncio.run(statute_summary.build("Fazla çalışma sınırı nedir?", _answer(), _generate(summary, verdicts=None)))
    assert all("1500" not in bullet for bullet in bullets)
    rejected = asyncio.run(
        statute_summary.build("Fazla çalışma sınırı nedir?", _answer(), _generate("- Fazla çalışma süresinin toplamı bir yılda ikiyüzyetmiş saatten fazla olamaz.", verdicts=[False]))
    )
    assert rejected == ()


def test_short_answers_case_law_and_mixed_articles_are_not_summarised():
    calls: list = []
    generate = _generate("- x", calls=calls)
    short = VerifiedAnswer(text="Kısa hüküm. [K1]", contexts=(_context(),), unverified_markers=())
    decision = _answer(contexts=(_context(source_type="court_decision", law_no=None, article_no=None, decision_date=date(2024, 1, 1)),))
    mixed = _answer(contexts=(_context(), _context(article_no="42")))
    unverified = _answer(contexts=(_context(verification="third_party"),))
    for answer in (short, decision, mixed, unverified):
        assert not statute_summary.eligible(answer)
        assert asyncio.run(statute_summary.build("soru", answer, generate)) == ()
    assert calls == []  # uygun olmayan cevapta model hiç çağrılmaz


def test_the_no_answer_line_and_model_failures_yield_no_summary():
    assert asyncio.run(statute_summary.build("Kira artışı nedir?", _answer(), _generate("- Madde bu soruyu doğrudan düzenlemiyor."))) == ()

    async def broken(system: str, prompt: str) -> str:
        raise RuntimeError("model yok")

    assert asyncio.run(statute_summary.build("Fazla çalışma ücreti nasıl ödenir?", _answer(), broken)) == ()


def test_summary_does_not_affect_groundedness_and_is_stored_with_the_message():
    answer = _answer()
    from dataclasses import replace

    with_summary = replace(answer, summary=("Özet maddesi.",))
    assert with_summary.grounded == answer.grounded and with_summary.text == answer.text


def test_a_truncated_model_output_still_yields_its_completed_bullets():
    """Canlıda görüldü: model 5 madde sınırını aşıp çıktı sınırında kesilince özet hiç çıkmıyordu."""
    from api.ai.providers import AIProviderError

    partial = (
        "- Fazla çalışma ücreti normal çalışma ücretinin saat başına düşen miktarının yüzde elli yükseltilmesi suretiyle ödenir.\n"
        "- Fazla çalışma süresinin toplamı bir yılda ikiyüzyetmiş saatten fazla olamaz.\n"
        "- Fazla çalışma, Kanunda yazılı koşullar çerçevesinde, haftalık kırkb"  # yarım kalan satır
    )

    async def generate(system: str, prompt: str) -> str:
        if "denetçisisin" in system:
            return json.dumps({"results": [True] * len(json.loads(prompt)["MADDELER"])})
        raise AIProviderError("Ollama yanıtı token sınırında kesildi", partial=partial)

    bullets = asyncio.run(statute_summary.build("Fazla çalışma ücreti nasıl ödenir?", _answer(), generate))
    assert len(bullets) == 2 and all("kırkb" not in bullet for bullet in bullets)
    assert statute_summary.complete_lines("- tek yarım sat") == ""


def test_the_verified_answer_is_previewed_before_the_summary_step_and_the_final_answer_carries_the_summary(monkeypatch):
    # Özet ek bir model çağrısıdır; kullanıcı onu beklerken doğrulanmış cevabı okuyabilmelidir.
    from dataclasses import replace
    from types import SimpleNamespace

    from api.ai import pipeline
    from api.ai.cache import answer_cache
    from api.schemas import AIAnswerRequest
    from tests.factories import legislation_context

    text = "Kira artışı bu sentetik örnekte tüketici fiyat endeksine bağlıdır."
    statute = replace(legislation_context(content=text), law_no="6098", article_no="344")
    answer_cache.clear()
    settings = SimpleNamespace(
        ai_provider="qwen", ai_model="synthetic", ollama_base_url="http://127.0.0.1:11434", ollama_timeout_seconds=1,
        ollama_max_output_tokens=256, ollama_num_ctx=4096, ollama_keep_alive="1m", rag_top_k=6, rag_context_chars=2400,
        rag_query_embedding=False, rag_explanations=False, embedding_model="test-model",
    )
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(pipeline, "create_provider", lambda **kw: SimpleNamespace(name="qwen", model="synthetic"))
    for name in ("pause_embeddings", "resume_embeddings", "unload_ollama_model", "verify_relevant_pending_statute"):
        if hasattr(pipeline, name):
            monkeypatch.setattr(pipeline, name, lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "try_fast_statute", lambda **kw: [statute])
    monkeypatch.setattr(pipeline, "generate_grounded_answer", lambda *a, **k: text + " [K1]")
    order: list[str] = []

    async def build(question, answer, generate):
        order.append("özet")
        return ("Artış TÜFE'ye bağlıdır.",)

    monkeypatch.setattr(statute_summary, "eligible", lambda answer: True)
    monkeypatch.setattr(statute_summary, "build", build)
    events: list[dict] = []

    def on_stage(event):
        if event.get("preview"):
            order.append("önizleme")
        events.append(event)

    question = "Kira sözleşmesinde TÜFE üzerinde artış istenirse ne yapılır?"
    response, _ = asyncio.run(pipeline.execute_answer(AIAnswerRequest(question=question), None, on_stage=on_stage))

    (summarizing,) = [event for event in events if event["stage"] == "summarizing"]
    preview = summarizing["preview"]
    assert order == ["önizleme", "özet"]
    assert preview["answer"] == response.answer and preview["grounded"] is True
    assert preview["summary"] == [] and preview["conversation_id"] is None and preview["message_id"] is None
    assert [citation["reference"] for citation in preview["citations"]] == [citation.reference for citation in response.citations]
    assert response.summary == ["Artış TÜFE'ye bağlıdır."]
    assert [event["stage"] for event in events][-1] == "done"
