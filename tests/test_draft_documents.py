"""Belge Hazırla: olgu kaynağı ve KONU satırı."""

from __future__ import annotations

from api import draft_documents
import pytest
from pydantic import ValidationError


def test_contract_keeps_all_subject_conditions():
    subject = "Web sitesi hazırlanması. Alan adı ve hosting bedelleri dahil değildir."
    text = draft_documents.build_document("sozlesme", None, ["A", "B"], subject, [], draft_documents.Legal())
    assert subject in text


def test_fallback_does_not_split_company_abbreviations():
    sentences = draft_documents.fallback_paragraphs("Hizmet", "Örnek Yazılım Ltd. web sitesini hazırlayacaktır. Teslim 30 gün içinde yapılacaktır.")
    assert sentences == ["Örnek Yazılım Ltd. web sitesini hazırlayacaktır.", "Teslim 30 gün içinde yapılacaktır."]


def test_fallback_and_verified_paragraphs_do_not_cut_after_six():
    sentences = [f"Belge {i} teslim edildi." for i in range(1, 10)]
    assert draft_documents.fallback_paragraphs("Teslim", " ".join(sentences)) == sentences
    given = " ".join(sentences)
    result = draft_documents.verified_paragraphs("\n".join(f"{i}. {s}" for i, s in enumerate(sentences, 1)), given)
    assert len(result) == 9


def test_notice_keeps_explicit_demands_period_and_consequence():
    text = draft_documents.build_document("ihtarname", None, ["A", "B"], "Ödeme", [], draft_documents.Legal(),
        {"notice_demand": "20.000 TL ödenmesi", "notice_period": "Tebliğden itibaren 30 gün",
         "notice_consequence": "Sözleşmenin feshedileceği bildirilmektedir.", "effective_date": "02.11.2026"})
    for value in ["20.000 TL ödenmesi", "Tebliğden itibaren 30 gün", "Sözleşmenin feshedileceği", "02.11.2026"]:
        assert value in text
    assert "her türlü masraf ve zarardan sorumlu" not in text


def test_petition_uses_explicit_authority_evidence_and_requests_without_inventing_relief():
    text = draft_documents.build_document("dilekce", None, ["Ayşe", "Ali"], "Alacak", [], draft_documents.Legal(),
        {"authority": "Ankara İş Mahkemesine", "evidence": "Banka dekontu", "requests": "20.000 TL alacağın tahsili"})
    assert "Ankara İş Mahkemesine" in text
    assert "Banka dekontu" in text
    assert "20.000 TL alacağın tahsili" in text
    assert "yargılama giderleri ve vekâlet ücretinin davalıya" not in text


def test_contract_preserves_user_terms_and_does_not_invent_missing_terms():
    text = draft_documents.build_document("sozlesme", None, ["A", "B"], "Hizmet", [], draft_documents.Legal(),
        {"payment": "Her ay 15.000 TL", "term": "12 ay", "obligations": "A rapor teslim eder."})
    assert "Bedel ve ödeme koşulları:** Her ay 15.000 TL" in text
    assert "Süre:** 12 ay" in text
    assert "Sona erme ve fesih:** […]" in text
    assert "A rapor teslim eder." in text


def test_structured_fields_are_bounded_and_cannot_inject_markdown_headings():
    with pytest.raises(ValidationError):
        draft_documents.DraftFields(payment="a" * 4001)
    with pytest.raises(ValidationError):
        draft_documents.DraftFields(unknown="value")
    text = draft_documents.build_document("sozlesme", None, [], "Konu", [], draft_documents.Legal(),
                                          {"payment": "# Yeni bölüm\n[link](https://example.org)"})
    assert "\\# Yeni bölüm" in text
    assert "\\[link\\]" in text


def test_both_request_paths_accept_the_same_structured_fields():
    from api.office_ai import DocumentRequest
    from api.document_jobs import JobRequest

    fields = {"requests": "Alacağın tahsili", "payment": "10 TL"}
    direct = DocumentRequest(doc_type="dilekce", subject="Alacak", draft_fields=fields)
    queued = JobRequest(module="draft", draft_fields=fields)
    assert direct.draft_fields == queued.draft_fields
    assert queued.model_dump(mode="json")["draft_fields"]["payment"] == "10 TL"


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
