from io import BytesIO
import stat
from zipfile import ZipFile, ZipInfo

import pytest

from api import document_processing as processing


def zip_bytes(entries):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


def test_archive_keeps_each_members_full_text_and_provenance():
    result = processing.process_document("Ek_1.zip", zip_bytes([("bir/beyan.txt", "Birinci belge içeriği."), ("iki/beyan.txt", "İkinci belge içeriği.")]))
    assert result.extension == ".zip" and result.mime_type == "application/zip"
    assert {chunk.section_title for chunk in result.chunks} == {"bir/beyan.txt", "iki/beyan.txt"}
    assert [chunk.index for chunk in result.chunks] == list(range(len(result.chunks)))
    assert "Birinci belge" in result.chunks[0].content and "İkinci belge" in result.chunks[-1].content


@pytest.mark.parametrize("name", ["../secret.txt", "/secret.txt", "C:/secret.txt", "dir/../../secret.txt", "..\\secret.txt"])
def test_archive_rejects_unsafe_paths_without_extracting_to_disk(name):
    with pytest.raises(processing.DocumentProcessingError, match="güvenli olmayan"):
        processing.process_document("ek.zip", zip_bytes([(name, "Belge.")]))


def test_symlink_encryption_nested_archive_and_broken_zip_are_rejected():
    link = ZipInfo("link.txt")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(processing.DocumentProcessingError, match="güvenli olmayan"):
        processing.process_document("ek.zip", zip_bytes([(link, "target")]))
    for name, data in [("nested.zip", zip_bytes([("a.txt", "Metin")])), ("broken.pdf", b"not a pdf")]:
        with pytest.raises(processing.DocumentProcessingError):
            processing.process_document("ek.zip", zip_bytes([(name, data)]))
    with pytest.raises(processing.DocumentProcessingError, match="bozuk"):
        processing.process_document("ek.zip", b"not a zip")
    encrypted = bytearray(zip_bytes([("a.txt", "Metin")]))
    encrypted[6] |= 1
    encrypted[encrypted.index(b"PK\x01\x02") + 8] |= 1
    with pytest.raises(processing.DocumentProcessingError, match="Parolalı"):
        processing.process_document("ek.zip", bytes(encrypted))


def test_unsupported_or_broken_member_never_yields_a_silently_partial_ready_archive():
    with pytest.raises(processing.DocumentProcessingError, match="desteklenmeyen"):
        processing.process_document("ek.zip", zip_bytes([("good.txt", "Geçerli belge"), ("bad.exe", b"MZ")]))
    with pytest.raises(processing.DocumentProcessingError, match="ZIP eki işlenemedi"):
        processing.process_document("ek.zip", zip_bytes([("good.txt", "Geçerli belge"), ("bad.txt", b"\xff")]))


def test_archive_limits_are_checked_before_members_are_processed(monkeypatch):
    monkeypatch.setattr(processing, "MAX_ARCHIVE_ENTRIES", 1)
    with pytest.raises(processing.DocumentProcessingError, match="sınır"):
        processing.process_document("ek.zip", zip_bytes([("a.txt", "A"), ("b.txt", "B")]))
    monkeypatch.setattr(processing, "MAX_ARCHIVE_ENTRIES", 200)
    monkeypatch.setattr(processing, "MAX_ARCHIVE_EXPANDED_BYTES", 10)
    with pytest.raises(processing.DocumentProcessingError, match="sınır"):
        processing.process_document("ek.zip", zip_bytes([("a.txt", "Uzun metin burada.")]))


def test_ocr_is_deferred_for_the_whole_archive_not_silently_skipped():
    with pytest.raises(processing.OcrRequired):
        processing.process_document("ek.zip", zip_bytes([("a.txt", "Metin"), ("image.png", b"image")]), ocr="defer")
