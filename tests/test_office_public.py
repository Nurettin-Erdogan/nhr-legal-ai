"""UYAP eklentisi uç noktaları ve üst veri ayrıştırma. Veritabanı sahtelenir."""

from __future__ import annotations

import base64
import errno
import hashlib
import io
import zipfile
from uuid import uuid4

import psycopg
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import office_public
from api.office_public import router
from api.upload_stream import Upload
from api.uyap_meta import extract_text_sample, is_allowed_file, parse_uyap_meta, safe_file_name

TOKEN = "t" * 32
OWNER = uuid4()
# Eklentinin her istekte gönderdiği UYAP kişisi (parmak izi + maskeli ad; kimlik numarası değil).
IDENTITY = {"X-UYAP-Identity": "a" * 64, "X-UYAP-Identity-Kind": "tc", "X-UYAP-Portal": "vatandas", "X-UYAP-Display": "AYSE%20Y%C4%B0LMAZ"}
ACCOUNT = uuid4()


def _client(monkeypatch, *, owner=(uuid4(), OWNER), outcome=("inserted", uuid4()), identity=True):
    stored: list[dict] = []
    checks: list = []
    marks: list = []

    def fake_register(owner_id, identity, audit=None):
        checks.append((owner_id, identity))
        return ACCOUNT

    def fake_mark(owner_id, account_id, **target):
        marks.append((owner_id, account_id, target))
        return 1

    def fake_owner(token):
        return owner if token == TOKEN else None

    def fake_store(owner_id, **kwargs):
        data = kwargs["data"]
        # Uç nokta işi bitince geçici dosyayı kapatır: içerik, çağrı anında (küçükse) okunup kaydedilir.
        content = data.small_bytes(1024 * 1024) if isinstance(data, Upload) else data
        stored.append({"owner_id": owner_id, **kwargs, "upload": data, "data": content})
        return outcome

    monkeypatch.setattr(office_public, "_owner_for_token", fake_owner)
    monkeypatch.setattr(office_public, "_store", fake_store)
    monkeypatch.setattr(office_public, "register", fake_register)
    monkeypatch.setattr(office_public, "mark", fake_mark)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, headers=IDENTITY if identity else None)
    client.identity_checks = checks
    client.marks = marks
    return client, stored


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_ingest_rejects_unknown_token(monkeypatch):
    client, stored = _client(monkeypatch)

    response = client.post(
        "/api/public/uyap-ingest",
        json={"token": "x" * 32, "files": [{"name": "a.pdf", "contentBase64": _b64(b"abc")}]},
    )

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "*"
    assert not stored


def test_ingest_stores_allowed_files_for_the_token_owner(monkeypatch):
    client, stored = _client(monkeypatch)

    response = client.post(
        "/api/public/uyap-ingest",
        json={
            "token": TOKEN,
            "files": [
                {"name": "../../etc/karar 2024-123.pdf", "contentBase64": _b64(b"%PDF")},
                {"name": "virus.exe", "contentBase64": _b64(b"MZ")},
            ],
        },
    )

    assert response.json() == {"ok": True, "found": 2, "inserted": 1, "duplicates": 0, "skipped": 1}
    assert stored[0]["owner_id"] == OWNER
    assert "/" not in stored[0]["file_name"] and stored[0]["file_name"].endswith(".pdf")


def test_ingest_reports_duplicates_separately_from_rejected_files(monkeypatch):
    client, _ = _client(monkeypatch, outcome=("duplicate", uuid4()))

    response = client.post(
        "/api/public/uyap-ingest",
        json={
            "token": TOKEN,
            "files": [
                {"name": "dilekce.pdf", "contentBase64": _b64(b"%PDF")},
                {"name": "virus.exe", "contentBase64": _b64(b"MZ")},
            ],
        },
    )

    body = response.json()
    assert body["duplicates"] == 1
    assert body["inserted"] == 0
    assert body["skipped"] == 2  # eski istemciler: yinelenen + geçersiz


def test_ingest_body_is_capped_before_the_token_is_looked_up(monkeypatch):
    client, stored = _client(monkeypatch)
    looked_up: list[str] = []
    monkeypatch.setattr(office_public, "_owner_for_token", lambda token: looked_up.append(token))
    monkeypatch.setattr(office_public, "MAX_INGEST_REQUEST_BYTES", 1024)

    response = client.post(
        "/api/public/uyap-ingest",
        json={"token": TOKEN, "files": [{"name": "a.pdf", "contentBase64": _b64(b"x" * 4096)}]},
    )

    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "*"
    assert not looked_up and not stored


def test_ingest_rejects_malformed_json_without_a_token_lookup(monkeypatch):
    client, stored = _client(monkeypatch)

    response = client.post(
        "/api/public/uyap-ingest", content=b"{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert not stored


def test_extension_connection_check_gets_400_with_a_file_message(monkeypatch):
    """Eklentinin "Bağlantıyı dene" düğmesi: geçerli anahtar + dosyasız istek → 400 ve "dosya" mesajı."""
    client, stored = _client(monkeypatch)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    empty_form = client.post("/api/public/v1/documents/upload", data={"evrakId": "1"}, headers=headers)
    empty_multipart = client.post(
        "/api/public/v1/documents/upload",
        content=b"--nhrtest--\r\n",
        headers={**headers, "content-type": "multipart/form-data; boundary=nhrtest"},
    )
    bad_token = client.post(
        "/api/public/v1/documents/upload", data={"evrakId": "1"}, headers={"Authorization": "Bearer " + "z" * 32}
    )

    for response in (empty_form, empty_multipart):
        assert response.status_code == 400
        assert "dosya" in response.json()["error"].lower()
    assert bad_token.status_code == 401
    assert not stored


def test_upload_checks_token_before_parsing_the_multipart_body(monkeypatch):
    client, stored = _client(monkeypatch)
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "10")  # işletmecinin isteğe bağlı üst sınırı
    monkeypatch.setattr(office_public, "MULTIPART_OVERHEAD_BYTES", 10)
    big = {"file": ("evrak.pdf", b"x" * 5000, "application/pdf")}

    no_token = client.post("/api/public/v1/documents/upload", files=big)
    wrong = client.post(
        "/api/public/v1/documents/upload", files=big, headers={"Authorization": "Bearer " + "z" * 32}
    )
    too_big = client.post(
        "/api/public/v1/documents/upload", files=big, headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert (no_token.status_code, wrong.status_code, too_big.status_code) == (401, 401, 413)
    assert not stored


def test_upload_has_no_size_cap_by_default_and_never_holds_the_body_in_memory(monkeypatch):
    """50 MB'ı aşan UYAP eki (canlıda 53 MB'lık zip) reddedilmez; sunucu içeriği belleğe almaz, ölçüp geçici dosyada tutar."""
    monkeypatch.delenv("MAX_UPLOAD_BYTES", raising=False)
    client, stored = _client(monkeypatch)
    payload = b"PK" + bytes(51 * 1024 * 1024)

    response = client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("ek.zip", payload, "application/zip")},
        data={"evrakId": "9"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200 and response.json()["ok"] is True
    [call] = stored
    upload = call["upload"]
    assert call["data"] is None  # 51 MB belleğe alınmadı
    assert upload.size == len(payload) and upload.sha256 == hashlib.sha256(payload).hexdigest()
    assert upload.data is None and upload.stream is not None  # bellekte değil, geçici dosyada
    assert upload._closed  # uç nokta işi bitince geçici dosyayı kapatır (sahte `_store` kapatmasa bile)


def test_upload_requires_bearer_token_and_known_extension(monkeypatch):
    client, stored = _client(monkeypatch)
    files = {"file": ("evrak.pdf", b"%PDF-1.4", "application/pdf")}

    assert client.post("/api/public/v1/documents/upload", files=files).status_code == 401
    bad_type = client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("x.exe", b"MZ", "application/octet-stream")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    ok = client.post(
        "/api/public/v1/documents/upload",
        files=files,
        data={"evrakId": "77", "dosyaEsasNo": "2024/55"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert bad_type.status_code == 415
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert stored[0]["file_name"] == "77-evrak.pdf"
    assert stored[0]["overrides"]["uyap_file_no"] == "2024/55"


def test_duplicate_upload_is_reported_not_repeated(monkeypatch):
    existing = uuid4()
    client, _ = _client(monkeypatch, outcome=("duplicate", existing))

    response = client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("evrak.pdf", b"%PDF", "application/pdf")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.json() == {"ok": True, "duplicate": True, "id": str(existing)}


def test_changed_evidence_is_not_silently_discarded_or_duplicated(monkeypatch):
    client, _ = _client(monkeypatch, outcome=("changed", None))
    response = client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("evrak.odt", b"different content", "application/vnd.oasis.opendocument.text")},
        data={"evrakId": "stable-1", "dosyaEsasNo": "2024/1"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 409
    assert "içeriği değişmiş" in response.json()["error"]


def test_meta_parsing_reads_file_no_date_court_and_type():
    meta = parse_uyap_meta(
        "gerekceli_karar.pdf", "İstanbul 3. Asliye Hukuk Mahkemesi 2024/123 Esas 15.03.2025 tarihli"
    )

    assert meta["uyap_file_no"] == "2024/123"
    assert meta["doc_date"] == "2025-03-15"
    assert meta["doc_type"] == "Karar"  # liste sırasındaki ilk eşleşme (web/src/lib/uyap.ts ile aynı)
    assert "Asliye Hukuk" in (meta["uyap_birim"] or "")


def test_meta_parsing_ignores_impossible_dates():
    assert parse_uyap_meta("x.pdf", "31.02.2025")["doc_date"] is None


def test_file_name_and_extension_rules():
    assert safe_file_name(r"..\..\gizli/dosya adı.pdf") == "dosya_ad_.pdf"
    assert is_allowed_file("a.UDF") and not is_allowed_file("a.exe")


@pytest.mark.parametrize("failure,status,code,retryable", [
    (OSError(errno.ENOSPC, "private path and document data"), 507, "storage_full", False),
    (OSError(errno.EINVAL, "private path and document data"), 500, "storage_path_invalid", False),
    (OSError(errno.EACCES, "private path and document data"), 500, "storage_permission_denied", False),
    (OSError(errno.EIO, "private path and document data"), 500, "storage_io_error", False),
    (psycopg.errors.QueryCanceled("private query and document data"), 503, "database_temporarily_unavailable", True),
    (psycopg.errors.CheckViolation("private query and document data"), 500, "database_write_error", False),
])
def test_upload_reports_safe_actionable_storage_errors_and_closes_temp(monkeypatch, failure, status, code, retryable):
    client, _ = _client(monkeypatch)
    uploads = []

    def fail(owner, **kwargs):
        uploads.append(kwargs["data"])
        raise failure

    monkeypatch.setattr(office_public, "_store", fail)
    response = client.post("/api/public/v1/documents/upload",
                           files={"file": ("test.txt", b"synthetic", "text/plain")},
                           headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.json()["retryable"] is retryable
    assert "private" not in response.text and TOKEN not in response.text
    assert uploads[0]._closed


def test_upload_never_claims_success_when_database_insert_was_not_confirmed(monkeypatch):
    client, _ = _client(monkeypatch, outcome=("failed", None))
    response = client.post("/api/public/v1/documents/upload",
                           files={"file": ("test.txt", b"synthetic", "text/plain")},
                           headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 500
    assert response.json()["code"] == "document_write_unconfirmed"
    assert response.json()["retryable"] is False
    assert response.json().get("ok") is not True


def test_udf_text_is_read_from_content_xml():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("content.xml", "<doc><p>Merhaba dilekçe</p></doc>")

    assert "Merhaba dilekçe" in extract_text_sample("belge.udf", buffer.getvalue())
    assert extract_text_sample("bozuk.udf", b"not a zip") == ""


def test_preview_nul_is_removed_without_modifying_source_or_joining_numbers():
    source = b"120\x00340 lira"
    assert extract_text_sample("ek.txt", source) == "120 340 lira"
    assert source == b"120\x00340 lira"


def test_nul_in_identity_metadata_is_rejected_not_silently_changed(monkeypatch):
    client, stored = _client(monkeypatch)
    response = client.post("/api/public/v1/documents/upload",
                           files={"file": ("ek.txt", b"synthetic", "text/plain")},
                           data={"evrakId": "id\x001"}, headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 400
    assert not stored


def test_upload_accepts_odt_and_keeps_the_uyap_folder_path(monkeypatch):
    """Eklenti evrakı UYAP ağacındaki klasör yoluyla yollar; ODT (ön izleme biçimi) kabul edilir."""
    client, stored = _client(monkeypatch)

    response = client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("Gerekceli Karar.odt", b"PK\x03\x04odt", "application/vnd.oasis.opendocument.text")},
        data={
            "evrakId": "123",
            "evrakTuru": "Gerekçeli Karar",
            "dosyaEsasNo": "2024/2000",
            "klasorYolu": "2024/2000 (Ceza Dava Dosyası)  /  Gerekçeli Karar  /\n Ek 1",
        },
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert stored[0]["file_name"] == "123-Gerekceli_Karar.odt"
    overrides = stored[0]["overrides"]
    assert overrides["uyap_path"] == "2024/2000 (Ceza Dava Dosyası) / Gerekçeli Karar / Ek 1"  # boşluklar sadeleşir
    assert overrides["doc_type"] == "Gerekçeli Karar"


def test_upload_accepts_html_receipt_and_extracts_text(monkeypatch):
    client, stored = _client(monkeypatch)
    html = '<html><head><meta charset="windows-1254"></head><body>VEKALET PULU MAKBUZU T.C. ADALET BAKANLIĞI Makbuz No 123</body></html>'.encode("cp1254")
    response = client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("Vekalet Pulu Makbuzu.html", html, "text/html")},
        data={"evrakId": "receipt-1", "evrakTuru": "Makbuz", "dosyaEsasNo": "2024/55"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert stored[0]["file_name"].endswith(".html")
    assert stored[0]["data"] == html
    assert "BAKANLIĞI" in extract_text_sample(stored[0]["file_name"], stored[0]["data"])


def test_folder_path_is_capped_and_optional(monkeypatch):
    client, stored = _client(monkeypatch)

    client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
        data={"klasorYolu": "k" * 900},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("b.pdf", b"%PDF-1.4", "application/pdf")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert len(stored[0]["overrides"]["uyap_path"]) == 400
    assert stored[1]["overrides"]["uyap_path"] is None


def test_encrypted_uyap_evrak_ids_never_end_up_in_the_file_name(monkeypatch):
    """Gerçek portalda evrak_id şifreli bir değerdir (tırnak, '/', '+'); dosya adına ham hâliyle girerse
    Windows yazamaz ("Kayıt hatası"). Kararlı bir özet kullanılır; kısa/düz kimlik olduğu gibi kalır."""
    client, stored = _client(monkeypatch)
    weird = '"hfHeLsx0lKef/FTtsb+ab==\\x"'

    for evrak_id, title in ((weird, "A.odt"), (weird, "A.odt"), (weird + "2", "A.odt"), ("123", "A.odt")):
        response = client.post(
            "/api/public/v1/documents/upload",
            files={"file": (title, b"PK\x03\x04", "application/vnd.oasis.opendocument.text")},
            data={"evrakId": evrak_id},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert response.status_code == 200

    names = [item["file_name"] for item in stored]
    assert all(set(name) <= set("abcdef0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz._") for name in names)
    assert not any(char in name for name in names for char in '"/\\+=*?<>|:')
    assert names[0] == names[1]  # aynı kimlik, aynı ön ek (yinelenen denetimi çalışabilsin)
    assert names[0] != names[2]  # farklı evrak, farklı ön ek
    assert names[3] == "123-A.odt"  # düz kimlik olduğu gibi


def test_evrak_id_prefix_rules():
    assert office_public.evrak_id_prefix(None) == "" and office_public.evrak_id_prefix("  ") == ""
    assert office_public.evrak_id_prefix("77") == "77"
    assert office_public.evrak_id_prefix("a.b-c_9") == "a.b-c_9"
    hashed = office_public.evrak_id_prefix('"x/y')
    assert len(hashed) == 12 and hashed == office_public.evrak_id_prefix('"x/y')
    assert office_public.evrak_id_prefix("k" * 80) != "k" * 80  # çok uzun kimlik de özetlenir


def test_known_documents_lists_only_the_evraks_already_stored_for_the_token_owner(monkeypatch):
    client, _ = _client(monkeypatch)
    seen = []

    def fake_keys(owner_id, esas_no, birim):
        seen.append((owner_id, esas_no, birim))
        return ["101", office_public.evrak_id_prefix("A+/b==")]

    monkeypatch.setattr(office_public, "_stored_keys", fake_keys)

    response = client.post(
        "/api/public/v1/documents/known",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"evrakIds": ["101", "A+/b==", "999", "", "bozuk"], "dosyaEsasNo": "2024/124", "birim": "Ankara 1. İcra Dairesi"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "known": ["101", "A+/b=="]}
    assert seen == [(OWNER, "2024/124", "Ankara 1. İcra Dairesi")]  # owner + case + court
    assert response.headers["access-control-allow-origin"] == "*"


def test_known_documents_requires_a_valid_token_and_a_sane_body(monkeypatch):
    client, _ = _client(monkeypatch)
    monkeypatch.setattr(office_public, "_stored_keys", lambda *args: [])

    assert client.post("/api/public/v1/documents/known", json={"evrakIds": []}).status_code == 401
    bad = client.post("/api/public/v1/documents/known", headers={"Authorization": "Bearer " + "x" * 32}, json={"evrakIds": []})
    assert bad.status_code == 401
    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert client.post("/api/public/v1/documents/known", headers=headers, content=b"not json").status_code == 422
    too_many = {"evrakIds": [str(number) for number in range(office_public.MAX_KNOWN_IDS + 1)]}
    assert client.post("/api/public/v1/documents/known", headers=headers, json=too_many).status_code == 422
    monkeypatch.setattr(office_public, "MAX_KNOWN_REQUEST_BYTES", 50)
    assert client.post("/api/public/v1/documents/known", headers=headers, json={"evrakIds": ["1" * 100]}).status_code == 413


def test_known_evrak_ids_uses_explicit_keys_and_ignores_oversized_ids():
    keys = ["ENC-12", "7"]
    assert office_public.known_evrak_ids(["ENC-12", "7", "8", "x" * 601], keys) == ["ENC-12", "7"]
    assert office_public.known_evrak_ids(["bozuk"], ["bozuk-ad-yok.pdf"]) == []


def test_known_documents_without_case_and_court_never_skip_evidence(monkeypatch):
    client, _ = _client(monkeypatch)
    monkeypatch.setattr(office_public, "_stored_keys", lambda *args: (_ for _ in ()).throw(AssertionError("Ambiguous query")))
    headers = {"Authorization": f"Bearer {TOKEN}"}
    for payload in ({"evrakIds": ["1"]}, {"evrakIds": ["1"], "dosyaEsasNo": "2024/1"},
                    {"evrakIds": ["1"], "dosyaEsasNo": "invalid", "birim": "Court"}):
        response = client.post("/api/public/v1/documents/known", json=payload, headers=headers)
        assert response.json() == {"ok": True, "known": []}


def test_same_named_same_sized_legacy_document_needs_matching_bytes(monkeypatch, tmp_path):
    old_file = tmp_path / "old.pdf"
    old_file.write_bytes(b"old!")
    old_id = uuid4()

    class Rows:
        def fetchall(self):
            return [{"id": old_id, "owner_id": OWNER, "storage_path": "legacy.pdf", "checksum_sha256": None}]

    class Connection:
        def execute(self, query, params):
            assert "file_name = %s" in query and params[:2] == ["same.pdf", 4]
            return Rows()

    monkeypatch.setattr(office_public, "_storage_path", lambda *_: old_file)
    args = {"file_name": "same.pdf", "size_bytes": 4, "uyap_file_no": "2024/1", "source": None}
    assert office_public.find_duplicate(Connection(), **args, checksum_sha256=hashlib.sha256(b"new!").hexdigest()) is None
    assert office_public.find_duplicate(Connection(), **args, checksum_sha256=hashlib.sha256(b"old!").hexdigest()) == old_id


def test_same_uyap_evrak_with_repacked_odt_is_not_imported_twice(monkeypatch, tmp_path):
    def odt(extra: str) -> bytes:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(
                "content.xml",
                '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body>'
                '<office:text><text:p>Aynı hukuki metin</text:p></office:text></office:body></office:document-content>',
            )
            archive.writestr("meta.xml", extra)
        return stream.getvalue()

    old_data, new_data = odt("eski"), odt("yeni paket metadata")
    stored_file = tmp_path / "old.odt"
    stored_file.write_bytes(old_data)
    old_id = uuid4()

    class Rows:
        def fetchall(self):
            return [{"id": old_id, "owner_id": OWNER, "storage_path": "old.odt", "checksum_sha256": None}]

    class Connection:
        def execute(self, query, params):
            assert "size_bytes = %s" not in query
            return Rows()

    monkeypatch.setattr(office_public, "_storage_path", lambda *_: stored_file)
    assert len(old_data) != len(new_data)
    assert office_public.find_duplicate(
        Connection(), file_name="abc-Ek_1.odt", size_bytes=len(new_data),
        uyap_file_no="2024/1", source="uyap-avukat-eklentisi",
        evrak_key="abc", checksum_sha256=hashlib.sha256(new_data).hexdigest(),
        content_text=" ".join(extract_text_sample("abc-Ek_1.odt", new_data).split()),
    ) == old_id


def test_upload_without_a_uyap_identity_is_refused_before_reading_the_body(monkeypatch):
    """Dosyalar karışmasın: UYAP kişisi bilinmeyen eklentinin evrakı hiçbir hesaba yazılmaz (kullanıcı kararı 2026-10-16)."""
    client, stored = _client(monkeypatch, identity=False)
    response = client.post("/api/public/v1/documents/upload", files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")},
                           data={"evrakId": "1"}, headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 428 and response.json()["code"] == "uyap_identity_required"
    assert stored == [] and client.identity_checks == []
    known = client.post("/api/public/v1/documents/known", headers={"Authorization": f"Bearer {TOKEN}"}, json={"evrakIds": ["1"]})
    assert known.status_code == 428


def test_each_uploaded_document_is_marked_with_the_uyap_person_it_came_from(monkeypatch):
    """Dosyalar kimin UYAP'ından geldiyse onun altında durur (kullanıcı kararı 2026-10-16); kimse engellenmez."""
    document_id = uuid4()
    client, stored = _client(monkeypatch, outcome=("inserted", document_id))
    response = client.post("/api/public/v1/documents/upload", files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")},
                           data={"evrakId": "1"}, headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200 and len(stored) == 1
    [(owner_id, identity)] = client.identity_checks
    assert owner_id == OWNER and identity.kind == "tc" and identity.display == "AYSE YİLMAZ"
    assert client.marks == [(OWNER, ACCOUNT, {"document_id": document_id})]


def test_a_known_check_marks_the_files_unattributed_documents_for_that_person(monkeypatch):
    client, _ = _client(monkeypatch)
    monkeypatch.setattr(office_public, "_stored_keys", lambda owner, esas, birim: ["k1"])
    response = client.post("/api/public/v1/documents/known", headers={"Authorization": f"Bearer {TOKEN}"},
                           json={"evrakIds": ["1"], "dosyaEsasNo": "2024/1", "birim": "Ankara 1. Asliye Hukuk"})
    assert response.status_code == 200
    assert client.marks == [(OWNER, ACCOUNT, {"esas_no": "2024/1", "birim": "Ankara 1. Asliye Hukuk"})]


def test_a_display_name_with_digits_is_not_accepted_so_no_id_number_can_be_stored(monkeypatch):
    client, stored = _client(monkeypatch)
    response = client.post("/api/public/v1/documents/upload", files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")},
                           data={"evrakId": "1"}, headers={"Authorization": f"Bearer {TOKEN}", "X-UYAP-Display": "12345678901"})
    assert response.status_code == 428 and stored == [] and client.identity_checks == []

