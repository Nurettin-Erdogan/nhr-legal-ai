from __future__ import annotations

import json
from datetime import date
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from ingestion.aym.portal import (
    AymDecisionRow,
    AymDecisionFile,
    AymPortalClient,
    AymPortalError,
    AymSecurityVerificationRequired,
    SearchPage,
    application_external_id,
    decision_url,
)
from ingestion.aym.parser import decision_from_udf, extract_udf_text
from worker.adapters.aym import AymSourceAdapter
from worker.models import SyncRequest


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
    assert "/kbb/pages/search/BireyselBasvuru?" in row.source_url
    assert "type=BireyselBasvuru" in row.source_url


def test_search_uses_verified_public_json_contract():
    opener = _Opener({"total": 1, "page": 1, "page_size": 5, "data": [SYNTHETIC_ROW]})
    client = AymPortalClient(opener=opener, timeout_seconds=5)

    page = client.search_page(page=1, page_size=5, application_no="2099/123")

    assert page.total == 1
    assert page.rows[0].application_no == "2099/123"
    body = json.loads(opener.request.data.decode("utf-8"))
    assert body["kararTipi"] == "BireyselBasvuru"
    assert opener.request.full_url.endswith("/api/core/public/search")


def test_search_rejects_missing_official_identity():
    invalid = {**SYNTHETIC_ROW, "id": ""}
    client = AymPortalClient(
        opener=_Opener({"total": 1, "page": 1, "data": [invalid]}),
        timeout_seconds=5,
    )

    with pytest.raises(AymPortalError, match="resmî id"):
        client.search_page()


def test_search_norm_denetimi_uses_official_karar_tipi():
    row = {
        "kararTipi": "NormDenetimi",
        "id": "00000000-0000-0000-0000-000000000999",
        "esasNo": "1962/2",
        "kararNo": "1962/1",
        "kararTarihi": "1962-09-05",
    }
    opener = _Opener({"total": 1, "page": 1, "page_size": 1, "data": [row]})
    client = AymPortalClient(opener=opener, timeout_seconds=5)
    page = client.search_page(page=1, page_size=1, karar_tipi="NormDenetimi")
    body = json.loads(opener.request.data.decode("utf-8"))
    assert body["kararTipi"] == "NormDenetimi"
    assert page.rows[0].external_id.startswith("aym:NormDenetimi:")
    assert "NormDenetimi" in page.rows[0].source_url
    row = AymDecisionRow.from_mapping(SYNTHETIC_ROW)

    with pytest.raises(AymSecurityVerificationRequired, match="public UDF"):
        AymPortalClient().fetch_full_text(row)


def test_identity_and_url_reject_empty_application_number():
    with pytest.raises(ValueError):
        application_external_id(" ")
    with pytest.raises(ValueError):
        decision_url("")


def _synthetic_udf(application_no: str = "2099/123", *, decision_date: str = "03.02.2099") -> bytes:
    xml = f"""
    <template><content><elements>
      <paragraph><content>ANAYASA MAHKEMESİ</content></paragraph>
      <paragraph><content>Bireysel Başvuru No: {application_no}</content></paragraph>
      <paragraph><content>Karar Tarihi: {decision_date}</content></paragraph>
      <paragraph><content>{'Sentetik karar paragrafı. ' * 12}</content></paragraph>
    </elements></content></template>
    """.encode("utf-8")
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("content.xml", xml)
    return stream.getvalue()


class _RawResponse:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    def read(self) -> bytes:
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _SequenceOpener:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        assert timeout == 5
        self.requests.append(request)
        return _RawResponse(self.responses.pop(0))


def test_public_udf_file_contract_and_text_parser():
    file_payload = {
        "success": True,
        "data": [
            {
                "id": "file-1",
                "kararId": SYNTHETIC_ROW["id"],
                "url": "/files/bireysel-basvuru/synthetic_2099-123.udf",
                "kaynak": "BireyselBasvuru",
            }
        ],
    }
    udf = _synthetic_udf()
    opener = _SequenceOpener(
        [json.dumps(file_payload).encode("utf-8"), udf]
    )
    client = AymPortalClient(opener=opener, timeout_seconds=5)
    row = AymDecisionRow.from_mapping(SYNTHETIC_ROW)

    files = client.list_decision_files(row)
    raw, download = client.download_udf(files[0])
    text = extract_udf_text(raw)

    assert files == (
        AymDecisionFile(
            "file-1",
            SYNTHETIC_ROW["id"],
            "bireysel-basvuru",
            "synthetic_2099-123.udf",
            "BireyselBasvuru",
        ),
    )
    assert "/api/core/public/files/download-attachment/" in download
    assert "2099/123" in text
    assert "Sentetik karar paragrafı" in text


def test_udf_becomes_grounded_court_decision_without_fake_decision_number():
    row = AymDecisionRow.from_mapping(SYNTHETIC_ROW)
    decision = decision_from_udf(
        row,
        _synthetic_udf(),
        download_url="https://kararlarbilgibankasi.anayasa.gov.tr/api/core/public/files/download-attachment/x/y.udf",
    )

    assert decision.court_name == "Anayasa Mahkemesi"
    assert decision.chamber == "İkinci Bölüm"
    assert decision.docket_no == "2099/123"
    assert decision.decision_no is None
    assert decision.external_id == "aym:bb:2099/123"
    assert decision.metadata["outcome"] == "Esas (İhlal)"
    assert decision.metadata["kunye_verified"] is True
    assert "applicant_name" not in decision.metadata


def test_udf_rejects_mismatched_application_number():
    row = AymDecisionRow.from_mapping(SYNTHETIC_ROW)
    with pytest.raises(AymPortalError, match="eşleşmiyor"):
        decision_from_udf(
            row,
            _synthetic_udf("2099/999"),
            download_url="https://kararlarbilgibankasi.anayasa.gov.tr/public.udf",
        )


def test_udf_reads_content_xml_even_if_archive_has_extra_members():
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        with ZipFile(BytesIO(_synthetic_udf()), "r") as source:
            archive.writestr("content.xml", source.read("content.xml"))
        archive.writestr("mimetype", b"application/vnd.uyap-udf")
        archive.writestr("images/logo.png", b"not-a-real-image")
    text = extract_udf_text(stream.getvalue())
    assert "2099/123" in text
    assert "03.02.2099" in text


def test_udf_rejects_missing_content_xml():
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/vnd.uyap-udf")
    with pytest.raises(AymPortalError, match="content.xml yok"):
        extract_udf_text(stream.getvalue())


def test_udf_rejects_mismatched_decision_date():
    row = AymDecisionRow.from_mapping(SYNTHETIC_ROW)
    with pytest.raises(AymPortalError, match="karar tarihi"):
        decision_from_udf(
            row,
            _synthetic_udf(decision_date="01.01.1990"),
            download_url="https://kararlarbilgibankasi.anayasa.gov.tr/public.udf",
        )


def test_adapter_quarantines_unreadable_udf_and_keeps_scanning(monkeypatch):
    rows = tuple(
        AymDecisionRow.from_mapping(
            {
                **SYNTHETIC_ROW,
                "id": f"00000000-0000-0000-0000-00000000012{index}",
                "basvuruNo": f"2099/{index}",
            }
        )
        for index in (1, 2)
    )

    class Client:
        def search_page(self, **_kwargs):
            return SearchPage(rows, total=2, page=1, page_size=20)

        def list_decision_files(self, row):
            return (
                AymDecisionFile(
                    "file",
                    row.official_id,
                    "bireysel-basvuru",
                    f"{row.application_no.replace('/', '-')}.udf",
                    "BireyselBasvuru",
                ),
            )

        def download_udf(self, decision_file):
            if "2099-1" in decision_file.filename:
                return b"not-a-zip", "https://kararlarbilgibankasi.anayasa.gov.tr/bad.udf"
            application_no = decision_file.filename.removesuffix(".udf").replace("-", "/")
            return _synthetic_udf(application_no), (
                "https://kararlarbilgibankasi.anayasa.gov.tr/"
                f"api/core/public/files/download-attachment/{decision_file.folder}/"
                f"{decision_file.filename}"
            )

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("AYM_DELAY_SECONDS", "0")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    adapter = AymSourceAdapter(client=Client())
    events = list(
        adapter.sync(
            SyncRequest(source="aym", max_records=2, resume=True),
            cursor={},
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert events[0][0] == "quarantined"
    assert events[1][0] == "created"
    assert events[1][1]["external_id"] == "aym:bb:2099/2"
    assert adapter.last_cursor["type_index"] == 1


def test_adapter_resumes_inside_partially_consumed_page(monkeypatch):
    rows = tuple(
        AymDecisionRow.from_mapping(
            {
                **SYNTHETIC_ROW,
                "id": f"00000000-0000-0000-0000-00000000012{index}",
                "basvuruNo": f"2099/{index}",
            }
        )
        for index in (3, 4)
    )

    class Client:
        def search_page(self, **_kwargs):
            return SearchPage(rows, total=2, page=1, page_size=20)

        def list_decision_files(self, row):
            return (
                AymDecisionFile(
                    "file",
                    row.official_id,
                    "bireysel-basvuru",
                    f"{row.application_no.replace('/', '-')}.udf",
                    "BireyselBasvuru",
                ),
            )

        def download_udf(self, decision_file):
            application_no = decision_file.filename.removesuffix(".udf").replace("-", "/")
            return _synthetic_udf(application_no), (
                "https://kararlarbilgibankasi.anayasa.gov.tr/"
                f"api/core/public/files/download-attachment/{decision_file.folder}/"
                f"{decision_file.filename}"
            )

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("AYM_DELAY_SECONDS", "0")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    request = SyncRequest(source="aym", max_records=1, resume=True)
    first = AymSourceAdapter(client=Client())
    first_events = list(
        first.sync(request, cursor={}, connection=None, dry_run=True, should_stop=lambda: False)
    )
    assert first_events[0][1]["external_id"] == "aym:bb:2099/3"
    assert first.last_cursor["row_offset"] == 1

    second = AymSourceAdapter(client=Client())
    second_events = list(
        second.sync(
            request,
            cursor=first.last_cursor,
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert second_events[0][1]["external_id"] == "aym:bb:2099/4"


def test_completed_one_off_aym_search_does_not_pin_next_corpus_run(monkeypatch):
    class Client:
        def __init__(self):
            self.calls = []

        def search_page(self, **kwargs):
            self.calls.append(kwargs)
            return SearchPage((), total=0, page=1, page_size=20)

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    client = Client()
    adapter = AymSourceAdapter(client=client)
    list(
        adapter.sync(
            SyncRequest(source="aym", max_records=1),
            cursor={"page": 1, "row_offset": 0, "complete": True, "keyword": "2024/31235"},
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )

    assert client.calls[0]["keyword"] is None
    assert client.calls[0]["application_no"] is None
    assert adapter.last_cursor["keyword"] == ""
