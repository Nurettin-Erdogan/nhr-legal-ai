from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from ingestion.kdk import parser
from ingestion.kdk.parser import decision_from_row
from ingestion.kdk.portal import KdkPortalClient, KdkPortalError, download_url, search_form


SYNTHETIC_ROW = {
    "id": 999001,
    "evraK_ID": 888001,
    "karaR_NO": "2099/1234",
    "karaR_TARIH": "2099-12-31T12:30:00",
    "karaR_TURU": "Tavsiye Kararı",
    "karaR_YAYIN_URL": "20991231\\999001\\Yayin\\Karar.pdf",
    "karaR_YAYINLAMA_TARIHI": "2100-01-02T00:00:00",
    "sikayeT_NO": "2099/4321",
    "sikayeT_TARIH": "2099-11-01T00:00:00",
    "sikayeT_KONU": "Sentetik konu",
    "sikayeT_ALT_KONU": "Sentetik alt konu",
    "evraK_KONU": "Sentetik evrak konusu",
    "sikayeT_EDILEN_KURUM": "Sentetik kamu kurumu",
}


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


def test_verified_search_contract_and_official_pdf_url():
    payload = {
        "data": [SYNTHETIC_ROW],
        "draw": 1,
        "recordsTotal": 10,
        "recordsFiltered": 1,
    }
    opener = _Opener([json.dumps(payload).encode("utf-8"), b"%PDF-synthetic"])
    client = KdkPortalClient(opener=opener, timeout_seconds=5)
    form = search_form(
        start=20,
        length=10,
        keyword="işçi",
        date_from=date(2099, 1, 1),
        date_to=date(2099, 12, 31),
    )

    page = client.search_page(form)
    pdf, url = client.download_pdf(
        SYNTHETIC_ROW["karaR_YAYIN_URL"], SYNTHETIC_ROW["karaR_TARIH"]
    )

    assert page.records_filtered == 1
    assert page.rows[0]["karaR_NO"] == "2099/1234"
    assert form["start"] == "20"
    assert form["karbas"] == "01/01/2099"
    assert form["kararkelimeleri"] == "işçi"
    assert pdf.startswith(b"%PDF-")
    assert url.startswith("https://kararlar.ombudsman.gov.tr/Arama/Download?")
    assert "%5C" in url


def test_parser_uses_structured_metadata_and_pdf_text(monkeypatch):
    class Page:
        def extract_text(self):
            return "Sentetik KDK karar metni. " * 10

    class Reader:
        is_encrypted = False
        pages = [Page()]

    monkeypatch.setattr(parser, "PdfReader", lambda _stream: Reader())
    decision = decision_from_row(
        SYNTHETIC_ROW,
        b"%PDF-synthetic",
        source_url=download_url(
            SYNTHETIC_ROW["karaR_YAYIN_URL"], SYNTHETIC_ROW["karaR_TARIH"]
        ),
        fetched_at=datetime(2100, 1, 2, tzinfo=UTC),
    )

    assert decision.external_id == "kdk:999001"
    assert decision.decision_no == "2099/1234"
    assert decision.decision_date == date(2099, 12, 31)
    assert decision.complaint_no == "2099/4321"
    assert decision.metadata["source_document_id"] == "888001"
    assert decision.metadata["decision_type"] == "Tavsiye Kararı"
    assert decision.metadata["publication_date"] == "2100-01-02"
    assert decision.content_hash


def test_non_pdf_and_incomplete_row_are_rejected():
    opener = _Opener([b"<html>blocked</html>"])
    client = KdkPortalClient(opener=opener, timeout_seconds=5)
    with pytest.raises(KdkPortalError, match="PDF"):
        client.download_pdf("x.pdf", "2099-01-01")

    with pytest.raises(KdkPortalError, match="künye"):
        decision_from_row({}, b"%PDF-x", source_url="https://kararlar.ombudsman.gov.tr/x")
