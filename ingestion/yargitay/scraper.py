"""Yargıtay karar arama portalından karar toplayan Playwright tabanlı scraper.

Portal DOM'u değişebildiği için seçiciler `ScraperConfig` üzerinden
değiştirilebilir; ayrıştırma ve tekilleştirme mantığı DOM'dan bağımsızdır.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from ingestion.yargitay.archive import DecisionArchive
from ingestion.yargitay.parser import DEFAULT_COURT_NAME, parse_decision

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class ScraperConfig:
    """Portal adresi, seçiciler ve hız sınırlama ayarları.

    Seçiciler canlı portalın güncel DOM'una göre doğrulanmalıdır; varsayılanlar
    ilk prototipten devralınmıştır.
    """

    base_url: str = "https://karararama.yargitay.gov.tr"
    headless: bool = True
    timeout_ms: int = 45_000
    request_delay_seconds: float = 1.5
    max_retries: int = 3
    retry_backoff_seconds: float = 2.0
    search_input_selector: str = "#aranan"
    search_button_selector: str = "#btnArama"
    results_selector: str = ".search-result, .karar-listesi, .panel-group"
    row_selector: str = ".panel-heading, .karar-row"
    body_selector: str = ".panel-body, .karar-icerik"
    next_page_selector: str = "a:has-text('»'), .pagination-next, #btnNext"


@dataclass(slots=True)
class ScrapeStats:
    saved: int = 0
    duplicates: int = 0
    unparsed: int = 0
    failed: int = 0
    pages: int = 0


class YargitayScraper:
    def __init__(
        self,
        archive: DecisionArchive,
        *,
        config: ScraperConfig | None = None,
        chamber: str | None = None,
        court_name: str = DEFAULT_COURT_NAME,
    ) -> None:
        self.archive = archive
        self.config = config or ScraperConfig()
        self.chamber = chamber
        self.court_name = court_name
        self._last_request_at = 0.0

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.config.request_delay_seconds - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)
        self._last_request_at = time.monotonic()

    async def _with_retry(self, description: str, action):
        last_error: Exception | None = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                await self._throttle()
                return await action()
            except PlaywrightTimeoutError as error:
                last_error = error
                backoff = self.config.retry_backoff_seconds * attempt
                logger.warning(
                    "%s zaman aşımına uğradı (deneme %s/%s), %.1f sn sonra tekrar denenecek.",
                    description,
                    attempt,
                    self.config.max_retries,
                    backoff,
                )
                await asyncio.sleep(backoff)

        raise TimeoutError(f"{description} {self.config.max_retries} denemede tamamlanamadı.") from last_error

    async def _open_results(self, page: Page, keyword: str) -> None:
        await self._with_retry(
            "Portal açılışı",
            lambda: page.goto(
                self.config.base_url,
                timeout=self.config.timeout_ms,
                wait_until="domcontentloaded",
            ),
        )

        search_input = page.locator(self.config.search_input_selector)
        if await search_input.count() > 0:
            await search_input.fill(keyword)

        await self._with_retry(
            "Arama isteği",
            lambda: page.locator(self.config.search_button_selector).click(
                timeout=self.config.timeout_ms
            ),
        )

        await self._with_retry(
            "Sonuç listesi",
            lambda: page.wait_for_selector(
                self.config.results_selector,
                timeout=self.config.timeout_ms,
            ),
        )

    async def _collect_page(self, page: Page, remaining: int, stats: ScrapeStats) -> int:
        rows = page.locator(self.config.row_selector)
        row_count = await rows.count()

        if row_count == 0:
            logger.warning("Sayfada karar satırı bulunamadı.")
            return 0

        saved_here = 0

        for position in range(row_count):
            if saved_here >= remaining:
                break

            try:
                row = rows.nth(position)
                header_text = await row.inner_text()

                await self._throttle()
                await row.click(timeout=self.config.timeout_ms)

                body = page.locator(self.config.body_selector).nth(position)
                body_text = await body.inner_text()

                decision = parse_decision(
                    header_text=header_text,
                    body_text=body_text,
                    source_url=page.url,
                    court_name=self.court_name,
                    fallback_chamber=self.chamber,
                    scraped_at=datetime.now(timezone.utc),
                )

                if decision is None:
                    stats.unparsed += 1
                    logger.warning(
                        "Esas/karar numarası okunamadı, kayıt atlandı: %s",
                        header_text[:120],
                    )
                    continue

                if self.archive.save(decision):
                    saved_here += 1
                    stats.saved += 1
                    logger.info("Kaydedildi: %s", decision.external_id)
                else:
                    stats.duplicates += 1

            except PlaywrightTimeoutError:
                stats.failed += 1
                logger.warning("Karar satırı zaman aşımına uğradı, atlanıyor.")
            except Exception as error:
                stats.failed += 1
                logger.exception("Karar satırı işlenemedi: %s", error)

        return saved_here

    async def _go_to_next_page(self, page: Page) -> bool:
        next_button = page.locator(self.config.next_page_selector)

        if await next_button.count() == 0 or not await next_button.first.is_visible():
            return False

        await self._throttle()
        await next_button.first.click(timeout=self.config.timeout_ms)
        await page.wait_for_selector(
            self.config.results_selector,
            timeout=self.config.timeout_ms,
        )
        return True

    async def scrape(self, *, keyword: str = "", max_decisions: int = 50) -> ScrapeStats:
        stats = ScrapeStats()
        logger.info(
            "Scraper başlıyor | daire=%s | hedef=%s karar",
            self.chamber or "tümü",
            max_decisions,
        )

        async with async_playwright() as playwright:
            browser: Browser = await playwright.chromium.launch(
                headless=self.config.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context: BrowserContext = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=_USER_AGENT,
            )
            page = await context.new_page()

            try:
                await self._open_results(page, keyword)

                while stats.saved < max_decisions:
                    stats.pages += 1
                    logger.info("Sayfa %s taranıyor.", stats.pages)

                    saved_here = await self._collect_page(
                        page,
                        max_decisions - stats.saved,
                        stats,
                    )

                    if stats.saved >= max_decisions:
                        break

                    if not await self._go_to_next_page(page):
                        logger.info("Son sayfaya ulaşıldı.")
                        break

                    if saved_here == 0 and stats.duplicates == 0:
                        logger.info("Yeni karar bulunamadı, tarama durduruldu.")
                        break
            finally:
                await context.close()
                await browser.close()

        logger.info(
            "Tarama bitti | yeni=%s | mükerrer=%s | ayrıştırılamayan=%s | hatalı=%s",
            stats.saved,
            stats.duplicates,
            stats.unparsed,
            stats.failed,
        )
        return stats
