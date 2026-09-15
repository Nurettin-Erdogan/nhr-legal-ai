from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from ingestion.yargitay.portal import (
    CaptchaRequiredError,
    PortalDecisionRow,
    PortalError,
    SearchPage,
    _retry_wait_seconds,
    _validate_response,
    html_to_text,
)
from ingestion.yargitay.scraper import (
    ScraperConfig,
    YargitayScraper,
    _search_filters,
    decision_from_portal_row,
)


ROW = PortalDecisionRow(
    document_id="1224329000",
    chamber="9. Hukuk Dairesi",
    docket_no="2026/6550",
    decision_no="2026/4875",
    decision_date="21.05.2026",
    keyword="kıdem tazminatı",
)


def test_html_to_text_removes_markup_and_preserves_paragraphs():
    value = "<html><style>x</style><body><p>T.C. YARGITAY</p><p>Karar&nbsp;metni<br>devamı</p></body></html>"

    assert html_to_text(value) == "T.C. YARGITAY\n\nKarar metni\n\ndevamı"


def test_structured_portal_row_is_authoritative():
    decision = decision_from_portal_row(
        ROW,
        "<p>Gövde içinde yanıltıcı 2010/1 E. numarası vardır.</p>",
        scraped_at=datetime(2026, 5, 22, tzinfo=UTC),
    )

    assert decision.chamber == "9. Hukuk Dairesi"
    assert decision.docket_no == "2026/6550"
    assert decision.decision_no == "2026/4875"
    assert decision.decision_date.isoformat() == "2026-05-21"
    assert decision.external_id == "yargitay:1224329000"
    assert decision.source_url.endswith("getDokuman?id=1224329000")
    assert decision.metadata["source_document_id"] == "1224329000"


def test_search_payload_routes_hukuk_chamber_to_correct_field(tmp_path):
    config = ScraperConfig(
        "işçilik",
        "9. Hukuk Dairesi",
        decision_date_from=date(2025, 1, 1),
        decision_date_to=date(2025, 12, 31),
        output_dir=tmp_path,
    )

    filters = _search_filters(config, page_number=2, page_size=10)

    assert filters["birimYrgHukukDaire"] == "9. Hukuk Dairesi"
    assert filters["birimYrgCezaDaire"] == ""
    assert filters["siralama"] == 3
    assert filters["pageNumber"] == 2
    assert filters["baslangicTarihi"] == "01.01.2025"
    assert filters["bitisTarihi"] == "31.12.2025"


def test_retry_wait_is_exponential_and_respects_retry_after():
    assert _retry_wait_seconds(1, base_seconds=2) == 2
    assert _retry_wait_seconds(3, base_seconds=2) == 8
    assert _retry_wait_seconds(2, base_seconds=2, retry_after="12") == 12
    assert _retry_wait_seconds(2, base_seconds=2, retry_after="invalid") == 4


class _FakeClient:
    base_url = "https://karararama.yargitay.gov.tr/"

    def __init__(self) -> None:
        self.document_calls = 0

    def begin_detailed_search(self, filters):
        return None

    def search_page(self, filters):
        return SearchPage(rows=(ROW,), records_total=1, records_filtered=1)

    def fetch_document_html(self, document_id):
        self.document_calls += 1
        return "<p>Birinci paragraf.</p><p>İkinci paragraf.</p>"


def test_scraper_rejects_reversed_date_range(tmp_path):
    config = ScraperConfig(
        "işçilik",
        "9. Hukuk Dairesi",
        decision_date_from=date(2026, 1, 2),
        decision_date_to=date(2026, 1, 1),
        output_dir=tmp_path,
    )

    with pytest.raises(ValueError, match="Başlangıç tarihi"):
        YargitayScraper(config, client=_FakeClient())


def test_scraper_archives_and_skips_same_portal_id(tmp_path):
    client = _FakeClient()
    config = ScraperConfig(
        "kıdem tazminatı",
        "9. Hukuk Dairesi",
        max_decisions=1,
        output_dir=tmp_path,
        delay_seconds=0,
    )

    first = asyncio.run(YargitayScraper(config, client=client).run())
    second = asyncio.run(YargitayScraper(config, client=client).run())

    assert first.saved == 1
    assert second.duplicates == 1
    assert client.document_calls == 1
    assert (tmp_path / "yargitay__1224329000.json").exists()


def test_missing_structured_field_is_rejected():
    invalid = PortalDecisionRow("1", "9. Hukuk Dairesi", "", "2026/1", "01.01.2026")

    with pytest.raises(PortalError, match="esas no"):
        decision_from_portal_row(invalid, "<p>Karar metni</p>")


def test_captcha_instruction_stops_automatic_collection():
    response = {"metadata": {"FMTY": "SUCCESS", "FMTE": "DisplayCaptcha"}}

    with pytest.raises(CaptchaRequiredError, match="CAPTCHA"):
        _validate_response(response)
