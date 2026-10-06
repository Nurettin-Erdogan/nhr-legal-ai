"""Kullanıcı belgesi cümleleri mevzuat konu kapısıyla elenmemeli (UYAP/dava belgeleri).

`passage_relevant` bir hukuki konu tanıdığında (ör. "kıdem tazminatı") cümlenin o konunun tüm terim
gruplarını içermesini ister; bu, mevzuat ve karar pasajları içindir. Bilirkişi raporundaki somut olgu
cümlesi bu terimleri taşımadığından eleniyor ve model hiç çağrılmadan "yeterli bilgi yok" deniyordu.
"""

from __future__ import annotations

from uuid import uuid4

from api.ai.evidence_selection import evidence_candidates
from api.ai.rag import RAGContext
from api.ai.relevance import document_passage_relevant, documents_answer, passage_relevant
from api.ai.verification import prune_rejected_lines, verify_answer

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


def test_a_short_fact_sentence_answers_one_part_of_a_two_part_question():
    """Canlıda "kira bedeli ne kadar ve depozito tutarı nedir?" sorusunda depozito cümlesi eleniyor, cevap yarım kalıyordu."""
    question = "Aylık kira bedeli ne kadar ve depozito tutarı nedir?"
    assert document_passage_relevant(question, "Depozito 37.000 TL'dir.")
    assert document_passage_relevant(question, "Aylık kira bedeli 18.500 TL olup her ayın 5'ine kadar ödenir.")
    # Sayı içermeyen kısa cümle tek sözcük eşleşmesiyle alınmaz.
    assert not document_passage_relevant(question, "Kiracı, kiralananı alt kiraya veremez.")
    assert not document_passage_relevant(question, "İhtilaf halinde Ankara mahkemeleri yetkilidir.")


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


# --- Dava sohbeti: cevabı belgede yazan soru ve tek satır yüzünden reddedilmeyen cevap -------------------------------

CONTRACT = (
    "KİRA SÖZLEŞMESİ\n\nKiraya veren: Ayşe Demir. Kiracı: Mehmet Kaya.\n\n"
    "Kira başlangıç tarihi 01.03.2024, süre 1 yıldır. Aylık kira bedeli 18.500 TL olup her ayın 5'ine kadar ödenir.\n\n"
    "Depozito 37.000 TL'dir. Kira artışı TÜFE on iki aylık ortalaması oranında yapılır.\n\n"
    "Kiracı, kiralananı alt kiraya veremez. İhtilaf halinde Ankara mahkemeleri yetkilidir."
)
TWO_PART = "Aylık kira bedeli ne kadar ve depozito tutarı nedir?"


def _named(title: str, content: str) -> RAGContext:
    from dataclasses import replace

    return replace(_context("document", content, "user_document"), title=title)


def test_documents_answer_a_fact_question_only_when_a_sentence_carries_its_topic():
    contract = _named("kira-sozlesmesi.docx", CONTRACT)
    assert documents_answer("Depozito tutarı nedir?", [contract])
    assert documents_answer(TWO_PART, [contract])
    assert not documents_answer("Bilirkişi kıdem tazminatını ne kadar hesaplamış?", [contract])
    assert not documents_answer("Depozito tutarı nedir?", [])
    # Konu sözcüğü olmayan soruda karar verilemez: belge eşleşmiş sayılmaz.
    assert not documents_answer("Nedir?", [contract])
    # Tek ortak sözcük ("süre") belgeyi cevabın kaynağı yapmaz.
    assert not documents_answer("Arabuluculuk başvuru süresi kaç gün?", [contract])


def test_a_citation_marker_does_not_make_a_short_fact_sentence_look_long():
    line = "Kira başlangıç tarihi 01.03.2024, süre 1 yıldır."
    assert document_passage_relevant(TWO_PART, line) == document_passage_relevant(TWO_PART, f"{line} [K1]")


def test_one_rejected_line_no_longer_discards_the_whole_document_answer():
    document = _context("document", CONTRACT, "user_document")
    draft = (
        "Aylık kira bedeli 18.500 TL olup her ayın 5'ine kadar ödenir. [K1]\n\n"
        "İhtilaf halinde Ankara mahkemeleri yetkilidir. [K1]\n\n"
        "Depozito 37.000 TL'dir. [K1]"
    )
    first = verify_answer(draft, [document], question=TWO_PART)
    assert not first.grounded and all("mahkemeleri" in claim for claim in first.unsupported_claims)

    pruned = prune_rejected_lines(draft, first)
    assert pruned == "Aylık kira bedeli 18.500 TL olup her ayın 5'ine kadar ödenir. [K1]\n\nDepozito 37.000 TL'dir. [K1]"
    assert verify_answer(pruned, [document], question=TWO_PART).grounded


def test_pruning_only_removes_lines_and_never_rescues_an_unsupported_answer():
    document = _context("document", CONTRACT, "user_document")
    # Tek satır ve o da kaynakta olmayan tutarı söylüyor: çıkarılacak başka satır yok, cevap reddedilmiş kalır.
    wrong = "Depozito 99.000 TL'dir. [K1]"
    assert prune_rejected_lines(wrong, verify_answer(wrong, [document], question=TWO_PART)) is None
    # Yanlış tutarlı satır atılır; kalan doğru satır tek başına yeniden doğrulanır.
    mixed = "Depozito 99.000 TL'dir. [K1]\nAylık kira bedeli 18.500 TL olup her ayın 5'ine kadar ödenir. [K1]"
    pruned = prune_rejected_lines(mixed, verify_answer(mixed, [document], question=TWO_PART))
    assert pruned == "Aylık kira bedeli 18.500 TL olup her ayın 5'ine kadar ödenir. [K1]"
    # Var olmayan kaynağa atıf (uydurma işaret) satır çıkararak düzeltilmez.
    invented = "Depozito 37.000 TL'dir. [K1]\nKira artışı yapılır. [K7]"
    assert prune_rejected_lines(invented, verify_answer(invented, [document], question=TWO_PART)) is None
    # Zaten geçerli cevapta yapılacak bir şey yok.
    fine = "Depozito 37.000 TL'dir. [K1]"
    assert prune_rejected_lines(fine, verify_answer(fine, [document], question=TWO_PART)) is None
