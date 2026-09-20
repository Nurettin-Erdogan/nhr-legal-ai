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


def test_adapter_rate_limit_on_search_keeps_cursor_and_stays_alive(monkeypatch):
    class Client:
        def search_page(self, **_kwargs):
            raise AymPortalError(
                "AYM HTTP 429; kaynak hız sınırı, aktarım beklemeye alınmalı "
                "(https://kararlarbilgibankasi.anayasa.gov.tr/api/core/public/search)"
            )

        def list_decision_files(self, _row):
            raise AssertionError("429 sonrası dosya listelenmemeli")

        def download_udf(self, _decision_file):
            raise AssertionError("429 sonrası UDF indirilmemeli")

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    from worker.config import get_worker_settings
    from worker.adapters.aym import AymSourceAdapter
    from worker.models import SyncRequest

    get_worker_settings.cache_clear()
    adapter = AymSourceAdapter(client=Client())
    events = list(
        adapter.sync(
            SyncRequest(source="aym", max_records=2, resume=True),
            cursor={"type_index": 2, "page": 15, "row_offset": 66, "karar_tipi": "SiyasiParti"},
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert events[0][0] == "failed"
    assert "429" in events[0][1]["reason"]
    assert adapter.last_cursor["type_index"] == 2
    assert adapter.last_cursor["page"] == 15
    get_worker_settings.cache_clear()



def test_from_mapping_does_not_treat_gazette_or_publication_as_decision_date():
    row = AymDecisionRow.from_mapping(
        {
            **SYNTHETIC_ROW,
            "kararTarihi": None,
            "resmiGazeteTarihi": "2099-03-01",
            "yayinTarihi": "2099-04-01T12:00:00",
        }
    )
    assert row.decision_date is None
    assert row.official_gazette_date == date(2099, 3, 1)
    assert row.publication_date == date(2099, 4, 1)


def test_udf_fills_missing_portal_decision_date_without_using_gazette():
    row = AymDecisionRow.from_mapping(
        {
            **SYNTHETIC_ROW,
            "kararTarihi": None,
            "resmiGazeteTarihi": "2098-12-31",
        }
    )
    decision = decision_from_udf(
        row,
        _synthetic_udf(),
        download_url="https://kararlarbilgibankasi.anayasa.gov.tr/public.udf",
    )
    assert decision.decision_date == date(2099, 2, 3)
    assert decision.metadata["official_gazette_date"] == "2098-12-31"


def test_adapter_accumulates_seen_across_runs_until_partition_closes(monkeypatch):
    rows = tuple(
        AymDecisionRow.from_mapping(
            {
                **SYNTHETIC_ROW,
                "id": f"00000000-0000-0000-0000-00000000012{index}",
                "basvuruNo": f"2099/{index}",
            }
        )
        for index in range(1, 6)
    )

    class Client:
        def search_page(self, **_kwargs):
            return SearchPage(rows, total=5, page=1, page_size=20)

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
    monkeypatch.setattr("worker.adapters.aym.AYM_DECISION_TYPES", ("BireyselBasvuru",))
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    request = SyncRequest(source="aym", max_records=2, resume=True)
    cursor: dict = {}
    seen_ids: list[str] = []
    last = None
    for _ in range(3):
        adapter = AymSourceAdapter(client=Client())
        events = list(
            adapter.sync(
                request,
                cursor=cursor,
                connection=None,
                dry_run=True,
                should_stop=lambda: False,
            )
        )
        seen_ids.extend(payload["external_id"] for _, payload in events)
        last = adapter
        cursor = adapter.last_cursor

    assert seen_ids == [
        "aym:bb:2099/1",
        "aym:bb:2099/2",
        "aym:bb:2099/3",
        "aym:bb:2099/4",
        "aym:bb:2099/5",
    ]
    assert last is not None
    assert last.last_cursor["complete"] is True
    assert last.last_cursor["reconciled"] is True


def test_adapter_keeps_legacy_page_size_when_resuming_mid_partition(monkeypatch):
    row = AymDecisionRow.from_mapping(SYNTHETIC_ROW)
    captured: list[int] = []

    class Client:
        def search_page(self, **kwargs):
            captured.append(int(kwargs["page_size"]))
            return SearchPage((row,), total=5, page=1, page_size=kwargs["page_size"])

        def list_decision_files(self, decision_row):
            return (
                AymDecisionFile(
                    "file",
                    decision_row.official_id,
                    "bireysel-basvuru",
                    "2099-123.udf",
                    "BireyselBasvuru",
                ),
            )

        def download_udf(self, decision_file):
            return _synthetic_udf(), (
                "https://kararlarbilgibankasi.anayasa.gov.tr/"
                f"api/core/public/files/download-attachment/{decision_file.folder}/"
                f"{decision_file.filename}"
            )

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("AYM_DELAY_SECONDS", "0")
    monkeypatch.setenv("AYM_PAGE_SIZE", "100")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    adapter = AymSourceAdapter(client=Client())
    list(
        adapter.sync(
            SyncRequest(source="aym", max_records=1, resume=True),
            cursor={
                "type_index": 0,
                "page": 2,
                "row_offset": 3,
                "window_seen_total": 23,
            },
            connection=None,
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert captured[0] == 20
    get_worker_settings.cache_clear()


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


class _KnownSourcesConnection:
    def __init__(self, known):
        self.known = set(known)

    def execute(self, _sql, params=None):
        wanted = set(params[0]) if params else set()
        hits = [(eid,) for eid in sorted(self.known & wanted)]

        class _Result:
            def fetchall(self_inner):
                return hits

        return _Result()


def test_adapter_skips_file_download_when_source_exists(monkeypatch):
    row = AymDecisionRow.from_mapping(SYNTHETIC_ROW)

    class Client:
        def __init__(self):
            self.listed = []
            self.downloaded = []

        def search_page(self, **_kwargs):
            return SearchPage((row,), total=1, page=1, page_size=20)

        def list_decision_files(self, decision_row):
            self.listed.append(decision_row.official_id)
            raise AssertionError("mevcut AYM kaydı için dosya listesi istenmemeli")

        def download_udf(self, decision_file):
            self.downloaded.append(decision_file.file_id)
            raise AssertionError("mevcut AYM kaydı indirilmemeli")

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("AYM_DELAY_SECONDS", "0")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    adapter = AymSourceAdapter(client=Client())
    events = list(
        adapter.sync(
            SyncRequest(source="aym", max_records=1, resume=True, lane="backfill"),
            cursor={},
            connection=_KnownSourcesConnection({"aym:bb:2099/123"}),
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert events == [
        (
            "unchanged",
            {
                "page": 1,
                "expected_count": 1,
                "requests_made": 1,
                "karar_tipi": "BireyselBasvuru",
                "external_id": "aym:bb:2099/123",
                "skipped_existing": True,
            },
        )
    ]


def test_adapter_current_lane_refetches_existing_source(monkeypatch):
    row = AymDecisionRow.from_mapping(SYNTHETIC_ROW)

    class Client:
        def __init__(self):
            self.listed = []
            self.downloaded = []

        def search_page(self, **_kwargs):
            return SearchPage((row,), total=1, page=1, page_size=20)

        def list_decision_files(self, decision_row):
            self.listed.append(decision_row.official_id)
            return (
                AymDecisionFile(
                    "file",
                    decision_row.official_id,
                    "bireysel-basvuru",
                    "2099-123.udf",
                    "BireyselBasvuru",
                ),
            )

        def download_udf(self, decision_file):
            self.downloaded.append(decision_file.file_id)
            return _synthetic_udf(), (
                "https://kararlarbilgibankasi.anayasa.gov.tr/"
                f"api/core/public/files/download-attachment/{decision_file.folder}/"
                f"{decision_file.filename}"
            )

    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql://nhr_app:x@localhost:5433/nhr")
    monkeypatch.setenv("AYM_DELAY_SECONDS", "0")
    from worker.config import get_worker_settings

    get_worker_settings.cache_clear()
    client = Client()
    adapter = AymSourceAdapter(client=client)
    events = list(
        adapter.sync(
            SyncRequest(source="aym", max_records=1, resume=True, lane="current"),
            cursor={},
            connection=_KnownSourcesConnection({"aym:bb:2099/123"}),
            dry_run=True,
            should_stop=lambda: False,
        )
    )
    assert events[0][0] == "created"
    assert "skipped_existing" not in events[0][1]
    assert client.listed == [row.official_id]
    assert client.downloaded == ["file"]

