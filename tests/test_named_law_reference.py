"""Kanunu ADIYLA anan açık madde soruları: "Anayasanın 36. maddesi", "TBK m. 344", "İİK m. 67".

Önceki davranış: kanun numarası yazılmamışsa açık madde sorusu tanınmıyor, üç haneli madde numarası ("TBK 344. madde")
kanun numarası sanılıp olmayan bir "344 sayılı kanun" aranıyordu.
"""

from __future__ import annotations

import pytest

from api.ai.retrieval import named_law_numbers, question_article_numbers, question_law_numbers


@pytest.mark.parametrize(
    "question,law,article",
    [
        ("Anayasanın 36. maddesi adil yargılanma hakkını nasıl düzenler?", "2709", "36"),
        ("ANAYASANIN 36. MADDESİ NEDİR", "2709", "36"),
        ("TBK 344. madde ne diyor?", "6098", "344"),
        ("Türk Borçlar Kanunu madde 344 kira artışını nasıl sınırlar?", "6098", "344"),
        ("TBK m. 344", "6098", "344"),
        ("İİK m.67 itirazın iptali süresi", "2004", "67"),
        ("İcra ve İflas Kanununun 67. maddesi", "2004", "67"),
        ("İş Kanunu md. 18 neyi düzenler?", "4857", "18"),
        ("HMK madde 127 cevap süresi", "6100", "127"),
        ("CMK 273. madde istinaf süresi", "5271", "273"),
        ("İYUK m. 45 istinaf", "2577", "45"),
        ("KVKK madde 5 açık rıza", "6698", "5"),
        ("Türk Medeni Kanunu 166. madde", "4721", "166"),
        ("2023 yılında TBK m. 344 nasıl uygulanır?", "6098", "344"),  # yıl, kanun numarası sanılmaz
    ],
)
def test_a_named_law_with_an_article_number_is_an_explicit_reference(question, law, article):
    assert question_law_numbers(question)[0] == law
    assert question_article_numbers(question)[0] == article


@pytest.mark.parametrize(
    "question,expected",
    [
        ("4857 sayılı İş Kanunu madde 18 neyi düzenler?", ("4857",)),
        ("1475 sayılı İş Kanunu madde 14", ("1475",)),  # eski İş Kanunu: ad eşlemesi (4857) açık numarayı EZMEZ
        ("1475 İş Kanunu m. 14", ("1475",)),
        ("6098 sayılı kanun madde 315", ("6098", "315")),
        ("2004 sayılı Kanun madde 67", ("2004",)),  # yıl gibi görünse de "sayılı" ile kanundur
    ],
)
def test_an_explicit_law_number_always_wins_over_the_name(question, expected):
    assert question_law_numbers(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "İş Kanununda eşit davranma ilkesi nasıl korunur?",  # madde numarası yok: konu sorusu, açık madde sorusu değil
        "Anayasa Mahkemesine bireysel başvuru süresi nedir?",
        "Kıdem tazminatına hak kazanma şartları nelerdir?",
    ],
)
def test_without_an_article_number_the_name_is_not_turned_into_a_law_number(question):
    assert question_law_numbers(question) == ()


def test_ambiguous_or_other_laws_are_not_guessed():
    assert named_law_numbers("Anayasa Mahkemesi kararı 36. madde") == ()  # "Anayasa Mahkemesi" Anayasa değildir
    assert named_law_numbers("Deniz İş Kanunu madde 14") == ()
    assert named_law_numbers("Basın İş Kanunu madde 6") == ()
    assert named_law_numbers("TMK m. 166") == ()  # Medeni Kanun mu, Terörle Mücadele Kanunu mu: bilinemez
    assert question_law_numbers("madde 344 ne der?") == ("344",)  # ad yoksa eski davranış korunur


def test_short_article_notation_is_read_but_case_numbers_and_units_are_not():
    assert question_article_numbers("TBK m. 344 ve m.345") == ("344", "345")
    assert question_article_numbers("md. 18") == ("18",)
    assert question_article_numbers("E. 2024/1234 K. 2025/5678") == ()
    assert question_article_numbers("dönüm. 5 ve km. 12") == ()  # "m." bir sözcüğün sonuysa madde değildir
    assert question_article_numbers("m. 2024") == ()  # dört haneli sayı madde numarası değildir
    assert question_article_numbers("18. madde ve madde 20") == ("18", "20")


def test_first_named_law_in_the_question_comes_first():
    assert named_law_numbers("HMK ve İİK bakımından m. 5") == ("6100", "2004")
