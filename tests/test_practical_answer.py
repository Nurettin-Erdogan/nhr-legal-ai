"""Gerçek kullanıcı hesabı/API olmadan: net kira sorusu, eksik veri ve güvenli aritmetik."""
from dataclasses import replace

import pytest

from api.ai.practical_answer import rent_summary
from api.ai.verification import VerifiedAnswer
from tests.factories import legislation_context


def answer(**changes):
    context = replace(legislation_context(), law_no="6098", article_no="344", verification="official")
    return replace(VerifiedAnswer(text="Kaynak cümlesi. [K1]", contexts=(context,), unverified_markers=()), **changes)


def summary(question, **kwargs):
    return rent_summary(answer(), question=question, user_question=question, **kwargs)


def test_real_question_asks_for_renewal_period_instead_of_inventing_a_rate():
    question = "ben ne fazla ne kadar kira artışı yapabilirim 18 bin kira alıom"
    lines = summary(question)
    assert len(lines) == 1
    assert "18.000 TL" in lines[0] and "ay/yıl" in lines[0] and "konut" in lines[0]
    assert "%" not in lines[0] and lines[0].endswith("?")


@pytest.mark.parametrize("amount", ["18 bin", "18.000 TL", "18000", "18000 lira"])
def test_user_rate_is_calculated_not_misrepresented_as_legal_permission(amount):
    lines = summary(f"En fazla kira artışı %{20} yapabilir miyim: {amount} kira alıyorum")
    assert "21.600 TL" in lines[0] and "3.600 TL" in lines[0]
    assert "Verdiğiniz %20" in lines[0] and "yasal üst sınır olduğunu göstermez" in lines[0]
    assert "yapabilirsiniz" not in " ".join(lines)


def test_decimal_money_and_percentage_round_to_cents():
    text = " ".join(summary("Kira artışı %37,42 için 18.000 TL kira alıyorum"))
    assert "24.735,60 TL" in text and "6.735,60 TL" in text


def test_pure_arithmetic_gets_only_the_result_without_irrelevant_legal_disclaimer():
    lines = summary("Örnek hesap: 18.000 TL konut kirasına %20 artışla yeni kira ne kadar?")
    assert len(lines) == 1 and "21.600 TL" in lines[0] and "3.600 TL" in lines[0]
    assert "yasal" not in lines[0] and "yazar mısınız" not in lines[0]


def test_completed_rate_calculation_never_falls_through_to_asking_for_the_same_rate():
    question = "Hukuki üst sınır olarak değil, sadece örnek hesap: 18.000 TL kiraya %20 zam yapılırsa yeni kira kaç TL olur?"
    lines = summary(question, prior_questions=["Konut için. Kasım 2026 yenileme; kira 18.000 TL."])
    assert len(lines) == 1 and "21.600 TL" in lines[0] and "3.600 TL" in lines[0]
    assert "Oranı paylaşırsanız" not in lines[0] and "kaynaklarda yok" not in lines[0]


def test_known_period_and_property_do_not_trigger_the_same_questions_again():
    lines = summary("Ekim 2026 yenilenen konut kira artışı: 18 bin alıyorum")
    assert len(lines) == 1 and "doğrulanmış TÜFE oranı" in lines[0]
    assert "yazar mısınız" not in lines[0] and "%20" not in lines[0]


def test_follow_up_uses_original_user_amount_not_the_models_rewrite():
    lines = rent_summary(answer(), question="Ekim 2026 konut kira artışı 99 bin için nedir?",
        user_question="Konut, Ekim 2026 yenilenecek",
        prior_questions=["Kira artışı yapacağım 18 bin kira alıyorum"])
    assert "99" not in " ".join(lines)
    calculated = rent_summary(answer(), question="Kira artışı yüzde 20 için hesap nedir?", user_question="%20 hesapla",
        prior_questions=["Kira artışı 18 bin kira alıyorum"])
    assert "21.600 TL" in calculated[0]


def test_new_amount_overrides_prior_amount():
    lines = summary("Kira artışı %20, 20 bin kira alıyorum", prior_questions=["Kira artışı 18 bin kira"])
    assert "24.000 TL" in lines[0] and "21.600 TL" not in lines[0]


def test_multiple_amounts_do_not_pick_a_random_base_or_reuse_old_base():
    lines = summary("Kira artışı %20 için 18 bin mi 20 bin mi?", prior_questions=["Kira 10 bin"])
    assert "mevcut kira tutarını" in " ".join(lines)
    assert "hesap:" not in " ".join(lines)


@pytest.mark.parametrize("query", ["Kira artışı 2026 yılında ne kadar?", "Kira artışı TC 12345678901 olan kiracı için ne kadar?",
                                    "Kira artışı 18.10.2026 tarihinde ne kadar?", "Kira artışı -18000 TL için ne kadar?"])
def test_dates_ids_and_negative_values_are_not_current_rent(query):
    assert "mevcut kira tutarını" in " ".join(summary(query))


def test_no_guidance_without_verified_legal_basis_and_no_mutation_of_evidence():
    original = answer()
    for invalid in [replace(original, contexts=()), replace(original, unsupported_claims=("unsupported",)),
                    replace(original, contexts=(replace(original.contexts[0], verification="third_party"),)),
                    replace(original, contexts=(replace(original.contexts[0], article_no="343"),))]:
        assert rent_summary(invalid, question="Kira artışı ne kadar?", user_question="Kira artışı ne kadar?") == ()
    assert rent_summary(original, question="Yıllık izin kaç gün?", user_question="Yıllık izin kaç gün?") == ()
    assert original.text == "Kaynak cümlesi. [K1]" and original.summary == ()


@pytest.mark.parametrize("question", ["Kira sözleşmesinde TÜFE üzerinde artış istenirse ne yapılır?",
                                      "18 bin kira için %50 zam isteyen ev sahibine nasıl itiraz edebilirim?"])
def test_calculator_does_not_replace_remedy_or_general_law_questions(question):
    assert summary(question) == ()


def test_excessively_long_numerals_do_not_crash_decimal_arithmetic():
    text = "Kira artışı %" + "9" * 200 + " için " + "9" * 200 + " TL"
    assert summary(text)


def test_real_pipeline_returns_and_caches_calculation_with_unchanged_verified_basis(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from api.ai import pipeline, explanation
    from api.ai.cache import answer_cache
    from api.schemas import AIAnswerRequest
    from tests.test_ai_pipeline import _settings

    text = ("Tarafların yenilenen kira dönemlerinde uygulanacak kira bedeline ilişkin anlaşmaları, "
            "bir önceki kira yılında tüketici fiyat endeksindeki oniki aylık ortalamalara göre "
            "değişim oranını geçmemek koşuluyla geçerlidir.")
    context = replace(answer().contexts[0], content=text)
    monkeypatch.setattr(pipeline, "get_settings", lambda: _settings(rag_explanations=True))
    monkeypatch.setattr(pipeline, "create_provider", lambda **_: SimpleNamespace(name="qwen", model="test-only"))
    monkeypatch.setattr(pipeline, "try_fast_statute", lambda **_: [context])
    for name in ("pause_embeddings", "resume_embeddings", "unload_ollama_model", "verify_relevant_pending_statute"):
        monkeypatch.setattr(pipeline, name, lambda *_, **__: None)
    monkeypatch.setattr(pipeline, "generate_grounded_answer", lambda *_, **__: pytest.fail("Calculator must not ask a language model"))
    monkeypatch.setattr(explanation, "explain_verified_answer", lambda *_, **__: pytest.fail("Unnecessary extra model call"))
    answer_cache.clear()
    try:
        # A legal-limit question still needs its verified statutory basis;
        # pure user-supplied percentage arithmetic has a separate nonlegal route.
        request = AIAnswerRequest(question="18 bin kira için %20 artışın yasal sınırı nedir?")
        result, _ = asyncio.run(pipeline.execute_answer(request, None))
        assert result.grounded and result.answer == text + " [K1]"
        assert "21.600 TL" in result.summary[0] and len(result.citations) == 1
        assert result.provider == "calculation" and result.model == "decimal+verified-basis-v1"
        cached, _ = asyncio.run(pipeline.execute_answer(request, None))
        assert cached.from_cache and cached.summary == result.summary and cached.provider == "calculation"
    finally:
        answer_cache.clear()
