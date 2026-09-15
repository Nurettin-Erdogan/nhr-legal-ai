from __future__ import annotations

import json
from datetime import date

import pytest

from ingestion.aym.portal import (
    AymDecisionRow,
    AymPortalClient,
    AymPortalError,
    AymSecurityVerificationRequired,
    application_external_id,
    decision_url,
)


SYNTHETIC_ROW = {
    "kararTipi": "BireyselBasvuru",
    "id": "00000000-0000-0000-0000-000000000123",
    "basvuruNo": "2099/123",
    "kararTarihi": "2099-02-03",
    "basvuruTarihi": "2098-01-02",
    "yayinTarihi": "2099-02-05T09:30:00",
    "basvuruAdi": "SENTETİK TEST BAŞVURUSU",
    "kararKonusu": "<p>Yalnız fixture sözleşme metnidir.</p>",
    "kararTuruBasvuruSonucuLabel": "Esas (İhlal)",
    "kararVerenBirimLabel": "İkinci Bölüm",
    "gizlilik": False,
}


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _Opener:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.request = None

    def open(self, request, timeout):
        self.request = request
        assert timeout == 5
        return _Response(self.payload)


def test_structured_row_preserves_official_aym_metadata():
    row = AymDecisionRow.from_mapping(SYNTHETIC_ROW)

    assert row.official_id.endswith("0123")
    assert row.application_no == "2099/123"
    assert row.decision_date == date(2099, 2, 3)
    assert row.publication_date == date(2099, 2, 5)
    assert row.chamber == "İkinci Bölüm"
    assert row.outcome == "Esas (İhlal)"
    assert row.subject == "Yalnız fixture sözleşme metnidir."
    assert row.confidential is False
    assert row.external_id == "aym:bb:2099/123"
    assert row.source_url.endswith("/kbb/BB/2099/123")


def test_search_uses_verified_public_json_contract():
    opener = _Opener({"total": 1, "page": 1, "page_size": 5, "data": [SYNTHETIC_ROW]})
    client = AymPortalClient(opener=opener, timeout_seconds=5)

    page = client.search_page(page=1, page_size=5, application_no="2099/123")

    assert page.total == 1
    assert page.rows[0].application_no == "2099/123"
    body = json.loads(opener.request.data.decode("utf-8"))
    assert body == {
        "kararTipi": "BireyselBasvuru",
        "page": 1,
        "size": 5,
        "sort": "yayinTarihi",
        "order": "desc",
        "basvuruNo": "2099/123",
    }
    assert opener.request.full_url.endswith("/api/core/public/search")


def test_search_rejects_missing_official_identity():
    invalid = {**SYNTHETIC_ROW, "id": ""}
    client = AymPortalClient(
        opener=_Opener({"total": 1, "page": 1, "data": [invalid]}),
        timeout_seconds=5,
    )

    with pytest.raises(AymPortalError, match="resmî id"):
        client.search_page()


def test_full_text_security_verification_is_not_bypassed():
    row = AymDecisionRow.from_mapping(SYNTHETIC_ROW)

    with pytest.raises(AymSecurityVerificationRequired, match="bypass"):
        AymPortalClient().fetch_full_text(row)


def test_identity_and_url_reject_empty_application_number():
    with pytest.raises(ValueError):
        application_external_id(" ")
    with pytest.raises(ValueError):
        decision_url("")
