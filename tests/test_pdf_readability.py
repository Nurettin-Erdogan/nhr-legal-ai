"""Okunamayan PDF metni "aranabilir" diye indekslenmemeli.

Gerçek bir UYAP PDF'inde (Adli Yardım Başvuru Formu) özel yazı tipi kodlaması yüzünden okuyucu her
harf yerine `/gid00001` döndürdü; belge 18 parça ile "hazır" sayılıyordu ve arama hiçbir şey bulamazdı.
"""

from __future__ import annotations

import pytest

from api import document_processing
from api.document_processing import DocumentProcessingError, is_readable_text, process_document

GARBAGE = "/gid00001" * 120 + " /gid00005/gid00127/gid00110 " * 20
GOOD = (
    "Adli yardım talebinde bulunan kişi, mahkemeye başvuru dilekçesi ile birlikte gelir durumunu "
    "gösteren belgeleri sunar ve talebinin gerekçesini açıkça belirtir."
)


class _Page:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _Reader:
    is_encrypted = False

    def __init__(self, pages: list[str]) -> None:
        self.pages = [_Page(text) for text in pages]


def _pdf_with_pages(monkeypatch, pages: list[str]) -> bytes:
    monkeypatch.setattr(document_processing, "PdfReader", lambda _data: _Reader(pages))
    return b"%PDF-1.4 sahte"


def test_glyph_placeholder_text_is_not_readable():
    assert not is_readable_text(GARBAGE)
    assert not is_readable_text("   \n ")


def test_normal_turkish_and_numeric_text_is_readable():
    assert is_readable_text(GOOD)
    assert is_readable_text("Kıdem tazminatı 340.000 TL; ihbar tazminatı 85.000 TL.")
    assert is_readable_text("Toplam 12 345,67 | KDV %20 | 2025/412 E.")


def test_pdf_with_only_unreadable_text_is_rejected_with_a_user_visible_reason(monkeypatch):
    data = _pdf_with_pages(monkeypatch, [GARBAGE, GARBAGE])
    with pytest.raises(DocumentProcessingError) as error:
        process_document("adliyardimbasvuru.pdf", data)
    message = str(error.value)
    assert "okunamadı" in message and "aranamaz" in message


def test_unreadable_pages_are_never_silently_dropped_from_a_mixed_pdf(monkeypatch):
    data = _pdf_with_pages(monkeypatch, [GARBAGE, GOOD])
    with pytest.raises(DocumentProcessingError, match="tamamı aranabilir değil"):
        process_document("karisik.pdf", data)


def test_a_normal_pdf_is_unchanged(monkeypatch):
    data = _pdf_with_pages(monkeypatch, [GOOD, GOOD + " İkinci sayfa."])
    processed = process_document("normal.pdf", data)
    assert {chunk.page_number for chunk in processed.chunks} == {1, 2}
