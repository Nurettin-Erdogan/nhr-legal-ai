from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from docx import Document as DocxDocument
from pypdf import PdfReader

from api.ocr import OcrTooLarge, OcrUnavailable, ocr_image_pages, ocr_pdf_pages
from api.udf import UdfError, extract_udf_text
from ingestion.yargitay.chunking import chunk_text


class DocumentProcessingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExtractedSection:
    content: str
    page_number: int | None = None
    section_title: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessedChunk:
    index: int
    content: str
    content_hash: str
    page_number: int | None
    section_title: str | None


@dataclass(frozen=True, slots=True)
class ProcessedDocument:
    extension: str
    mime_type: str
    checksum_sha256: str
    chunks: tuple[ProcessedChunk, ...]
    # Metin OCR ile okundu: okuma hataları olabilir, arayüzde belirtilmelidir.
    ocr: bool = False


_SUPPORTED_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".html": "text/html",
    ".udf": "application/vnd.uyap.udf",
    ".odt": "application/vnd.oasis.opendocument.text",
}
_IMAGE_TYPES = {
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def safe_file_name(file_name: str | None) -> str:
    name = (file_name or "belge").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = "".join(character for character in name if character >= " " and character != "\x7f")
    if not name:
        name = "belge"
    if len(name) > 240:
        suffix = Path(name).suffix[:16]
        name = name[: 240 - len(suffix)].rstrip() + suffix
    return name


_GLYPH_PLACEHOLDER_RE = re.compile(r"/gid\d+")


def is_readable_text(text: str) -> bool:
    """Çıkarılan metin gerçekten okunabilir mi?

    Özel yazı tipi kodlamalı PDF'lerde (gerçek bir UYAP PDF'inde görüldü) metin katmanı yoktur;
    okuyucu her harf yerine `/gid00001` gibi glif numarası döndürür. Böyle çıktı boş değildir ama
    arama için anlamsızdır. Glif yer tutucuları metnin büyük kısmıysa ya da harf oranı çok düşükse
    okunamaz sayılır.
    """
    compact = "".join(text.split())
    if not compact:
        return False
    placeholders = sum(len(match) for match in _GLYPH_PLACEHOLDER_RE.findall(compact))
    if placeholders / len(compact) >= 0.2:
        return False
    return sum(character.isalpha() for character in compact) / len(compact) >= 0.25


class OcrRequired(DocumentProcessingError):
    """Belge OCR gerektiriyor ama bu çağrıda OCR ertelendi (arka planda çalıştırılmalı)."""


# OCR kipleri: "off" hiç çalıştırma (senkron yüklemeler), "defer" gerekirse OcrRequired fırlat
# (soru anındaki hızlı yol; ağır iş arka plana bırakılır), "run" gerekiyorsa çalıştır.
_OCR_MIN_PAGE_CHARS = 20


def _has_images(page) -> bool:
    try:
        return bool(page.images)
    except Exception:  # noqa: BLE001 - görüntü listelenemezse taranmış sayfa varsay (OCR denenir)
        return True


def _usable_ocr_text(text: str) -> bool:
    return len(text.strip()) >= _OCR_MIN_PAGE_CHARS and is_readable_text(text)


def _extract_pdf(data: bytes, ocr: str = "off") -> tuple[list[ExtractedSection], bool]:
    """PDF sayfalarını okur; (bölümler, OCR kullanıldı mı) döndürür.

    Metin katmanı olan okunabilir sayfalar olduğu gibi alınır. Metni olmayan ama görüntü içeren
    (taranmış) sayfalar ile çöp metin üreten (özel yazı tipi kodlaması, `/gid00001…`) sayfalar
    OCR gerektirir. Gerçekten boş sayfalar atlanır.
    """
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise DocumentProcessingError("Parolalı PDF dosyaları henüz desteklenmiyor.")
        pages = [
            ((page.extract_text() or "").strip(), _has_images(page)) for page in reader.pages
        ]
    except DocumentProcessingError:
        raise
    except Exception as exc:
        raise DocumentProcessingError("PDF dosyası okunamadı veya bozuk.") from exc

    readable = {
        number: text for number, (text, _) in enumerate(pages, start=1) if text and is_readable_text(text)
    }
    needs_ocr = [
        number
        for number, (text, has_images) in enumerate(pages, start=1)
        if number not in readable and (text or has_images)
    ]

    ocr_used = False
    ocr_failure = ""
    if needs_ocr and ocr == "defer":
        raise OcrRequired("Belge OCR gerektiriyor; arka planda işlenecek.")
    if needs_ocr and ocr == "run":
        try:
            for number, text in ocr_pdf_pages(data, needs_ocr).items():
                if _usable_ocr_text(text):
                    readable[number] = text
                    ocr_used = True
        except (OcrUnavailable, OcrTooLarge) as exc:
            ocr_failure = str(exc)

    if not readable:
        if ocr_failure:
            raise DocumentProcessingError(f"PDF'in metni okunamadı; OCR yapılamadı: {ocr_failure}")
        if needs_ocr and ocr == "run":
            raise DocumentProcessingError(
                "PDF'in metni okunamadı: OCR ile de okunabilir metin çıkmadı; belge aranamaz."
            )
        if needs_ocr:
            raise DocumentProcessingError(
                "PDF'in metni okunamadı: belge taranmış ya da özel bir yazı tipi kodlaması kullanıyor. "
                "Bu yüklemede OCR çalıştırılmadı; belge aranamaz."
            )
        raise DocumentProcessingError("Bu PDF metin içermiyor; belge aranamaz.")
    sections = [
        ExtractedSection(content=readable[number], page_number=number) for number in sorted(readable)
    ]
    return sections, ocr_used


def _extract_image(data: bytes, ocr: str) -> tuple[list[ExtractedSection], bool]:
    if ocr == "defer":
        raise OcrRequired("Görüntü OCR gerektiriyor; arka planda işlenecek.")
    if ocr != "run":
        raise DocumentProcessingError(
            "Görüntü dosyaları metin içermez; bu işlemde OCR çalıştırılmadı, belge aranamaz."
        )
    try:
        pages = ocr_image_pages(data)
    except (OcrUnavailable, OcrTooLarge) as exc:
        raise DocumentProcessingError(f"Görüntü OCR ile okunamadı: {exc}") from exc
    sections = [
        ExtractedSection(content=text, page_number=number)
        for number, text in pages
        if _usable_ocr_text(text)
    ]
    if not sections:
        raise DocumentProcessingError(
            "Görüntü OCR ile okundu ama okunabilir metin çıkmadı; belge aranamaz."
        )
    return sections, True


def _extract_docx(data: bytes) -> list[ExtractedSection]:
    try:
        with ZipFile(BytesIO(data)) as archive:
            if "word/document.xml" not in archive.namelist():
                raise DocumentProcessingError("Dosya geçerli bir DOCX belgesi değil.")
        document = DocxDocument(BytesIO(data))
    except DocumentProcessingError:
        raise
    except (BadZipFile, KeyError, ValueError, OSError) as exc:
        raise DocumentProcessingError("DOCX dosyası okunamadı veya bozuk.") from exc

    sections: list[ExtractedSection] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            sections.append(
                ExtractedSection(content="\n\n".join(buffer), section_title=heading)
            )
            buffer.clear()

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        if paragraph.style and paragraph.style.name.lower().startswith("heading"):
            flush()
            heading = text
        else:
            buffer.append(text)

    table_text = []
    for table in document.tables:
        for row in table.rows:
            values = [cell.text.strip() for cell in row.cells]
            if any(values):
                table_text.append(" | ".join(values))
    if table_text:
        buffer.append("\n".join(table_text))
    flush()

    if not sections:
        raise DocumentProcessingError("DOCX belgesinde işlenebilir metin bulunamadı.")
    return sections


def _extract_txt(data: bytes) -> list[ExtractedSection]:
    try:
        text = data.decode("utf-8-sig").strip()
    except UnicodeDecodeError as exc:
        raise DocumentProcessingError("TXT dosyası UTF-8 kodlamasında olmalıdır.") from exc
    if not text:
        raise DocumentProcessingError("TXT belgesi boş.")
    return [ExtractedSection(content=text)]


def _extract_html(data: bytes) -> list[ExtractedSection]:
    from ingestion.text import decode_html_bytes, html_to_text

    if b"<" not in data[:4096] or b"\x00" in data[:4096]:
        raise DocumentProcessingError("HTML uzantılı dosyanın içeriği HTML değil.")
    text = html_to_text(decode_html_bytes(data)).strip()
    if not text:
        raise DocumentProcessingError("HTML belgesinde işlenebilir metin bulunamadı.")
    return [ExtractedSection(content=text)]


def _extract_udf(data: bytes) -> list[ExtractedSection]:
    try:
        text = extract_udf_text(data).strip()
    except UdfError as exc:
        raise DocumentProcessingError(str(exc)) from exc
    if not text:
        raise DocumentProcessingError("UDF belgesinde işlenebilir metin bulunamadı.")
    return [ExtractedSection(content=text)]


def process_document(file_name: str, data: bytes, *, ocr: str = "off") -> ProcessedDocument:
    """Belgeden aranabilir parçalar üretir.

    `ocr`: "off" (varsayılan; senkron yüklemelerde OCR çalıştırılmaz), "defer" (OCR gerekirse
    `OcrRequired` fırlatılır, çağıran arka planda yeniden dener) ya da "run" (gerekirse OCR yapılır).
    OCR ile okunan belge `ProcessedDocument.ocr` ile işaretlenir; okuma hataları olabilir.
    """
    if ocr not in ("off", "defer", "run"):
        raise ValueError(f"Geçersiz OCR kipi: {ocr}")
    extension = Path(file_name).suffix.lower()
    if extension not in _SUPPORTED_TYPES and extension not in _IMAGE_TYPES:
        raise DocumentProcessingError("Yalnız PDF, DOCX, UDF, ODT, TXT, HTML ve görüntü belgeleri desteklenir.")
    if not data:
        raise DocumentProcessingError("Yüklenen dosya boş.")

    ocr_used = False
    if extension in _IMAGE_TYPES:
        sections, ocr_used = _extract_image(data, ocr)
    elif extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise DocumentProcessingError("Dosya uzantısı PDF olsa da içerik PDF değil.")
        sections, ocr_used = _extract_pdf(data, ocr)
    elif extension == ".docx":
        if not data.startswith(b"PK"):
            raise DocumentProcessingError("Dosya uzantısı DOCX olsa da içerik DOCX değil.")
        sections = _extract_docx(data)
    elif extension in (".udf", ".odt"):
        if not data.startswith(b"PK"):
            raise DocumentProcessingError(f"Dosya uzantısı {extension[1:].upper()} olsa da içerik {extension[1:].upper()} değil.")
        # UDF ve ODT, metni content.xml içinde taşıyan zip arşividir (UYAP ön izleme evrakı ODT gelir).
        sections = _extract_udf(data)
    elif extension == ".html":
        sections = _extract_html(data)
    else:
        if b"\x00" in data[:4096]:
            raise DocumentProcessingError("Dosya uzantısı TXT olsa da içerik metin değil.")
        sections = _extract_txt(data)

    chunks: list[ProcessedChunk] = []
    for section in sections:
        for chunk in chunk_text(section.content):
            chunks.append(
                ProcessedChunk(
                    index=len(chunks),
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    page_number=section.page_number,
                    section_title=section.section_title,
                )
            )
    if not chunks:
        raise DocumentProcessingError("Belgeden aranabilir metin parçası üretilemedi.")

    return ProcessedDocument(
        extension=extension,
        mime_type=_SUPPORTED_TYPES.get(extension) or _IMAGE_TYPES[extension],
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        chunks=tuple(chunks),
        ocr=ocr_used,
    )


def store_document_file(
    storage_root: str, user_id: str, document_id: str, extension: str, data: bytes
) -> tuple[str, Path]:
    root = Path(storage_root).resolve()
    user_directory = (root / user_id).resolve()
    if root != user_directory and root not in user_directory.parents:
        raise DocumentProcessingError("Belge saklama yolu güvenli değil.")
    user_directory.mkdir(parents=True, exist_ok=True)

    relative_key = Path(user_id) / f"{document_id}{extension}"
    destination = (root / relative_key).resolve()
    if root not in destination.parents:
        raise DocumentProcessingError("Belge saklama yolu güvenli değil.")

    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return relative_key.as_posix(), destination
