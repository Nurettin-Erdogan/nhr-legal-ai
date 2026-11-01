"""Danıştay liste kaydını doğrulanmış karar modeline dönüştürür."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ingestion.text import html_to_text, normalize_text
from ingestion.yargitay.models import CourtDecision
from ingestion.yargitay.parser import build_title

from .portal import (
    BASE_URL,
    DanistayPortalError,
    PortalDecisionRow,
    document_url,
    parse_portal_date,
    portal_external_id,
)


@dataclass(slots=True)
class ScraperConfig:
    keyword: str = ""
    chamber: str = ""
    decision_date_from: date | None = None
    decision_date_to: date | None = None
    max_decisions: int = 30
    output_dir: Path = Path("data/raw/danistay")
    page_size: int = 20
    delay_seconds: float = 2.0
    max_retries: int = 3
    start_page: int = 1


def search_filters(config: ScraperConfig, *, page_number: int, page_size: int) -> dict[str, Any]:
    return {
        "daire": config.chamber.strip(),
        "esasYil": "",
        "esasIlkSiraNo": "",
        "esasSonSiraNo": "",
        "kararYil": "",
        "kararIlkSiraNo": "",
        "kararSonSiraNo": "",
        "baslangicTarihi": (
            config.decision_date_from.strftime("%d.%m.%Y") if config.decision_date_from else ""
        ),
        "bitisTarihi": (
            config.decision_date_to.strftime("%d.%m.%Y") if config.decision_date_to else ""
        ),
        "mevzuatNumarasi": "",
        "mevzuatAdi": "",
        "madde": "",
        "siralama": "3",
        "siralamaDirection": "desc",
        "pageSize": page_size,
        "pageNumber": page_number,
    }


class _HiddenContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if self.depth:
            self.depth += 1
        elif tag.casefold() == "p" and attrs_map.get("id") == "hiddencontent":
            self.depth = 1

    def handle_endtag(self, _tag: str) -> None:
        if self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)


def extract_decision_text(document_html: str) -> str:
    parser = _HiddenContentParser()
    parser.feed(document_html)
    parser.close()
    embedded_html = "".join(parser.parts).strip()
    if not embedded_html:
        raise DanistayPortalError("Danıştay karar sayfasında hiddencontent bulunamadı")
    text = normalize_text(html_to_text(embedded_html))
    if not text:
        raise DanistayPortalError("Danıştay karar metni ayrıştırılamadı")
    return text


def decision_from_portal_row(
    row: PortalDecisionRow,
    document_html: str,
    *,
    base_url: str = BASE_URL,
    scraped_at: datetime | None = None,
) -> CourtDecision:
    required = {
        "doküman kimliği": row.document_id,
        "daire/kurul": row.chamber,
        "esas no": row.docket_no,
        "karar no": row.decision_no,
        "karar tarihi": row.decision_date,
    }
    missing = [label for label, value in required.items() if not value]
    if missing:
        raise DanistayPortalError(f"Danıştay liste kaydında eksik alanlar: {', '.join(missing)}")
    decision_date = parse_portal_date(row.decision_date)
    if decision_date is None:
        raise DanistayPortalError(f"Danıştay karar tarihi ayrıştırılamadı: {row.decision_date}")
    body = extract_decision_text(document_html)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return CourtDecision(
        court_name="Danıştay",
        chamber=row.chamber,
        docket_no=row.docket_no,
        decision_no=row.decision_no,
        decision_date=decision_date,
        title=build_title("Danıştay", row.chamber, row.docket_no, row.decision_no, decision_date),
        raw_text=body,
        external_id=portal_external_id(row.document_id),
        content_hash=digest,
        source_url=document_url(row.document_id, base_url=base_url),
        scraped_at=scraped_at or datetime.now(UTC),
        metadata={
            "source": "karararama.danistay.gov.tr",
            "source_adapter": "danistay",
            "source_document_id": row.document_id,
            "canonical_source_name": "Danıştay Karar Arama",
            "ingestion_method": "danistay_public_json_http",
            "search_keyword": row.keyword,
            "header": {
                "daire": row.chamber,
                "esas_no": row.docket_no,
                "karar_no": row.decision_no,
                "karar_tarihi": row.decision_date,
            },
        },
    )
