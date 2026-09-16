from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from ingestion.aym.portal import AymDecisionRow, AymPortalError
from ingestion.text import content_hash, normalize_text
from ingestion.yargitay.models import CourtDecision

MAX_UDF_BYTES = 20 * 1024 * 1024
MAX_XML_BYTES = 30 * 1024 * 1024


def extract_udf_text(raw: bytes) -> str:
    if len(raw) > MAX_UDF_BYTES:
        raise AymPortalError("AYM UDF dosyası güvenli boyut sınırını aşıyor")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            names = archive.namelist()
            if names != ["content.xml"]:
                raise AymPortalError("AYM UDF arşivi yalnız content.xml içermelidir")
            info = archive.getinfo("content.xml")
            if info.file_size > MAX_XML_BYTES:
                raise AymPortalError("AYM UDF XML içeriği güvenli boyut sınırını aşıyor")
            xml = archive.read(info)
    except AymPortalError:
        raise
    except (BadZipFile, KeyError, OSError) as exc:
        raise AymPortalError("AYM UDF arşivi okunamadı") from exc

    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise AymPortalError("AYM UDF XML içinde desteklenmeyen entity tanımı var")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise AymPortalError("AYM UDF content.xml ayrıştırılamadı") from exc

    # UYAP UDF'de asıl belge metni doğrudan bir veya birkaç `content` metin
    # düğümünde durur; `paragraph` elemanları aynı metne offset/length ile
    # referans verir. Düğümleri belge sırasıyla birleştirmek satır sonlarını
    # korur ve offset'leri Unicode üzerinde yeniden hesaplama ihtiyacını önler.
    text_nodes = [
        element.text
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "content"
        and element.text
        and element.text.strip()
    ]
    text = normalize_text("\n\n".join(text_nodes))
    if len(text) < 100:
        raise AymPortalError("AYM UDF içinde yeterli karar metni bulunamadı")
    return text


def decision_from_udf(
    row: AymDecisionRow,
    udf: bytes,
    *,
    download_url: str,
    fetched_at: datetime | None = None,
) -> CourtDecision:
    if not row.decision_date:
        raise AymPortalError("AYM karar tarihi eksik")
    raw_text = extract_udf_text(udf)
    compact = "".join(raw_text.split())
    if row.application_no not in raw_text and row.application_no.replace("/", "") not in compact:
        raise AymPortalError("AYM UDF başvuru numarası arama künyesiyle eşleşmiyor")
    fetched_at = fetched_at or datetime.now(UTC)
    title = (
        f"AYM Bireysel Başvuru, B. No: {row.application_no} "
        f"({row.decision_date.strftime('%d.%m.%Y')})"
    )
    metadata = {
        "source_adapter": "aym",
        "canonical_source_name": "Anayasa Mahkemesi Kararlar Bilgi Bankası",
        "ingestion_method": "aym_public_json_udf",
        "source_document_id": row.official_id,
        "application_no": row.application_no,
        "application_date": row.application_date.isoformat() if row.application_date else None,
        "decision_date": row.decision_date.isoformat(),
        "publication_date": row.publication_date.isoformat() if row.publication_date else None,
        "decision_type": row.decision_type,
        "outcome": row.outcome or None,
        "subject": row.subject or None,
        "confidential": row.confidential,
        "official_download_url": download_url,
    }
    return CourtDecision(
        court_name="Anayasa Mahkemesi",
        chamber=row.chamber or None,
        docket_no=row.application_no,
        decision_no=None,
        decision_date=row.decision_date,
        title=title,
        raw_text=raw_text,
        external_id=row.external_id,
        content_hash=content_hash(raw_text),
        source_url=row.source_url,
        scraped_at=fetched_at,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )
