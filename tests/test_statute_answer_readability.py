"""Kanun maddesi cevabının üstündeki doğrudan cevap (2026-10-18): anlaşılır olmalı, ama kaynakta olmayan bilgi yine geçmemeli."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from api import case_summary
from api.ai import statute_summary
from api.ai.numeric_support import numeric_claims_supported, spell_numbers

ARTICLE_344 = (
    "Tarafların yenilenen kira dönemlerinde uygulanacak kira bedeline ilişkin anlaşmaları, bir önceki kira yılında tüketici fiyat "
    "endeksindeki oniki aylık ortalamalara göre değişim oranını geçmemek koşuluyla geçerlidir. Bu kural, bir yıldan daha uzun "
    "süreli kira sözleşmelerinde de uygulanır. Beş yıldan sonra yenilenen kira sözleşmelerinde hâkim emsal kira bedellerini de "
    "göz önüne alır."
)


@pytest.mark.parametrize("text,expected", [
    ("oniki aylık ortalamaya", "12 aylık ortalamaya"),
    ("beş yıldan uzun", "5 yıldan uzun"),
    ("on iki ay", "12 ay"),
    ("yüz yirmi beş gün", "125 gün"),
    ("bir yıl içinde", "1 yıl içinde"),
    ("bir kira yılında", "bir kira yılında"),  # belirtme sözcüğü sayı değildir
    ("binanın altında", "binanın altında"),
])
def test_spelled_out_numbers_become_digits_on_both_sides(text, expected):
    assert spell_numbers(text) == expected


def test_a_digit_matches_the_same_number_written_in_words_but_not_a_different_one():
    assert numeric_claims_supported("Artış 12 aylık ortalamayı geçemez.", ARTICLE_344)
    assert numeric_claims_supported("5 yıldan sonra emsal bedel dikkate alınır.", ARTICLE_344)
    assert not numeric_claims_supported("6 yıldan sonra emsal bedel dikkate alınır.", ARTICLE_344)
    assert not numeric_claims_supported("Artış 24 aylık ortalamayı geçemez.", ARTICLE_344)


def test_the_year_from_the_question_does_not_reject_an_otherwise_supported_answer():
    question = "2026 yılında konut kira artışı nasıl belirlenir?"
    bullet = "2026 yılında kira artışı, 12 aylık TÜFE ortalamasına göre değişim oranını geçemez."
    assert not case_summary.bullet_supported(bullet, ARTICLE_344)  # yıl kaynakta yok
    assert case_summary.bullet_supported(statute_summary.checked_text(bullet, question, ARTICLE_344), ARTICLE_344)
    # Sorudan gelmeyen bir yıl ise yine düşürür.
    other = "2019 yılından beri kira artışı 12 aylık ortalamayı geçemez."
    assert not case_summary.bullet_supported(statute_summary.checked_text(other, question, ARTICLE_344), ARTICLE_344)


@pytest.mark.parametrize("bullet,expected", [
    ("Evet, ev sahibi TÜFE'nin üzerinde zam yapamaz.", "Ev sahibi TÜFE'nin üzerinde zam yapamaz."),
    ("Hayır, artış TÜFE ortalamasını geçemez.", "Hayır, artış TÜFE ortalamasını geçemez."),
    ("Hayır, işveren bildirim yapabilir.", "İşveren bildirim yapabilir."),
    ("Evet, işçi izne hak kazanır.", "Evet, işçi izne hak kazanır."),
    ("İşçi izne hak kazanır.", "İşçi izne hak kazanır."),
])
def test_a_yes_or_no_that_contradicts_its_own_sentence_is_dropped(bullet, expected):
    assert statute_summary.coherent_polarity(bullet) == expected


def _answer(text: str):
    context = SimpleNamespace(source_type="legislation", verification="official", law_no="4857", article_no="53",
                              law_name="İş Kanunu")
    return SimpleNamespace(grounded=True, text=text * 2, contexts=(context,))


def test_a_duration_question_never_gets_a_short_answer_without_any_duration():
    """Kıdem için "ne kadar çalışmak gerekir?" sorusuna yalnız askerlik istisnası kalınca kısa cevap gösterilmez."""
    source = ("Yıllık ücretli izin süresi hizmet süresi bir yıldan beş yıla kadar olanlara on dört günden az olamaz. "
              "Askerlik nedeniyle işten ayrılanlara izin ücreti ödenir. ") * 3

    async def generate(system, prompt):
        if "denetçisisin" in system:
            return '{"results":[true]}'
        return "- Askerlik nedeniyle işten ayrılanlara izin ücreti ödenir."

    assert asyncio.run(statute_summary.build("Yıllık izin kaç gündür?", _answer(source), generate)) == ()

    async def generate_duration(system, prompt):
        if "denetçisisin" in system:
            return '{"results":[true]}'
        return "- Hizmet süresi bir yıldan beş yıla kadar olanlara izin on dört günden az olamaz."

    bullets = asyncio.run(statute_summary.build("Yıllık izin kaç gündür?", _answer(source), generate_duration))
    assert bullets and "on dört" in bullets[0]


def test_the_model_checker_also_sees_the_question():
    seen = []
    source = ARTICLE_344 * 2

    async def generate(system, prompt):
        if "denetçisisin" in system:
            seen.append(prompt)
            return '{"results":[true]}'
        return "- Hayır, kira bedeline ilişkin anlaşmalar 12 aylık ortalamalara göre değişim oranını geçemez."

    context = SimpleNamespace(source_type="legislation", verification="official", law_no="6098", article_no="344", law_name="TBK")
    answer = SimpleNamespace(grounded=True, text=source, contexts=(context,))
    bullets = asyncio.run(statute_summary.build("Ev sahibi TÜFE'nin üzerinde zam yapabilir mi?", answer, generate))
    assert bullets == ("Hayır, kira bedeline ilişkin anlaşmalar 12 aylık ortalamalara göre değişim oranını geçemez.",)
    assert seen and "TÜFE'nin üzerinde zam yapabilir mi" in seen[0]
