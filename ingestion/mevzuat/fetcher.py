"""Bedesten üzerinden mevzuat maddelerini arşive yazar."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ingestion.mevzuat.archive import LegislationArchive
from ingestion.mevzuat.parser import article_external_id, iter_article_nodes, portal_type_name, record_from_article
from ingestion.mevzuat.portal import MevzuatPortalClient, MevzuatPortalError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FetcherConfig:
    law_no: str = ""
    title: str = ""
    types: tuple[str, ...] = ("KANUN",)
    max_documents: int = 5
    max_articles: int = 50
    output_dir: Path = Path("data/mevzuat")
    page_size: int = 10
    delay_seconds: float = 1.0
    timeout_seconds: float = 30
    max_retries: int = 3
    refresh_existing: bool = False


@dataclass(slots=True)
class FetchStats:
    documents: int = 0
    processed: int = 0
    saved: int = 0
    duplicates: int = 0
    failed: int = 0


class MevzuatFetcher:
    def __init__(self, config: FetcherConfig, *, client: MevzuatPortalClient | None = None) -> None:
        if config.max_documents <= 0 or config.max_articles <= 0:
            raise ValueError("max_documents ve max_articles pozitif olmalıdır")
        if not config.law_no.strip() and not config.title.strip():
            raise ValueError("En az bir kanun numarası veya mevzuat adı verilmelidir")
        self.config = config
        self.archive = LegislationArchive(config.output_dir)
        self.client = client or MevzuatPortalClient(
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
        )

    async def _pause(self) -> None:
        if self.config.delay_seconds > 0:
            await asyncio.sleep(self.config.delay_seconds)

    async def run(self) -> FetchStats:
        stats = FetchStats()
        remaining_articles = self.config.max_articles
        page_number = 1
        collected_documents = 0

        while collected_documents < self.config.max_documents and remaining_articles > 0:
            page = await asyncio.to_thread(
                self.client.search_page,
                page_number=page_number,
                page_size=min(self.config.page_size, self.config.max_documents - collected_documents),
                law_no=self.config.law_no.strip() or None,
                title=self.config.title.strip() or None,
                types=self.config.types,
            )
            if not page.documents:
                break

            for document in page.documents:
                if collected_documents >= self.config.max_documents or remaining_articles <= 0:
                    break
                collected_documents += 1
                stats.documents += 1
                mevzuat_id = str(document.get("mevzuatId") or "").strip()
                if not mevzuat_id:
                    stats.failed += 1
                    continue
                try:
                    await self._pause()
                    tree = await asyncio.to_thread(self.client.fetch_article_tree, mevzuat_id)
                    articles = list(iter_article_nodes(tree))
                except MevzuatPortalError as exc:
                    stats.failed += 1
                    logger.warning("Madde ağacı alınamadı: %s | %s", mevzuat_id, exc)
                    continue

                law_no = str(document.get("mevzuatNo") or "").strip()
                portal_type = portal_type_name(document.get("mevzuatTur"))
                for article in articles:
                    if remaining_articles <= 0:
                        break
                    remaining_articles -= 1
                    stats.processed += 1
                    article_no = str(article.get("maddeNo") or "").strip()
                    madde_id = str(article.get("maddeId") or "").strip()
                    if not article_no or not madde_id or not law_no:
                        stats.failed += 1
                        continue
                    external_id = article_external_id(
                        law_no, article_no, portal_type=portal_type
                    )
                    if self.archive.contains_portal_article(external_id, madde_id) and not self.config.refresh_existing:
                        stats.duplicates += 1
                        continue
                    try:
                        await self._pause()
                        html = await asyncio.to_thread(self.client.fetch_article_html, madde_id)
                        record = record_from_article(
                            document=document,
                            article=article,
                            article_html=html,
                            scraped_at=datetime.now(UTC),
                        )
                        if self.archive.save(record):
                            stats.saved += 1
                        else:
                            stats.duplicates += 1
                    except (MevzuatPortalError, ValueError) as exc:
                        stats.failed += 1
                        logger.warning("Madde alınamadı: %s | %s", madde_id, exc)

            if page_number * self.config.page_size >= page.total:
                break
            page_number += 1
            await self._pause()

        return stats
