"""OCR: taranmış PDF, görüntü ve çöp metin üreten PDF sayfaları. Birim testleri Tesseract gerektirmez."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from api import document_processing, ocr
from api.document_processing import DocumentProcessingError, OcrRequired, process_document
from api.ocr import OcrTooLarge, OcrUnavailable

GOOD = (
    "Davacı işçi kıdem tazminatı talep etmektedir. Bilirkişi raporunda kıdem tazminatı "
    "340.000 TL olarak hesaplanmıştır."
)
GARBAGE = "/gid00001" * 100


class _Page:
    def __init__(self, text: str, images: bool) -> None:
        self._text, self.images = text, ([object()] if images else [])

    def extract_text(self) -> str:
        return self._text


class _Reader:
    is_encrypted = False

    def __init__(self, pages) -> None:
        self.pages = [_Page(text, images) for text, images in pages]


def _pdf(monkeypatch, pages) -> bytes:
    monkeypatch.setattr(document_processing, "PdfReader", lambda _data: _Reader(pages))
    return b"%PDF-1.4 sahte"


@pytest.fixture
def ocr_calls(monkeypatch):
    calls: dict[str, list] = {"pdf": [], "image": []}

    def fake_pdf(data, pages):
        calls["pdf"].append(list(pages))
        return {number: GOOD for number in pages}

    def fake_image(data):
        calls["image"].append(len(data))
        return [(1, GOOD)]

    monkeypatch.setattr(document_processing, "ocr_pdf_pages", fake_pdf)
    monkeypatch.setattr(document_processing, "ocr_image_pages", fake_image)
    return calls


def test_image_without_ocr_is_rejected_and_says_ocr_was_not_run():
    with pytest.raises(DocumentProcessingError, match="OCR"):
        process_document("tarama.png", b"\x89PNG....")


def test_image_defers_when_asked_and_reads_when_allowed(ocr_calls):
    with pytest.raises(OcrRequired):
        process_document("tarama.png", b"\x89PNG....", ocr="defer")
    assert ocr_calls["image"] == []  # ertelenen işte OCR çalışmaz

    processed = process_document("tarama.png", b"\x89PNG....", ocr="run")
    assert processed.ocr is True
    assert processed.mime_type == "image/png"
    assert "340.000 TL" in " ".join(chunk.content for chunk in processed.chunks)


def test_scanned_pdf_pages_are_read_with_ocr(monkeypatch, ocr_calls):
    data = _pdf(monkeypatch, [("", True), ("", True)])  # metin yok, sayfa görüntü içeriyor
    with pytest.raises(OcrRequired):
        process_document("tarama.pdf", data, ocr="defer")
    with pytest.raises(DocumentProcessingError, match="OCR çalıştırılmadı"):
        process_document("tarama.pdf", data)  # varsayılan "off": sessizce hazır olmaz

    processed = process_document("tarama.pdf", data, ocr="run")
    assert processed.ocr is True
    assert {chunk.page_number for chunk in processed.chunks} == {1, 2}
    assert ocr_calls["pdf"] == [[1, 2]]


def test_only_pages_that_need_ocr_are_sent_and_blank_pages_are_skipped(monkeypatch, ocr_calls):
    # 1: normal metin, 2: taranmış, 3: tamamen boş (görüntü yok), 4: çöp metin (özel yazı tipi)
    data = _pdf(monkeypatch, [(GOOD, False), ("", True), ("", False), (GARBAGE, False)])
    processed = process_document("karisik.pdf", data, ocr="run")
    assert ocr_calls["pdf"] == [[2, 4]]
    assert {chunk.page_number for chunk in processed.chunks} == {1, 2, 4}
    assert processed.ocr is True
    assert all("/gid" not in chunk.content for chunk in processed.chunks)


def test_a_normal_pdf_never_triggers_ocr(monkeypatch, ocr_calls):
    data = _pdf(monkeypatch, [(GOOD, False), (GOOD + " İkinci sayfa.", False)])
    processed = process_document("normal.pdf", data, ocr="run")
    assert processed.ocr is False
    assert ocr_calls["pdf"] == []


def test_ocr_output_that_is_still_garbage_is_not_indexed(monkeypatch):
    monkeypatch.setattr(document_processing, "ocr_pdf_pages", lambda data, pages: {n: "~~ // ## 1 2" for n in pages})
    data = _pdf(monkeypatch, [("", True)])
    with pytest.raises(DocumentProcessingError, match="OCR ile de okunabilir metin çıkmadı"):
        process_document("kotu.pdf", data, ocr="run")


@pytest.mark.parametrize("failure", [OcrUnavailable("Tesseract OCR kurulu değil."), OcrTooLarge("En çok 40 sayfa.")])
def test_unavailable_or_oversized_ocr_fails_with_a_visible_reason(monkeypatch, failure):
    def boom(data, pages):
        raise failure

    monkeypatch.setattr(document_processing, "ocr_pdf_pages", boom)
    data = _pdf(monkeypatch, [("", True)])
    with pytest.raises(DocumentProcessingError) as error:
        process_document("tarama.pdf", data, ocr="run")
    assert str(failure) in str(error.value)


def test_invalid_ocr_mode_is_rejected():
    with pytest.raises(ValueError):
        process_document("a.txt", b"merhaba dunya", ocr="always")


def test_ocr_requires_the_turkish_language_pack(monkeypatch):
    """Yalnız İngilizce OCR ç/ş/ğ/ı yanlış okur: `tur` yoksa OCR kullanılamaz sayılır."""
    import types

    fake = types.SimpleNamespace(
        pytesseract=types.SimpleNamespace(tesseract_cmd=""),
        get_languages=lambda config="": ["eng", "osd"],
    )
    monkeypatch.setitem(__import__("sys").modules, "pytesseract", fake)
    monkeypatch.setattr(ocr, "find_tesseract", lambda: r"C:\sahte\tesseract.exe")
    available, reason = ocr.ocr_status()
    assert available is False
    assert "tur.traineddata" in reason


# --- Gerçek Tesseract ile uçtan uca (kurulu değilse atlanır) --------------------------------

_FONT = Path(r"C:\Windows\Fonts\arial.ttf")
_real = ocr.ocr_status()[0]


@pytest.mark.skipif(not _real or not _FONT.is_file(), reason="Tesseract (tur) veya Arial yazı tipi yok")
def test_real_tesseract_reads_turkish_characters_from_an_image():
    from PIL import Image, ImageDraw, ImageFont

    picture = Image.new("RGB", (1500, 260), "white")
    draw = ImageDraw.Draw(picture)
    font = ImageFont.truetype(str(_FONT), 52)
    draw.text((40, 30), "Kıdem tazminatı 340.000 TL olarak", font=font, fill="black")
    draw.text((40, 130), "hesaplanmıştır. İşçi çalışmıştır.", font=font, fill="black")
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")

    processed = process_document("bilirkisi_taramasi.png", buffer.getvalue(), ocr="run")
    text = " ".join(chunk.content for chunk in processed.chunks)

    assert processed.ocr is True
    for expected in ("Kıdem", "tazminatı", "340.000", "hesaplanmıştır", "çalışmıştır"):
        assert expected in text, f"{expected!r} OCR çıktısında yok: {text!r}"


@pytest.mark.skipif(not _real, reason="Tesseract (tur) yok")
def test_real_tesseract_status_reports_ready():
    assert ocr.ocr_status() == (True, "")
    assert os.environ.get("TESSDATA_PREFIX") or ocr.find_tesseract()
