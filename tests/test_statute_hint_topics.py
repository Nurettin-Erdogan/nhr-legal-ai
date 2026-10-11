"""Konu → madde ipuçları: sorunun yazılışı (ek, ünlü düşmesi) konuyu kaçırmamalı, başka konuya da taşmamalı.

Ölçüldü (2026-10-09): "Yıllık ücretli izne hak kazanma şartları" ("izin" → "izne") ve "İş uyuşmazlıklarında … arabulucuya
başvurmak zorunlu mudur?" soruları konu tablosuyla eşleşmiyor, cevap adaylarına ilgili madde girmiyordu.
"""

from __future__ import annotations

import pytest

from api import statute_hints


def _articles(question: str) -> list[tuple[str, str]]:
    return [(hint.law_no, hint.article_no) for hint in statute_hints.suggest(question)]


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
