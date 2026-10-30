"""Konu → madde ipuçları: sorunun yazılışı (ek, ünlü düşmesi) konuyu kaçırmamalı, başka konuya da taşmamalı.

Ölçüldü (2026-10-09): "Yıllık ücretli izne hak kazanma şartları" ("izin" → "izne") ve "İş uyuşmazlıklarında … arabulucuya
başvurmak zorunlu mudur?" soruları konu tablosuyla eşleşmiyor, cevap adaylarına ilgili madde girmiyordu.
"""

from __future__ import annotations

import pytest

from api import statute_hints


def _articles(question: str) -> list[tuple[str, str]]:
    return [(hint.law_no, hint.article_no) for hint in statute_hints.suggest(question)]


@pytest.mark.parametrize("question", [
    "Kira uyuşmazlığında zorunlu arabuluculuk nasıl işler?",
    "Komşu hakkından doğan davada arabulucuya başvuru gerekir mi?",
    "İşverenle uyuşmazlıkta arabuluculuk süreci nedir?",
])
def test_mediation_procedure_has_its_own_verified_lookup_addresses(question):
    articles = _articles(question)
    assert ("6325", "18/A") in articles and ("6325", "18/B") in articles


@pytest.mark.parametrize(
    "question",
    [
        "Yıllık ücretli izne hak kazanma şartları nelerdir?",
        "Yıllık izni kullandırmayan işveren ne öder?",
        "Yıllık izin ücreti nasıl ispatlanır?",
        "Yıllık ücretli izin süresi kaç gündür?",
    ],
)
def test_annual_leave_is_recognised_with_and_without_the_dropped_vowel(question):
    assert _articles(question)[:2] == [("4857", "53"), ("4857", "59")]


@pytest.mark.parametrize(
    "question",
    [
        "İş uyuşmazlıklarında dava açmadan önce arabulucuya başvurmak zorunlu mudur?",
        "İşçi alacağı davasından önce arabulucu şart mı?",
        "İşe iade için arabulucuya ne zaman başvurulur?",
        "İş davasında arabuluculuk dava şartı mıdır?",
    ],
)
def test_mediation_in_labour_disputes_points_to_the_labour_courts_act(question):
    assert ("7036", "3") in _articles(question)


@pytest.mark.parametrize(
    "question",
    [
        "Ticari davada arabulucuya başvuru zorunlu mu?",  # başka kanun (6102 m. 5/A); tabloda yok, uydurulmaz
        "Kira uyuşmazlığında arabulucu şart mı?",
        "Arabuluculuk ücreti nasıl belirlenir?",
    ],
)
def test_mediation_outside_labour_law_is_not_sent_to_the_labour_courts_act(question):
    assert ("7036", "3") not in _articles(question)


def test_every_hint_names_words_its_article_must_contain():
    for topic in statute_hints.TOPICS:
        assert topic.groups and all(group for group in topic.groups), topic.name
        for hint in topic.hints:
            assert hint.law_no.isdigit() and hint.article_no and hint.expect, (topic.name, hint)


@pytest.mark.parametrize("question", [
    "Mirası reddetmek istiyorum, süresi ne kadar?",
    "Mirasın reddi için kaç gün süre var?",
])
def test_rejecting_an_inheritance_points_to_the_three_month_rule(question):
    assert ("4721", "606") in _articles(question)


@pytest.mark.parametrize("question", [
    "İşveren maaşımı geç ödüyor, gecikme faizi isteyebilir miyim?",
    "Ücret alacağında faiz hangi tarihten itibaren işler?",
])
def test_late_wage_interest_points_to_the_wage_and_default_interest_articles(question):
    articles = _articles(question)
    assert ("4857", "34") in articles and ("6098", "120") in articles


def test_interest_on_a_loan_is_not_taken_for_a_wage_question():
    assert ("4857", "34") not in _articles("Banka kredisinde faiz oranı nasıl belirlenir?")


def test_labour_claim_limitation_question_gets_the_borclar_kanunu_articles():
    assert {("6098", "146"), ("6098", "147")} <= set(_articles("İşçilik alacaklarında zamanaşımı süresi nedir?"))


def test_asking_when_severance_is_lost_brings_the_employers_just_cause_article():
    articles = set(_articles("Kıdem ve ihbar tazminatını aynı anda alabilir miyim? Hangi durumlarda alamam?"))
    assert {("1475", "14"), ("4857", "17"), ("4857", "25")} <= articles
def test_procedural_facet_hints_are_independent_of_the_deadline_article():
    from api.statute_hints import suggest
    found = {(h.law_no, h.article_no) for h in suggest('Belediyenin ruhsat ret işlemine karşı görevli mahkeme hangisi?')}
    assert ('2576', '5') in found


def test_unsiged_debt_and_objection_retrieve_distinct_procedural_provisions():
    from api.statute_hints import suggest
    found = {(h.law_no, h.article_no) for h in suggest('Senet yok, para borcu için ilamsız icra takibi ve itiraz yolları nelerdir?')}
    assert {('2004', a) for a in ('42', '58', '66', '67', '68')} <= found
