"""Mevzuat gezgini: kanun adı ya da kısaltmasıyla madde atfı ("TBK 344", "anayasa 38", "iş kanunu 17")."""

from __future__ import annotations

import pytest

from api.legislation_browse import Law, fold, parse_named_reference, search_laws


def _law(no: str, name: str, kind: str = "law", articles: int = 100) -> Law:
    return Law(no, name, kind, articles, None, None, fold(name))


LAWS = [
    _law("6098", "TÜRK BORÇLAR KANUNU"),
    _law("2709", "TÜRKİYE CUMHURİYETİ ANAYASASI", "constitution"),
    _law("4857", "İŞ KANUNU"),
    _law("6552", "İŞ KANUNU İLE BAZI KANUN VE KANUN HÜKMÜNDE KARARNAMELERDE DEĞİŞİKLİK YAPILMASI", articles=76),
    _law("4721", "TÜRK MEDENİ KANUNU"),
    _law("5271", "CEZA MUHAKEMESİ KANUNU"),
    _law("6698", "KİŞİSEL VERİLERİN KORUNMASI KANUNU"),
    _law("x1", "KİRA SÖZLEŞMELERİ YÖNETMELİĞİ", "regulation"),
]


@pytest.mark.parametrize(
    ("query", "law_no", "article"),
    [
        ("TBK 344", "6098", "344"),
        ("tbk m. 344", "6098", "344"),
        ("türk borçlar kanunu 344", "6098", "344"),
        ("anayasa 38", "2709", "38"),
        ("Anayasa m. 38", "2709", "38"),
        ("iş kanunu 17", "4857", "17"),
        ("İş Kanunu madde 17", "4857", "17"),
        ("iş kanunu 17. madde", "4857", "17"),
        ("ceza muhakemesi kanunu 100", "5271", "100"),
        ("türk medeni kanunu 683", "4721", "683"),
        ("kvkk 12", "6698", "12"),
        ("tbk 344/A", "6098", "344/A"),
    ],
)
def test_law_name_or_abbreviation_with_article_number_resolves(query, law_no, article):
    law, number = parse_named_reference(LAWS, query)
    assert (law.law_no, number) == (law_no, article)
    assert [found.law_no for found in search_laws(LAWS, query, None)] == [law_no]


@pytest.mark.parametrize("query", ["kira 2024", "kıdem tazminatı", "4857", "madde 5", "medeni 683", "kira sözleşmeleri yönetmeliği 5"])
def test_queries_that_are_not_a_named_article_reference_fall_through(query):
    assert parse_named_reference(LAWS, query) is None


def test_ambiguous_abbreviation_is_not_guessed():
    assert parse_named_reference(LAWS, "tmk 683") is None
