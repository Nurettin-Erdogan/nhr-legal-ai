"""Yargıtay ve mevzuat çekimini tek iş olarak yürüten toplayıcı."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ingestion.catalog import CollectProfile, PROFILES
from ingestion.mevzuat.fetcher import FetcherConfig, FetchStats, MevzuatFetcher
from ingestion.yargitay.scraper import ScrapeStats, ScraperConfig, YargitayScraper

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CollectOptions:
    profile: str = "starter"
    only: str = "all"
    delay: float | None = None
    mevzuat_dir: Path = Path("data/mevzuat")
    yargitay_dir: Path = Path("data/yargitay")
    refresh_existing: bool = False


@dataclass
class CollectReport:
    profile: str
    mevzuat: list[tuple[str, FetchStats]] = field(default_factory=list)
    yargitay: list[tuple[str, ScrapeStats]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def saved_count(self) -> int:
        return sum(stats.saved + stats.duplicates for _, stats in self.mevzuat) + sum(
            stats.saved + stats.duplicates for _, stats in self.yargitay
        )

    @property
    def ok(self) -> bool:
        return self.saved_count > 0


def resolve_profile(name: str) -> CollectProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        known = ", ".join(sorted(PROFILES))
        raise ValueError(f"Bilinmeyen profil: {name}. Kullanılabilir: {known}") from exc


class CorpusCollector:
    """Resmî JSON uçlarından başlangıç korpusunu diske yazar."""

    def __init__(
        self,
        options: CollectOptions,
        *,
        mevzuat_fetcher_cls: type[MevzuatFetcher] = MevzuatFetcher,
        yargitay_scraper_cls: type[YargitayScraper] = YargitayScraper,
    ) -> None:
        if options.only not in {"all", "mevzuat", "yargitay"}:
            raise ValueError("only all, mevzuat veya yargitay olmalıdır")
        self.options = options
        self.profile = resolve_profile(options.profile)
        self.mevzuat_fetcher_cls = mevzuat_fetcher_cls
        self.yargitay_scraper_cls = yargitay_scraper_cls

    def _mevzuat_delay(self) -> float:
        if self.options.delay is not None:
            return self.options.delay
        return self.profile.mevzuat_delay_seconds

    def _yargitay_delay(self) -> float:
        if self.options.delay is not None:
            return self.options.delay
        return self.profile.yargitay_delay_seconds

    async def run(self) -> CollectReport:
        report = CollectReport(profile=self.profile.name)
        if self.options.only in {"all", "mevzuat"}:
            await self._collect_mevzuat(report)
        if self.options.only in {"all", "yargitay"}:
            await self._collect_yargitay(report)
        return report

    async def _collect_mevzuat(self, report: CollectReport) -> None:
        for job in self.profile.laws:
            logger.info("Mevzuat çekiliyor: %s (%s)", job.name, job.law_no)
            fetcher = self.mevzuat_fetcher_cls(
                FetcherConfig(
                    law_no=job.law_no,
                    types=job.types,
                    max_documents=1,
                    max_articles=self.profile.max_articles_per_law,
                    output_dir=self.options.mevzuat_dir,
                    delay_seconds=self._mevzuat_delay(),
                    refresh_existing=self.options.refresh_existing,
                )
            )
            try:
                stats = await fetcher.run()
            except Exception as exc:
                message = f"{job.law_no} {job.name}: {exc}"
                logger.error("Mevzuat işi durdu: %s", message)
                report.errors.append(message)
                continue
            report.mevzuat.append((job.law_no, stats))
            logger.info(
                "Mevzuat bitti | %s | yeni=%s | aynı=%s | hatalı=%s",
                job.law_no,
                stats.saved,
                stats.duplicates,
                stats.failed,
            )

    async def _collect_yargitay(self, report: CollectReport) -> None:
        from ingestion.yargitay.portal import CaptchaRequiredError, PortalError

        for job in self.profile.yargitay:
            label = f"{job.keyword} / {job.chamber or 'tüm daireler'}"
            logger.info("Yargıtay çekiliyor: %s", label)
            scraper = self.yargitay_scraper_cls(
                ScraperConfig(
                    keyword=job.keyword,
                    chamber=job.chamber,
                    max_decisions=job.max_decisions,
                    output_dir=self.options.yargitay_dir,
                    delay_seconds=self._yargitay_delay(),
                    refresh_existing=self.options.refresh_existing,
                )
            )
            try:
                stats = await scraper.run()
            except CaptchaRequiredError as exc:
                message = f"Yargıtay CAPTCHA: {label}: {exc}"
                logger.error(message)
                report.errors.append(message)
                break
            except PortalError as exc:
                message = f"Yargıtay: {label}: {exc}"
                logger.error(message)
                report.errors.append(message)
                continue
            report.yargitay.append((label, stats))
            logger.info(
                "Yargıtay bitti | %s | yeni=%s | aynı=%s | hatalı=%s",
                label,
                stats.saved,
                stats.duplicates,
                stats.failed,
            )
