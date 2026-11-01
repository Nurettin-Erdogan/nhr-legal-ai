from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class KdkDecision:
    external_id: str
    decision_no: str
    decision_date: date
    decision_type: str
    title: str
    raw_text: str
    content_hash: str
    source_url: str
    complaint_no: str | None = None
    complaint_date: date | None = None
    publication_date: date | None = None
    subject: str | None = None
    category: str | None = None
    subcategory: str | None = None
    complained_institution: str | None = None
    fetched_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
