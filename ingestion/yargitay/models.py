"""Yargıtay kararlarının modüller arası ortak veri modeli."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class CourtDecision:
    """Ayrıştırılmış tek bir mahkeme kararı.

    `external_id` mahkeme, daire, esas ve karar numarasından türetilir; hem disk
    arşivinde hem de `legal_sources` tablosunda tekilleştirme anahtarıdır.
    """

    court_name: str
    chamber: str | None
    docket_no: str
    decision_no: str
    decision_date: date | None
    title: str
    raw_text: str
    external_id: str
    content_hash: str
    source_url: str | None = None
    scraped_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "external_id": self.external_id,
            "court_name": self.court_name,
            "chamber": self.chamber,
            "docket_no": self.docket_no,
            "decision_no": self.decision_no,
            "decision_date": self.decision_date.isoformat() if self.decision_date else None,
            "title": self.title,
            "raw_text": self.raw_text,
            "content_hash": self.content_hash,
            "source_url": self.source_url,
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> CourtDecision:
        decision_date = payload.get("decision_date")
        scraped_at = payload.get("scraped_at")

        return cls(
            court_name=payload["court_name"],
            chamber=payload.get("chamber"),
            docket_no=payload["docket_no"],
            decision_no=payload["decision_no"],
            decision_date=date.fromisoformat(decision_date) if decision_date else None,
            title=payload["title"],
            raw_text=payload["raw_text"],
            external_id=payload["external_id"],
            content_hash=payload["content_hash"],
            source_url=payload.get("source_url"),
            scraped_at=datetime.fromisoformat(scraped_at) if scraped_at else None,
            metadata=payload.get("metadata") or {},
        )
