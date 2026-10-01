from __future__ import annotations

import json
from datetime import date

import pytest

from ingestion.mevzuat_bilgi_sistemi.portal import MbsClient, MbsError


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


def _search_payload(*, detail_url: str = "mevzuat?MevzuatNo=4857&MevzuatTur=1&MevzuatTertip=5"):
    return {
        "draw": 1,
        "recordsTotal": 1,
        "recordsFiltered": 1,
        "data": [
            {
                "mevzuatNo": "4857",
                "mevAdi": "İŞ KANUNU",
                "kabulTarih": "22.05.2003",
                "resmiGazeteTarihi": "10.06.2003",
                "resmiGazeteSayisi": "25134",
                "mevzuatTertip": "5",
                "mevzuatTur": 1,
                "url": detail_url,
            }
        ],
    }


def _detail_html(*, host: str = "www.mevzuat.gov.tr") -> bytes:
    return f"""
    <html><body>
      <a href="https://{host}/MevzuatMetin/1.5.4857.doc">Word</a>
      <a href="https://{host}/MevzuatMetin/1.5.4857.pdf">PDF</a>
    </body></html>
    """.encode()


def test_official_search_and_detail_verify_legislation():
    opener = _Opener(
        [json.dumps(_search_payload(), ensure_ascii=False).encode(), _detail_html()]
    )
    result = MbsClient(opener=opener, timeout_seconds=5).verify_legislation(
        law_no="4857",
        law_name="İş Kanunu",
        publication_date=date(2003, 6, 10),
        issue_no="25134",
    )

    assert result.verified is True
    assert result.pdf_url == "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4857.pdf"
    assert result.doc_url == "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4857.doc"
    request_body = json.loads(opener.requests[0].data.decode())
    assert request_body["parameters"] == {
        "AranacakIfade": "NDg1Nw==",
        "AranacakYer": "Baslik",
        "TamCumle": False,
        "MevzuatTur": 0,
        "GenelArama": True,
    }


def test_metadata_mismatch_is_not_verified():
    opener = _Opener(
        [json.dumps(_search_payload(), ensure_ascii=False).encode(), _detail_html()]
    )
    result = MbsClient(opener=opener, timeout_seconds=5).verify_legislation(
        law_no="4857",
        law_name="Başka Kanun",
        publication_date=None,
        issue_no="99999",
    )

    assert result.verified is False
    assert result.title_matches is False
    assert "başlığı uyuşmuyor" in result.detail
    # Sayı uyuşmazlığı artık reddetmez, yalnız bilgi notu olarak eklenir (bkz. sayı hatası testi).
    assert "kayıtlı sayı" in result.detail


def test_issue_number_mismatch_alone_does_not_block_verification():
    # Bedesten'den gelen resmi_gazete_no kayıt hatası içerebilir (ör. "mükerrer" sayılar); başlık
    # ve tarih eşleştiği sürece kimlik zaten kanun no ile tekil bulunmuştur, sayı yalnız bilgi notudur.
    opener = _Opener(
        [json.dumps(_search_payload(), ensure_ascii=False).encode(), _detail_html()]
    )
    result = MbsClient(opener=opener, timeout_seconds=5).verify_legislation(
        law_no="4857",
        law_name="İş Kanunu",
        publication_date=date(2003, 6, 10),
        issue_no="99999",
    )

    assert result.verified is True
    assert result.observed_gazette_no == "25134"


def test_non_official_document_link_is_rejected():
    opener = _Opener(
        [json.dumps(_search_payload(), ensure_ascii=False).encode(), _detail_html(host="example.test")]
    )
    with pytest.raises(MbsError, match="resmî olmayan"):
        MbsClient(opener=opener, timeout_seconds=5).search_law("4857")


def test_ambiguous_exact_law_number_is_rejected():
    payload = _search_payload()
    payload["data"].append(dict(payload["data"][0]))
    opener = _Opener([json.dumps(payload, ensure_ascii=False).encode()])

    with pytest.raises(MbsError, match="tekil"):
        MbsClient(opener=opener, timeout_seconds=5).search_law("4857")


def test_same_number_in_other_legislation_type_resolves_to_law():
    # 6736 gibi numaralar hem Kanun hem Cumhurbaşkanı Kararı olarak listelenir.
    payload = _search_payload()
    other = dict(payload["data"][0])
    other["mevzuatTur"] = 3
    other["mevAdi"] = "CUMHURBAŞKANI KARARI"
    payload["data"].append(other)
    opener = _Opener([json.dumps(payload, ensure_ascii=False).encode(), _detail_html()])

    document = MbsClient(opener=opener, timeout_seconds=5).search_law("4857")

    assert document.law_name == "İŞ KANUNU"
    assert document.legislation_type == 1
