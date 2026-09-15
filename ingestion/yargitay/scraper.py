from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .archive import DecisionArchive
from .models import CourtDecision
from .parser import build_title, normalize_text
from .portal import (
    BASE_URL,
    CaptchaRequiredError,
    PortalDecisionRow,
    PortalError,
    YargitayPortalClient,
    document_url,
    html_to_text,
    parse_portal_date,
    portal_external_id,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScraperConfig:
    keyword: str
    chamber: str
    decision_date_from: date | None = None
    decision_date_to: date | None = None
    max_decisions: int = 50
    output_dir: Path = Path("data/yargitay")
    page_size: int = 20
    delay_seconds: float = 1.5
    timeout_seconds: float = 30
    max_retries: int = 3
    refresh_existing: bool = False
    start_page: int = 1


@dataclass(slots=True)
class ScrapeStats:
    processed: int = 0
    saved: int = 0
    duplicates: int = 0
    failed: int = 0
    pages: int = 0
    records_filtered: int = 0


def _search_filters(config: ScraperConfig, *, page_number: int, page_size: int) -> dict[str, Any]:
    chamber_field = "birimYrgKurulDaire"
    if "hukuk" in config.chamber.casefold():
        chamber_field = "birimYrgHukukDaire"
    elif "ceza" in config.chamber.casefold():
        chamber_field = "birimYrgCezaDaire"

    filters: dict[str, Any] = {
        "arananKelime": config.keyword.strip(),
        "birimYrgKurulDaire": "",
        "birimYrgHukukDaire": "",
        "birimYrgCezaDaire": "",
        "esasYil": "",
        "esasIlkSiraNo": "",
        "esasSonSiraNo": "",
        "kararYil": "",
        "kararIlkSiraNo": "",
        "kararSonSiraNo": "",
        "baslangicTarihi": "",
        "bitisTarihi": "",
        # Portal radio values: 1=esas no, 2=karar no, 3=karar tarihi.
        "siralama": 3,
        "siralamaDirection": "desc",
        "pageSize": page_size,
        "pageNumber": page_number,
    }
    if config.decision_date_from:
        filters["baslangicTarihi"] = config.decision_date_from.strftime("%d.%m.%Y")
    if config.decision_date_to:
        filters["bitisTarihi"] = config.decision_date_to.strftime("%d.%m.%Y")
    filters[chamber_field] = config.chamber.strip()
    return filters


def decision_from_portal_row(
    row: PortalDecisionRow,
    document_html: str,
    *,
    base_url: str = BASE_URL,
    scraped_at: datetime | None = None,
) -> CourtDecision:
    required = {
        "dokuman kimligi": row.document_id,
        "daire": row.chamber,
        "esas no": row.docket_no,
        "karar no": row.decision_no,
        "karar tarihi": row.decision_date,
    }
    missing = [label for label, value in required.items() if not value]
    if missing:
        raise PortalError(f"Karar liste kaydinda eksik alanlar var: {', '.join(missing)}")

    body = normalize_text(html_to_text(document_html))
    if not body:
        raise PortalError(f"Karar metni HTML'den ayristirilamadi: {row.document_id}")

    decision_date = parse_portal_date(row.decision_date)
    if decision_date is None:
        raise PortalError(f"Karar tarihi ayristirilamadi: {row.decision_date}")
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return CourtDecision(
        court_name="Yargıtay",
        chamber=row.chamber,
        docket_no=row.docket_no,
        decision_no=row.decision_no,
        decision_date=decision_date,
        title=build_title("Yargıtay", row.chamber, row.docket_no, row.decision_no, decision_date),
        raw_text=body,
        external_id=portal_external_id(row.document_id),
        content_hash=content_hash,
        source_url=document_url(row.document_id, base_url=base_url),
        scraped_at=scraped_at or datetime.now(UTC),
        metadata={
            "source": "karararama.yargitay.gov.tr",
            "source_document_id": row.document_id,
            "search_keyword": row.keyword,
            "header": {
                "daire": row.chamber,
                "esas_no": row.docket_no,
                "karar_no": row.decision_no,
                "karar_tarihi": row.decision_date,
            },
        },
    )


class YargitayScraper:
    def __init__(self, config: ScraperConfig, *, client: YargitayPortalClient | None = None) -> None:
        if config.max_decisions <= 0:
            raise ValueError("max_decisions pozitif olmalidir")
        if config.page_size <= 0:
            raise ValueError("page_size pozitif olmalidir")
        if not config.keyword.strip() and not config.chamber.strip():
            raise ValueError("En az bir arama kelimesi veya daire verilmelidir")
        if (
            config.decision_date_from
            and config.decision_date_to
            and config.decision_date_from > config.decision_date_to
        ):
            raise ValueError("Başlangıç tarihi bitiş tarihinden sonra olamaz")
        self.config = config
        self.archive = DecisionArchive(config.output_dir)
        self.client = client or YargitayPortalClient(
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
            retry_backoff_seconds=max(1.0, config.delay_seconds),
        )

    async def _pause(self) -> None:
        if self.config.delay_seconds > 0:
            await asyncio.sleep(self.config.delay_seconds)

    async def run(self) -> ScrapeStats:
        stats = ScrapeStats()
        first_page_size = min(self.config.page_size, self.config.max_decisions)
        initial_filters = _search_filters(self.config, page_number=1, page_size=first_page_size)
        await asyncio.to_thread(self.client.begin_detailed_search, initial_filters)

        page_number = max(1, self.config.start_page)
        while stats.processed < self.config.max_decisions:
            remaining = self.config.max_decisions - stats.processed
            page_size = min(self.config.page_size, remaining)
            filters = _search_filters(self.config, page_number=page_number, page_size=page_size)
            page = await asyncio.to_thread(self.client.search_page, filters)
            stats.pages += 1
            stats.records_filtered = page.records_filtered
            if not page.rows:
                break

            for row in page.rows[:remaining]:
                stats.processed += 1
                if not row.document_id:
                    stats.failed += 1
                    continue

                external_id = portal_external_id(row.document_id)
                if self.archive.contains(external_id) and not self.config.refresh_existing:
                    stats.duplicates += 1
                    continue

                try:
                    await self._pause()
                    document_html = await asyncio.to_thread(self.client.fetch_document_html, row.document_id)
                    decision = decision_from_portal_row(
                        row,
                        document_html,
                        base_url=self.client.base_url,
                    )
                    if self.archive.save(decision):
                        stats.saved += 1
                    else:
                        stats.duplicates += 1
                except CaptchaRequiredError:
                    stats.failed += 1
                    raise
                except PortalError as exc:
                    stats.failed += 1
                    logger.warning("Karar alinamadi: %s | %s", row.document_id, exc)

            if stats.processed >= self.config.max_decisions:
                break
            if page.records_filtered and page_number * page_size >= page.records_filtered:
                break
            page_number += 1
            await self._pause()

        return stats
