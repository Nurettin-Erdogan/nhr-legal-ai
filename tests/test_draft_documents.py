"""Belge Hazırla: olgu kaynağı ve KONU satırı."""

from __future__ import annotations

from api import draft_documents


def test_a_long_subject_is_used_as_the_users_own_facts_when_no_details_are_given():
    subject = (
        "Kıdem ve ihbar tazminatı talepli işçi alacağı davası. Davalı: ABC İnşaat A.Ş. Müvekkil 5 yıl 3 ay çalıştı, "
        "son brüt ücret 32.000 TL, haksız fesih."
    )
    assert draft_documents.facts_source(subject, "") == " ".join(subject.split())
    # kısa konu satırı olgu sayılmaz (model uydurmasın)
    assert not draft_documents.has_facts(draft_documents.facts_source("Kira tespit davası", ""))
    # ayrıntı doluysa o kullanılır
    assert draft_documents.facts_source(subject, "İş sözleşmesi 12.03.2019 tarihinde imzalandı ve 28.06.2024'te feshedildi.") != subject


def test_subject_line_is_the_first_sentence_and_has_no_trailing_period():
    subject = "Kıdem ve ihbar tazminatı talepli işçi alacağı davası. Davalı: ABC İnşaat A.Ş. Müvekkil 5 yıl 3 ay çalıştı."
    assert draft_documents.short_subject(subject) == "Kıdem ve ihbar tazminatı talepli işçi alacağı davası"
    long_one = "kira " * 80
    assert len(draft_documents.short_subject(long_one)) <= 160
