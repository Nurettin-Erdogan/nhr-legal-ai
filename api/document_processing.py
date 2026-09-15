from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from docx import Document as DocxDocument
from pypdf import PdfReader

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


_SUPPORTED_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
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


def _extract_pdf(data: bytes) -> list[ExtractedSection]:
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise DocumentProcessingError("Parolalı PDF dosyaları henüz desteklenmiyor.")
        sections = [
            ExtractedSection(content=(page.extract_text() or "").strip(), page_number=index)
            for index, page in enumerate(reader.pages, start=1)
        ]
    except DocumentProcessingError:
        raise
    except Exception as exc:
        raise DocumentProcessingError("PDF dosyası okunamadı veya bozuk.") from exc

    if not any(section.content for section in sections):
        raise DocumentProcessingError(
            "Bu PDF metin içermiyor veya taranmış görünüyor; OCR henüz desteklenmiyor."
        )
    return [section for section in sections if section.content]


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


def process_document(file_name: str, data: bytes) -> ProcessedDocument:
    extension = Path(file_name).suffix.lower()
    if extension not in _SUPPORTED_TYPES:
        raise DocumentProcessingError("Yalnız PDF, DOCX ve TXT belgeleri desteklenir.")
    if not data:
        raise DocumentProcessingError("Yüklenen dosya boş.")

    if extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise DocumentProcessingError("Dosya uzantısı PDF olsa da içerik PDF değil.")
        sections = _extract_pdf(data)
    elif extension == ".docx":
        if not data.startswith(b"PK"):
            raise DocumentProcessingError("Dosya uzantısı DOCX olsa da içerik DOCX değil.")
        sections = _extract_docx(data)
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
        mime_type=_SUPPORTED_TYPES[extension],
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        chunks=tuple(chunks),
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
