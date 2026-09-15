from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ingestion.mevzuat.parser import (
    article_external_id,
    iter_article_nodes,
    map_legislation_type,
    record_from_article,
)
from ingestion.mevzuat.portal import SearchPage
from ingestion.mevzuat.fetcher import FetcherConfig, MevzuatFetcher

FIXTURES = Path(__file__).parent / "fixtures" / "mevzuat"


def _load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_kanun_and_khk_map_to_schema_types():
    assert map_legislation_type("KANUN", law_no="4857") == "law"
    assert map_legislation_type("KHK") == "decree"
    assert map_legislation_type("YONETMELIK") == "regulation"
    assert map_legislation_type("TEBLIGLER") == "communique"
    assert map_legislation_type("KANUN", law_no="2709") == "constitution"


def test_article_external_id_uses_natural_law_and_article_key():
    assert article_external_id("4857", "25", portal_type="KANUN") == "mevzuat:kanun:4857:m.25"


def test_tree_fixture_yields_numbered_articles_in_document_order():
    tree = _load_json("tree_kanun_4857.json")["data"]
    articles = list(iter_article_nodes(tree))

    assert [str(node["maddeNo"]) for node in articles[:3]] == ["1", "2", "3"]
    assert all(node.get("maddeId") for node in articles)


def test_record_from_article_keeps_structured_metadata_and_plain_text():
    document = _load_json("search_kanun_4857.json")["data"]["mevzuatList"][0]
    html = (FIXTURES / "article_4857_m25.html").read_text(encoding="utf-8")
    article = {
        "maddeId": "1656939",
        "maddeNo": 25,
        "title": "İşverenin haklı nedenle derhal fesih hakkı",
        "guncellemeTarihi": "2026-05-07T08:03:51.000+00:00",
        "mevzuatId": "103054",
    }

    record = record_from_article(
        document=document,
        article=article,
        article_html=html,
        scraped_at=datetime(2026, 5, 7, tzinfo=UTC),
    )

    assert record.legislation_type == "law"
    assert record.law_no == "4857"
    assert record.article_no == "25"
    assert record.external_id == "mevzuat:kanun:4857:m.25"
    assert record.official_gazette_no == "25134"
    assert record.source_url and "MevzuatNo=4857" in record.source_url
    assert record.metadata["mevzuat_id"] == "103054"
    assert record.metadata["madde_id"] == "1656939"
    assert "Süresi belirli olsun veya olmasın" in record.raw_text
    assert "<p" not in record.raw_text


class _FakeClient:
    def __init__(self) -> None:
        self.article_calls: list[str] = []
        self.search = _load_json("search_kanun_4857.json")
        self.tree = _load_json("tree_kanun_4857.json")["data"]
        self.html = (FIXTURES / "article_4857_m25.html").read_text(encoding="utf-8")

    def search_page(self, **kwargs):
        documents = tuple(self.search["data"]["mevzuatList"])
        return SearchPage(documents=documents, total=1, start=0)

    def fetch_article_tree(self, mevzuat_id: str):
        assert mevzuat_id == "103054"
        return self.tree

    def fetch_article_html(self, madde_id: str) -> str:
        self.article_calls.append(madde_id)
        return self.html


def test_fetcher_archives_article_records_and_skips_duplicates(tmp_path):
    client = _FakeClient()
    fetcher = MevzuatFetcher(
        FetcherConfig(law_no="4857", max_articles=2, delay_seconds=0, output_dir=tmp_path),
        client=client,
    )

    first = asyncio_run(fetcher.run())
    second = asyncio_run(fetcher.run())

    assert first.saved == 2
    assert second.duplicates == 2
    assert len(fetcher.archive) == 2
    records = list(fetcher.archive.iter_records())
    assert records[0].law_no == "4857"
    assert {record.article_no for record in records} == {"1", "2"}


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
