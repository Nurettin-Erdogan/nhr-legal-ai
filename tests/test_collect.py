from __future__ import annotations

import asyncio
from pathlib import Path

from ingestion.catalog import PROFILES, STARTER_LAWS
from ingestion.collect import CollectOptions, CorpusCollector
from ingestion.mevzuat.fetcher import FetchStats, FetcherConfig
from ingestion.yargitay.scraper import ScrapeStats, ScraperConfig


def test_starter_profile_covers_core_codes_without_duplicates():
    numbers = [job.law_no for job in STARTER_LAWS]
    assert len(set(numbers)) == len(numbers)
    assert {"2709", "4857", "6098", "5237", "1475"} <= set(numbers)
    assert "starter" in PROFILES
    assert "smoke" in PROFILES


class _FakeMevzuatFetcher:
    def __init__(self, config: FetcherConfig) -> None:
        self.config = config
        self.archive_root = config.output_dir

    async def run(self) -> FetchStats:
        return FetchStats(documents=1, processed=2, saved=2)


class _FakeYargitayScraper:
    def __init__(self, config: ScraperConfig) -> None:
        self.config = config

    async def run(self) -> ScrapeStats:
        return ScrapeStats(processed=3, saved=3, records_filtered=3)


def test_collector_runs_smoke_jobs_in_order(tmp_path: Path):
    collector = CorpusCollector(
        CollectOptions(profile="smoke", mevzuat_dir=tmp_path / "m", yargitay_dir=tmp_path / "y"),
        mevzuat_fetcher_cls=_FakeMevzuatFetcher,
        yargitay_scraper_cls=_FakeYargitayScraper,
    )

    report = asyncio.run(collector.run())

    assert report.ok
    assert report.mevzuat[0][0] == "4857"
    assert report.mevzuat[0][1].saved == 2
    assert report.yargitay[0][1].saved == 3


def test_collector_can_skip_yargitay(tmp_path: Path):
    collector = CorpusCollector(
        CollectOptions(profile="smoke", only="mevzuat", mevzuat_dir=tmp_path),
        mevzuat_fetcher_cls=_FakeMevzuatFetcher,
        yargitay_scraper_cls=_FakeYargitayScraper,
    )

    report = asyncio.run(collector.run())

    assert report.yargitay == []
    assert len(report.mevzuat) == 1
