"""Mevzuat maddelerinin modüller arası ortak veri modeli."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class LegislationRecord:
    """Tek bir mevzuat maddesi.

    RAG birimi kanunun tamamı değil maddedir: atıf `İş Kanunu m. 25`
    biçiminde durur. `external_id` kanun no + madde no doğal anahtarıdır;
    portal `mevzuatId` / `maddeId` değerleri metadata'da saklanır.
    """

    record_type: str
    legislation_type: str
    law_name: str
    law_no: str
    article_no: str
    article_title: str | None
    title: str
    raw_text: str
    external_id: str
    content_hash: str
    source_url: str | None = None
    official_gazette_no: str | None = None
    official_gazette_date: date | None = None
    version_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    amendment_source: str | None = None
    scraped_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "legislation_type": self.legislation_type,
            "law_name": self.law_name,
            "law_no": self.law_no,
            "article_no": self.article_no,
            "article_title": self.article_title,
            "title": self.title,
            "raw_text": self.raw_text,
            "external_id": self.external_id,
            "content_hash": self.content_hash,
            "source_url": self.source_url,
            "official_gazette_no": self.official_gazette_no,
            "official_gazette_date": (
                self.official_gazette_date.isoformat() if self.official_gazette_date else None
            ),
            "version_date": self.version_date.isoformat() if self.version_date else None,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "amendment_source": self.amendment_source,
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> LegislationRecord:
        gazette_date = payload.get("official_gazette_date")
        version_date = payload.get("version_date")
        scraped_at = payload.get("scraped_at")
        effective_from = payload.get("effective_from")
        effective_to = payload.get("effective_to")
        return cls(
            record_type=payload.get("record_type") or "legislation",
            legislation_type=payload["legislation_type"],
            law_name=payload["law_name"],
            law_no=str(payload["law_no"]),
            article_no=str(payload["article_no"]),
            article_title=payload.get("article_title"),
            title=payload["title"],
            raw_text=payload["raw_text"],
            external_id=payload["external_id"],
            content_hash=payload["content_hash"],
            source_url=payload.get("source_url"),
            official_gazette_no=payload.get("official_gazette_no"),
            official_gazette_date=(
                date.fromisoformat(gazette_date) if gazette_date else None
            ),
            version_date=date.fromisoformat(version_date) if version_date else None,
            effective_from=date.fromisoformat(effective_from) if effective_from else None,
            effective_to=date.fromisoformat(effective_to) if effective_to else None,
            amendment_source=payload.get("amendment_source"),
            scraped_at=datetime.fromisoformat(scraped_at) if scraped_at else None,
            metadata=payload.get("metadata") or {},
        )
