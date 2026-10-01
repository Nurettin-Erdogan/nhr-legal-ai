"""Kullanıcı belgesi cümleleri mevzuat konu kapısıyla elenmemeli (UYAP/dava belgeleri).

`passage_relevant` bir hukuki konu tanıdığında (ör. "kıdem tazminatı") cümlenin o konunun tüm terim
gruplarını içermesini ister; bu, mevzuat ve karar pasajları içindir. Bilirkişi raporundaki somut olgu
cümlesi bu terimleri taşımadığından eleniyor ve model hiç çağrılmadan "yeterli bilgi yok" deniyordu.
"""

from __future__ import annotations

from uuid import uuid4

from api.ai.evidence_selection import evidence_candidates
from api.ai.rag import RAGContext
from api.ai.relevance import document_passage_relevant, passage_relevant
from api.ai.verification import verify_answer

QUESTION = "Bilirkişi kıdem tazminatını ne kadar hesaplamış?"
FACT = "Kıdem tazminatı 8 yıl için 340.000 TL olarak hesaplanmıştır."
UNRELATED = "Davalı şirketin merkezi İstanbul'da bulunmaktadır ve faaliyet göstermektedir."


def _context(source_type: str, content: str, verification: str) -> RAGContext:
    return RAGContext(
        chunk_id=uuid4(),
        source_id=uuid4(),
        source_type=source_type,
        title="bilirkisi_raporu.docx",
        source_url=None,
        authority="Kullanıcı belgesi" if source_type == "document" else None,
        court_name=None,
        chamber=None,
        docket_no=None,
        decision_no=None,
        decision_date=None,
        law_name=None,
        law_no=None,
        article_no=None,
        article_title=None,
        content=content,
        rank=0.5,
        verification=verification,
    )


def test_fact_sentence_in_a_document_is_relevant_to_the_question():
    assert document_passage_relevant(QUESTION, FACT)
    assert passage_relevant(QUESTION, FACT, source_type="document")


def test_unrelated_document_sentence_is_still_rejected():
    assert not document_passage_relevant(QUESTION, UNRELATED)
    assert not passage_relevant(QUESTION, UNRELATED, source_type="document")


def test_statutory_topic_gate_is_unchanged_for_non_document_sources():
    # Aynı cümle bir mevzuat/karar pasajı olsaydı konu kapısından geçmezdi: davranış korunur.
    assert not passage_relevant(QUESTION, FACT)
    assert not passage_relevant(QUESTION, FACT, source_type="legislation")


def test_amount_question_needs_an_amount_in_the_document_sentence():
    question = "Davacının son brüt ücreti kaç lira?"
    assert document_passage_relevant(question, "Davacının son brüt ücreti 42.500 TL'dir.")
    assert not document_passage_relevant(question, "Davacı 8 yıl 1 ay çalışmıştır.")


def test_evidence_is_selected_from_a_user_document_but_not_a_non_document_with_same_text():
    document = _context("document", FACT, "user_document")
    assert [item.text for item in evidence_candidates(QUESTION, [document])] == [FACT]

    decision = _context("court_decision", FACT, "official")
    assert evidence_candidates(QUESTION, [decision]) == []


def test_answer_citing_only_a_document_is_not_flagged_as_off_topic():
    document = _context("document", "BİLİRKİŞİ RAPORU\n\n" + FACT, "user_document")
    # Gerçek akış: cevap kanıt seçicinin döndürdüğü kaynak cümleden aynen alınır (başlık dahil).
    (evidence,) = evidence_candidates(QUESTION, [document])
    verified = verify_answer(f"{evidence.text} [K1]", [document], question=QUESTION)
    assert verified.unsupported_claims == ()
    assert verified.grounded


def test_document_answer_is_still_rejected_when_the_number_is_not_in_the_source():
    document = _context("document", "BİLİRKİŞİ RAPORU\n\n" + FACT, "user_document")
    verified = verify_answer(
        "Bilirkişi kıdem tazminatını 8 yıl için 999.000 TL olarak hesaplamıştır. [K1]",
        [document],
        question=QUESTION,
    )
    assert verified.unsupported_claims, "kaynakta olmayan tutar hâlâ reddedilmeli"
    assert not verified.grounded
