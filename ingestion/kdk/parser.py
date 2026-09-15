from __future__ import annotations

from datetime import UTC, date, datetime
from io import BytesIO
from typing import Any

from pypdf import PdfReader

from ingestion.kdk.models import KdkDecision
from ingestion.kdk.portal import KdkPortalError
from ingestion.text import content_hash, normalize_text


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        for pattern in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, pattern).date()
            except ValueError:
                continue
    return None


def extract_pdf_text(raw: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted:
            raise KdkPortalError("KDK PDF şifreli")
        text = normalize_text("\n\n".join(page.extract_text() or "" for page in reader.pages))
    except KdkPortalError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise KdkPortalError(f"KDK PDF metni ayrıştırılamadı: {exc}") from exc
    if len(text) < 50:
        raise KdkPortalError("KDK PDF içinde yeterli metin bulunamadı")
    return text


def decision_from_row(
    row: dict[str, Any],
    pdf: bytes,
    *,
    source_url: str,
    fetched_at: datetime | None = None,
) -> KdkDecision:
    record_id = str(row.get("id") or "").strip()
    document_id = str(row.get("evraK_ID") or "").strip()
    decision_no = str(row.get("karaR_NO") or "").strip()
    decision_type = str(row.get("karaR_TURU") or "").strip()
    decision_date = parse_date(row.get("karaR_TARIH"))
    if not record_id or not document_id or not decision_no or not decision_type or not decision_date:
        raise KdkPortalError("KDK yapılandırılmış karar künyesi eksik")

    raw_text = extract_pdf_text(pdf)
    title = f"KDK, {decision_no} — {decision_type} ({decision_date.strftime('%d.%m.%Y')})"
    complaint_no = str(row.get("sikayeT_NO") or "").strip() or None
    fetched_at = fetched_at or datetime.now(UTC)
    metadata = {
        "source_adapter": "kdk",
        "canonical_source_name": "KDK Kararlar Bilgi Bankası",
        "ingestion_method": "kdk_public_datatables_pdf",
        "source_record_id": record_id,
        "source_document_id": document_id,
        "decision_no": decision_no,
        "decision_date": decision_date.isoformat(),
        "decision_type": decision_type,
        "complaint_no": complaint_no,
        "complaint_date": (parse_date(row.get("sikayeT_TARIH")) or None),
        "publication_date": (parse_date(row.get("karaR_YAYINLAMA_TARIHI")) or None),
        "subject": str(row.get("evraK_KONU") or "").strip() or None,
        "category": str(row.get("sikayeT_KONU") or "").strip() or None,
        "subcategory": str(row.get("sikayeT_ALT_KONU") or "").strip() or None,
        "complained_institution": str(row.get("sikayeT_EDILEN_KURUM") or "").strip() or None,
        "official_pdf_path": str(row.get("karaR_YAYIN_URL") or "").strip(),
    }
    metadata = {
        key: value.isoformat() if isinstance(value, date) else value
        for key, value in metadata.items()
        if value not in (None, "")
    }
    return KdkDecision(
        external_id=f"kdk:{record_id}",
        decision_no=decision_no,
        decision_date=decision_date,
        decision_type=decision_type,
        title=title,
        raw_text=raw_text,
        content_hash=content_hash(raw_text),
        source_url=source_url,
        complaint_no=complaint_no,
        complaint_date=parse_date(row.get("sikayeT_TARIH")),
        publication_date=parse_date(row.get("karaR_YAYINLAMA_TARIHI")),
        subject=metadata.get("subject"),
        category=metadata.get("category"),
        subcategory=metadata.get("subcategory"),
        complained_institution=metadata.get("complained_institution"),
        fetched_at=fetched_at,
        metadata=metadata,
    )
