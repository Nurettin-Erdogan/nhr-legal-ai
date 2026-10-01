from __future__ import annotations

import json
from datetime import date

import pytest

from ingestion.resmi_gazete.portal import ResmiGazeteClient, ResmiGazeteError


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


def _search_payload(*, url: str = "https://www.resmigazete.gov.tr/eskiler/2099/01/20990102.htm"):
    return {
        "draw": 1,
        "recordsTotal": 1,
        "recordsFiltered": 1,
        "data": [
            {
                "konu": "Sentetik Test Kanunu",
                "mevzuatAdi": "KANUNLAR",
                "resmiGazeteSayisi": 39999,
                "kanunKararNo": "9999",
                "resmiGazeteTarihi": "2099-01-02T00:00:00",
                "mukerrer": "HAYIR",
                "url": url,
            }
        ],
        "searchType": 1,
    }


def test_number_and_law_search_verifies_official_gazette_provenance():
    archive = """
    <html><head><meta charset="windows-1254"></head><body>
    <p>2 Ocak 2099</p><p>Sayı : 39999</p>
    <a>9999 Sentetik Test Kanunu</a></body></html>
    """.encode("windows-1254")
    opener = _Opener(
        [
            b"<html>T.C. Resmi Gazete</html>",
            json.dumps(_search_payload(), ensure_ascii=False).encode(),
            archive,
        ]
    )
    client = ResmiGazeteClient(opener=opener, timeout_seconds=5)

    result = client.verify_legislation(
        publication_date=None,
        issue_no="39999",
        law_no="9999",
        law_name="Sentetik Test Kanunu",
    )

    assert result.verified is True
    assert result.observed_date == "2099-01-02"
    assert result.observed_issue_no == "39999"
    assert result.law_no_present is True
    assert result.law_name_present is True
    assert result.archive_url.endswith("20990102.htm")
    body = json.loads(opener.requests[1].data.decode())
    assert body["parameters"]["searchtype"] == "1"
    assert body["parameters"]["genelsayi"] == "39999"
    assert body["parameters"]["genelmevzuatsayisi"] == "9999"


def test_old_archive_issue_number_can_be_parsed_from_html():
    payload = _search_payload()
    payload["data"][0]["resmiGazeteSayisi"] = 0
    opener = _Opener(
        [
            b"<html>root</html>",
            json.dumps(payload).encode(),
            b"<html><p>Sayi : 39999</p><p>9999 Test</p></html>",
        ]
    )

    issue = ResmiGazeteClient(opener=opener, timeout_seconds=5).search_legislation(
        law_no="9999",
        expected_issue_no=None,
    )

    assert issue.issue_no == "39999"


def test_non_official_result_url_is_rejected():
    opener = _Opener(
        [
            b"<html>root</html>",
            json.dumps(_search_payload(url="https://example.test/fake")).encode(),
        ]
    )
    client = ResmiGazeteClient(opener=opener, timeout_seconds=5)

    with pytest.raises(ResmiGazeteError, match="resmî olmayan URL"):
        client.search_legislation(law_no="9999", expected_issue_no="39999")


def test_issue_number_mismatch_is_tolerated_when_date_and_law_no_match():
    # Ölçüldü (2026-09-27): Bedesten'in kaydettiği sayı gerçek RG sayısından farklı olabilir
    # (ör. 31455 kaydedilmiş, gerçeği 31457); tarih + kanun no zaten tekil bir kimlik anahtarıdır,
    # sayı uyuşmazlığı doğrulamayı reddetmemelidir.
    archive = """
    <html><head><meta charset="windows-1254"></head><body>
    <p>2 Ocak 2099</p><p>Sayı : 39999</p>
    <a>9999 Sentetik Test Kanunu</a></body></html>
    """.encode("windows-1254")
    opener = _Opener(
        [b"<html>root</html>", json.dumps(_search_payload(), ensure_ascii=False).encode(), archive]
    )

    result = ResmiGazeteClient(opener=opener, timeout_seconds=5).verify_legislation(
        publication_date=date(2099, 1, 2),
        issue_no="11111111",  # yanlış/kayıtlı sayı
        law_no="9999",
        law_name="Sentetik Test Kanunu",
    )

    assert result.verified is True
    assert result.text_confirmed is True
    assert result.observed_issue_no == "39999"
    body = json.loads(opener.requests[1].data.decode())
    # Tarih varken sayı sunucuya filtre olarak gönderilmez.
    assert body["parameters"]["genelsayi"] == ""


def test_scanned_pdf_archive_is_verified_structurally_without_text_confirmation():
    # 1980 öncesi sayılar taranmış görüntü PDF'idir (metin katmanı yok). Kanun no + tarih RG'nin
    # kendi arama dizininde tekil eşleştiği için kimlik doğrulanır, ama tam metin karşılaştırması
    # yapılamayacağı açıkça `text_confirmed=False` ile işaretlenir.
    scanned_pdf = b"%PDF-1.3\r%\xe2\xe3\xcf\xd3\r\nnot a real page stream"
    opener = _Opener(
        [
            b"<html>root</html>",
            json.dumps(_search_payload()).encode(),
            scanned_pdf,
        ]
    )

    result = ResmiGazeteClient(opener=opener, timeout_seconds=5).verify_legislation(
        publication_date=date(2099, 1, 2),
        issue_no="39999",
        law_no="9999",
        law_name="Sentetik Test Kanunu",
    )

    assert result.verified is True
    assert result.text_confirmed is False
    assert "taranmış" in result.detail


def test_mismatching_structured_identity_is_rejected():
    opener = _Opener(
        [b"<html>root</html>", json.dumps(_search_payload()).encode()]
    )

    with pytest.raises(ResmiGazeteError, match="tekil"):
        ResmiGazeteClient(opener=opener, timeout_seconds=5).search_legislation(
            law_no="8888",
            expected_issue_no="39999",
        )
