"""UYAP UDF metin çıkarma: gerçek yapı (CDATA), güvenlik sınırları ve belge işleme hattı."""

from __future__ import annotations

import io
import zipfile

import pytest

from api import udf
from api.document_processing import DocumentProcessingError, process_document
from api.udf import UdfError, extract_udf_text
from api.uyap_meta import extract_text_sample, parse_uyap_meta

# UDF'de belge metni kök <content> içinde CDATA'dır; paragraf içindeki <content> yalnız offset taşır.
_REAL_STRUCTURE = (
    '<?xml version="1.0" encoding="UTF-8" ?>'
    '<template format_id="1.8">'
    "<content><![CDATA[İstanbul 3. Asliye Hukuk Mahkemesi 2024/123 Esas\n"
    "Davacı işçi kıdem tazminatı talep etmektedir. Tarih: 15.03.2025\n\n"
    "SONUÇ VE İSTEM: davanın kabulü]]></content>"
    '<properties><pageFormat mediaSizeName="1"/></properties>'
    '<elements resolver="hvl-default">'
    '<paragraph Alignment="0"><content startOffset="0" length="40" family="Times New Roman"/></paragraph>'
    "</elements></template>"
)


def _udf(xml: str | bytes, name: str = "content.xml") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, xml)
    return buffer.getvalue()


def test_text_is_read_from_the_cdata_section_not_stripped_with_the_tags():
    text = extract_udf_text(_udf(_REAL_STRUCTURE))

    assert "kıdem tazminatı talep" in text
    assert "SONUÇ VE İSTEM" in text
    assert "startOffset" not in text and "Times New Roman" not in text


def test_metadata_is_found_from_a_real_udf_structure():
    sample = extract_text_sample("karar.udf", _udf(_REAL_STRUCTURE))

    meta = parse_uyap_meta("karar.udf", sample)

    assert meta["uyap_file_no"] == "2024/123"
    assert meta["doc_date"] == "2025-03-15"
    assert "Asliye Hukuk" in (meta["uyap_birim"] or "")


def test_older_layout_without_a_content_child_falls_back_to_text_nodes():
    assert "Merhaba dilekçe" in extract_udf_text(_udf("<doc><p>Merhaba dilekçe</p></doc>"))


def test_limit_truncates_output():
    assert len(extract_udf_text(_udf(_REAL_STRUCTURE), limit=10)) == 10


@pytest.mark.parametrize(
    "payload",
    [
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">]><x>&a;&a;</x>',
        b"<!doctype html><x/>",
    ],
)
def test_entity_declarations_are_rejected_before_parsing(payload):
    with pytest.raises(UdfError, match="güvenli olmayan"):
        extract_udf_text(_udf(payload))


def test_oversized_content_xml_is_rejected(monkeypatch):
    monkeypatch.setattr(udf, "MAX_CONTENT_XML_BYTES", 100)

    with pytest.raises(UdfError, match="boyutu aşıyor"):
        extract_udf_text(_udf("<a>" + "x" * 500 + "</a>"))


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"not a zip", "arşiv değil"),
        (_udf("<a/>", name="baska.xml"), "content.xml bulunamadı"),
        (_udf("<a><b></a>"), "ayrıştırılamadı"),
    ],
)
def test_unreadable_udf_raises_a_user_facing_error(data, message):
    with pytest.raises(UdfError, match=message):
        extract_udf_text(data)


def test_udf_goes_through_the_document_pipeline_and_is_chunked():
    processed = process_document("karar.udf", _udf(_REAL_STRUCTURE))

    assert processed.extension == ".udf"
    assert processed.chunks and "kıdem tazminatı" in processed.chunks[0].content


def test_udf_without_text_is_not_marked_ready():
    with pytest.raises(DocumentProcessingError, match="işlenebilir metin"):
        process_document("bos.udf", _udf("<template><content><![CDATA[   ]]></content></template>"))


def test_non_udf_bytes_with_udf_extension_are_rejected():
    with pytest.raises(DocumentProcessingError, match="UDF değil"):
        process_document("sahte.udf", b"plain text")


@pytest.mark.parametrize("name", ["tarama.tif", "foto.JPG", "imza.png"])
def test_images_get_an_explicit_ocr_message_instead_of_a_silent_empty_document(name):
    with pytest.raises(DocumentProcessingError, match="OCR"):
        process_document(name, b"\x89PNG....")
