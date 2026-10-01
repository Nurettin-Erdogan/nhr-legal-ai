"""Rekabet Kurulu karar PDF'ini OfficialDoc'a çevirir."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from io import BytesIO

from pypdf import PdfReader

from ingestion.official_docs import OfficialDoc
from ingestion.rekabet.portal import ListRow, RekabetClient, RekabetError
from ingestion.text import content_hash, normalize_text

MIN_TEXT_CHARS = 300


def parse_date(value: str) -> date | None:
    text = (value or "").strip()
    for pattern in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except ValueError:
            continue
    return None


def pdf_text(raw: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted:
            raise RekabetError("Rekabet PDF şifreli")
        return normalize_text("\n\n".join(page.extract_text() or "" for page in reader.pages))
    except RekabetError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RekabetError(f"Rekabet PDF metni ayrıştırılamadı: {exc}") from exc


def build_doc(row: ListRow, pdf: bytes, *, fetched_at: datetime | None = None) -> OfficialDoc:
    text = pdf_text(pdf)
    if len(text) < MIN_TEXT_CHARS:
        raise RekabetError(f"Rekabet {row.karar_sayisi}: PDF metni çok kısa ({len(text)} karakter, taranmış görüntü olabilir)")
    decision_date = parse_date(row.karar_tarihi)
    if decision_date is None:
        raise RekabetError(f"Rekabet {row.karar_sayisi}: karar tarihi okunamadı ({row.karar_tarihi!r})")
    published = parse_date(row.yayimlanma_tarihi)
    subject = row.konu[:160]
    metadata = {
        "source": "rekabet",
        "karar_id": row.karar_id,
        "karar_sayisi": row.karar_sayisi,
        "karar_turu": row.karar_turu,
        "konu": row.konu,
        "yayimlanma_tarihi": published.isoformat() if published else None,
        "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
        "decision_date": decision_date.isoformat(),
        "provenance": "official_portal",
        "official_verified": True,
        "third_party": False,
    }
    return OfficialDoc(
        external_id=f"rekabet:{row.karar_id}",
        title=f"Rekabet Kurulu, Karar Sayısı {row.karar_sayisi} ({decision_date.strftime('%d.%m.%Y')}) — {subject}",
        raw_text=text,
        content_hash=content_hash(text),
        source_url=RekabetClient.pdf_url(row.karar_id),
        decision_date=decision_date,
        fetched_at=fetched_at or datetime.now().astimezone(),
        metadata=metadata,
    )
