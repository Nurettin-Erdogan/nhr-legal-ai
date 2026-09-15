from __future__ import annotations

from io import BytesIO

import pytest
from docx import Document

from api.document_processing import (
    DocumentProcessingError,
    process_document,
    safe_file_name,
    store_document_file,
)


def test_txt_document_is_validated_and_chunked():
    content = ("İş sözleşmesi ve kıdem tazminatı hakkında örnek metin. " * 80).encode()

    processed = process_document("dilekce.txt", content)

    assert processed.mime_type == "text/plain"
    assert processed.checksum_sha256
    assert len(processed.chunks) >= 2
    assert [chunk.index for chunk in processed.chunks] == list(
        range(len(processed.chunks))
    )


def test_docx_headings_are_kept_as_chunk_metadata():
    document = Document()
    document.add_heading("Olaylar", level=1)
    document.add_paragraph("Davacı işçi iş sözleşmesini haklı nedenle feshetmiştir.")
    output = BytesIO()
    document.save(output)

    processed = process_document("dava.docx", output.getvalue())

    assert processed.chunks[0].section_title == "Olaylar"
    assert "haklı nedenle" in processed.chunks[0].content


def test_scanned_or_empty_pdf_gets_explicit_ocr_error():
    # A structurally invalid/empty PDF must not silently become a ready document.
    with pytest.raises(DocumentProcessingError, match="PDF"):
        process_document("tarama.pdf", b"%PDF-1.4\n%%EOF")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (r"C:\\Users\\someone\\dilekce.txt", "dilekce.txt"),
        ("../../sozlesme.pdf", "sozlesme.pdf"),
    ],
)
def test_file_name_never_keeps_client_path(name: str, expected: str):
    assert safe_file_name(name) == expected


def test_storage_uses_generated_user_and_document_path(tmp_path):
    key, destination = store_document_file(
        str(tmp_path), "user-id", "document-id", ".txt", b"ornek"
    )

    assert key == "user-id/document-id.txt"
    assert destination.read_bytes() == b"ornek"
    assert destination.is_relative_to(tmp_path)


def test_extension_and_content_must_match():
    with pytest.raises(DocumentProcessingError, match="içerik PDF değil"):
        process_document("sahte.pdf", b"normal metin")

    with pytest.raises(DocumentProcessingError, match="Yalnız PDF, DOCX ve TXT"):
        process_document("zararli.exe", b"MZ")
