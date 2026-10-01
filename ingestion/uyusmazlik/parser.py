"""Uyuşmazlık Mahkemesi karar PDF'ini OfficialDoc'a çevirir."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from io import BytesIO

from pypdf import PdfReader

from ingestion.official_docs import OfficialDoc
from ingestion.text import content_hash, normalize_text
from ingestion.uyusmazlik.portal import ListRow, UyusmazlikClient, UyusmazlikError, slug

MIN_TEXT_CHARS = 300
_UYAP_HEADER = re.compile(r"UYAP\s+Bili[şs]im\s+Sistemindeki\s+bu\s+dok[üu]mana.*?eri[şs]ebilirsiniz\.?", re.S | re.I)
_BOLUM = re.compile(r"(Hukuk|Ceza)\s+B[öo]l[üu]m[üu]|Genel\s+Kurul", re.I)


def parse_date(value: str) -> date | None:
    text = (value or "").strip()
    for pattern in ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except ValueError:
            continue
    return None


def pdf_text(raw: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted:
            raise UyusmazlikError("Uyuşmazlık PDF şifreli")
        joined = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except UyusmazlikError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise UyusmazlikError(f"Uyuşmazlık PDF metni ayrıştırılamadı: {exc}") from exc
    return normalize_text(_UYAP_HEADER.sub("", joined))


def external_id_for(row: ListRow) -> str:
    stem = re.sub(r"\.pdf$", "", row.pdf_path.rsplit("/", 1)[-1], flags=re.I)
    return f"uyusmazlik:{stem}:{slug(row.karar_no)}"


def build_doc(row: ListRow, pdf: bytes, *, fetched_at: datetime | None = None) -> OfficialDoc:
    text = pdf_text(pdf)
    if len(text) < MIN_TEXT_CHARS:
        raise UyusmazlikError(f"Uyuşmazlık {row.esas_no}: PDF metni çok kısa ({len(text)} karakter, taranmış görüntü olabilir)")
    decision_date = parse_date(row.karar_tarihi)  # portalda tarih bazen yok ya da geçersiz ("Belirtilmemiş", "31/09/2009"); tarih UYDURULMAZ
    match = _BOLUM.search(text[:400])
    bolum = re.sub(r"\s+", " ", match.group(0)).strip() if match else None
    metadata = {
        "source": "uyusmazlik",
        "esas_no": row.esas_no,
        "karar_no": row.karar_no,
        "bolum": bolum,
        "pdf_path": row.pdf_path,
        "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
        "decision_date": decision_date.isoformat() if decision_date else None,
        "decision_date_portal_raw": row.karar_tarihi,
        "provenance": "official_portal",
        "official_verified": True,
        "third_party": False,
    }
    return OfficialDoc(
        external_id=external_id_for(row),
        title=f"Uyuşmazlık Mahkemesi, E. {row.esas_no}, K. {row.karar_no}"
        + (f" ({decision_date.strftime('%d.%m.%Y')})" if decision_date else ""),
        raw_text=text,
        content_hash=content_hash(text),
        source_url=UyusmazlikClient.pdf_url(row.pdf_path),
        decision_date=decision_date,
        fetched_at=fetched_at or datetime.now().astimezone(),
        metadata=metadata,
    )
