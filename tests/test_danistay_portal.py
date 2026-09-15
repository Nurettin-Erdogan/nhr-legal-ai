from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from ingestion.danistay.portal import (
    DanistayPortalClient,
    DanistayPortalError,
    PortalDecisionRow,
    _raise_for_captcha,
    document_url,
    portal_external_id,
)
from ingestion.danistay.scraper import (
    ScraperConfig,
    decision_from_portal_row,
    extract_decision_text,
    search_filters,
)
from ingestion.yargitay.portal import CaptchaRequiredError
from worker.adapters.danistay import DanistaySourceAdapter
from worker.models import SyncRequest


SYNTHETIC_ROW = {
    "id": "9900000001",
    "daireKurul": "10. Daire",
    "esasNo": "2098/123",
    "kararNo": "2099/456",
    "kararTarihi": "31.12.2099",
    "arananKelime": "sentetik",
}

SYNTHETIC_DOCUMENT = """
<html><body>
<div id="content" class="context"></div>
<p id="hiddencontent" style="display:none">
&lt;html&gt;&lt;body&gt;&lt;b&gt;Danıştay 10. Daire Başkanlığı 2098/123 E., 2099/456 K.&lt;/b&gt;
&lt;p&gt;Birinci sentetik karar paragrafı.&lt;br&gt;İkinci satır.&lt;/p&gt;&lt;/body&gt;&lt;/html&gt;
</p>
<script>document.getElementById('content').innerHTML = 'navigation';</script>
</body></html>
"""


class _Response:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    def read(self) -> bytes:
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _Opener:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        assert timeout == 5
        self.requests.append(request)
        return _Response(self.responses.pop(0))


def test_structured_row_and_hidden_document_are_authoritative():
    row = PortalDecisionRow.from_mapping(SYNTHETIC_ROW)
    decision = decision_from_portal_row(
        row,
        SYNTHETIC_DOCUMENT,
        scraped_at=datetime(2099, 12, 31, tzinfo=UTC),
    )

    assert decision.court_name == "Danıştay"
    assert decision.chamber == "10. Daire"
    assert decision.docket_no == "2098/123"
    assert decision.decision_no == "2099/456"
    assert decision.decision_date == date(2099, 12, 31)
    assert decision.external_id == "danistay:9900000001"
    assert decision.source_url.endswith("getDokuman?id=9900000001")
    assert "Birinci sentetik karar paragrafı" in decision.raw_text
    assert "navigation" not in decision.raw_text
    assert decision.metadata["source_adapter"] == "danistay"
    assert decision.metadata["canonical_source_name"] == "Danıştay Karar Arama"


def test_search_uses_verified_session_and_json_contract():
    listing = {
        "metadata": {"FMTY": "SUCCESS"},
        "data": {"recordsTotal": 10, "recordsFiltered": 1, "data": [SYNTHETIC_ROW]},
    }
    opener = _Opener(
        [
            b"<html>root</html>",
            b"<html>detailed search</html>",
            json.dumps(listing, ensure_ascii=False).encode("utf-8"),
            SYNTHETIC_DOCUMENT.encode("utf-8"),
        ]
    )
    client = DanistayPortalClient(opener=opener, timeout_seconds=5)
    config = ScraperConfig(
        keyword="sentetik",
        chamber="10. Daire",
        decision_date_from=date(2099, 1, 1),
        decision_date_to=date(2099, 12, 31),
    )
    filters = search_filters(config, page_number=2, page_size=5)

    client.begin_detailed_search(filters)
    page = client.search_page(filters)
    document = client.fetch_document_html("9900000001", keyword="sentetik")

    assert page.records_total == 10
    assert page.records_filtered == 1
    assert page.rows[0].docket_no == "2098/123"
    assert extract_decision_text(document).startswith("Danıştay 10. Daire")
    detail_body = json.loads(opener.requests[1].data.decode("utf-8"))
    list_body = json.loads(opener.requests[2].data.decode("utf-8"))
    assert detail_body == {"data": filters}
    assert list_body == {"data": filters}
    assert filters["daire"] == "10. Daire"
    assert filters["baslangicTarihi"] == "01.01.2099"
    assert filters["pageNumber"] == 2


def test_captcha_enabled_response_stops_collection():
    raw = b'<input id="isDisplayCaptcha" value="true">'
    with pytest.raises(CaptchaRequiredError, match="CAPTCHA"):
        _raise_for_captcha(raw)


def test_missing_hidden_content_and_structured_fields_are_rejected():
    with pytest.raises(DanistayPortalError, match="hiddencontent"):
        extract_decision_text("<html><body>layout only</body></html>")

    invalid = PortalDecisionRow("1", "10. Daire", "", "2099/1", "01.01.2099")
    with pytest.raises(DanistayPortalError, match="esas no"):
        decision_from_portal_row(invalid, SYNTHETIC_DOCUMENT)


def test_identity_and_url_reject_empty_document_id():
    with pytest.raises(ValueError):
        portal_external_id(" ")
    with pytest.raises(ValueError):
        document_url("")


def test_adapter_resumes_inside_partially_consumed_page(monkeypatch, tmp_path):
    rows = tuple(
        PortalDecisionRow.from_mapping(
            {
                **SYNTHETIC_ROW,
                "id": f"990000000{index}",
                "esasNo": f"2098/{index}",
                "kararNo": f"2099/{index}",
            }
        )
        for index in range(1, 4)
    )

    class Client:
        base_url = "https://karararama.danistay.gov.tr/"

        def begin_detailed_search(self, _filters):
            return None

        def search_page(self, _filters):
            from ingestion.danistay.portal import SearchPage

            return SearchPage(rows=rows, records_total=3, records_filtered=3)

        def fetch_document_html(self, _document_id, *, keyword=""):
            return SYNTHETIC_DOCUMENT

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("DANISTAY_DELAY_SECONDS", "0")
    monkeypatch.setenv("INGESTION_SNAPSHOT_DIR", str(tmp_path))
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    request = SyncRequest(
        source="danistay",
        date_from=date(2099, 1, 1),
        date_to=date(2099, 12, 31),
        max_records=1,
        resume=True,
    )
    first = DanistaySourceAdapter(client=Client())
    first_events = list(
        first.sync(request, cursor={}, connection=None, dry_run=True, should_stop=lambda: False)
    )
    assert first_events[0][1]["external_id"] == "danistay:9900000001"
    assert first.last_cursor["page"] == 1
    assert first.last_cursor["row_offset"] == 1

    second = DanistaySourceAdapter(client=Client())
    second_events = list(
        second.sync(
            request,
            cursor=first.last_cursor,
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert second_events[0][1]["external_id"] == "danistay:9900000002"
    assert second.last_cursor["row_offset"] == 2
