"""Account-independent archive contract: original bytes != parsed/searchable text."""
import asyncio
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import document_indexing, office, office_public
from api.document_processing import DocumentProcessingError
from api.uyap_meta import is_allowed_file

TOKEN = "synthetic-archive-token-not-a-secret"
IDENTITY = {"evrakId": "opaque-stable-id", "dosyaEsasNo": "2026/99", "birim": "Test Mahkemesi"}


@pytest.fixture
def archive_client(monkeypatch):
    owner, document_id = uuid4(), uuid4()
    stored = []

    def store(owner_id, **kwargs):
        upload = kwargs["data"]
        stored.append({**kwargs, "owner_id": owner_id, "bytes": upload.small_bytes(), "upload": upload})
        return "inserted", document_id

    monkeypatch.setattr(office_public, "_owner_for_token", lambda token: (uuid4(), owner) if token == TOKEN else None)
    monkeypatch.setattr(office_public, "_uyap_account", lambda *_: asyncio.sleep(0, result=uuid4()))  # UYAP kişisi ayrıca sınanır (test_uyap_account.py)
    monkeypatch.setattr(office_public, "_mark", lambda *_, **__: asyncio.sleep(0))
    monkeypatch.setattr(office_public, "_store", store)
    monkeypatch.setattr(office_public, "_schedule_index", lambda *args: None)
    app = FastAPI()
    app.include_router(office_public.router)
    return TestClient(app), stored, owner


@pytest.mark.parametrize("suffix", ["bin", "dat", "enc", "dcm", "heic", "webm", "flac", "gz", "tar", "bz2", "iso", "bak", "customformat", "exe", "ps1", "js", "msi", "lnk", "svg"])
def test_unknown_formats_are_archived_as_opaque_bytes_not_rejected_or_parsed(archive_client, suffix):
    client, stored, owner = archive_client
    original = bytes(range(256)) * 41
    response = client.post("/api/public/v1/documents/upload", headers={"Authorization": f"Bearer {TOKEN}"},
                           data=IDENTITY, files={"file": (f"attachment.{suffix}", original, "application/download")})
    assert response.status_code == 200, response.text
    assert response.json()["archiveOnly"] is True
    assert response.json()["searchable"] is False
    assert stored[0]["bytes"] == original
    assert stored[0]["owner_id"] == owner
    assert stored[0]["file_name"].endswith(".bin")
    assert stored[0]["mime_type"] == "application/octet-stream"
    assert stored[0]["overrides"]["evrak_id"] == IDENTITY["evrakId"]
    assert stored[0]["upload"]._closed
    assert not is_allowed_file(f"attachment.{suffix}"), "general upload whitelist must not be weakened"


@pytest.mark.parametrize("missing", ["evrakId", "dosyaEsasNo", "birim"])
def test_opaque_fallback_requires_stable_document_and_case_identity(archive_client, missing):
    client, stored, _ = archive_client
    fields = {k: v for k, v in IDENTITY.items() if k != missing}
    response = client.post("/api/public/v1/documents/upload", headers={"Authorization": f"Bearer {TOKEN}"},
                           data=fields, files={"file": ("a.bin", b"\x01\x02", "application/octet-stream")})
    assert response.status_code == 415
    assert not stored


@pytest.mark.parametrize("data,mime", [
    (b"<html><body>Login</body></html>", "application/octet-stream"),
    (b"<form><input type=password></form>", "application/download"),
    (b"<div>Hata Mesaji</div>", "application/download"),
    (b"<!-- portal response -->\n<html><body>Login</body></html>", "application/download"),
    (b"not really a document", "text/html"),
    ("\ufeff<html><body>Login</body></html>".encode("utf-16le"), "application/octet-stream"),
    ("\ufeff<html><body>Login</body></html>".encode("utf-16be"), "application/octet-stream"),
])
def test_portal_pages_cannot_use_the_binary_archive_fallback(archive_client, data, mime):
    client, stored, _ = archive_client
    response = client.post("/api/public/v1/documents/upload", headers={"Authorization": f"Bearer {TOKEN}"},
                           data=IDENTITY, files={"file": ("response.dat", data, mime)})
    assert response.status_code == 415
    assert not stored


def test_archive_requires_authentication_before_reading_the_body(archive_client):
    client, stored, _ = archive_client
    response = client.post("/api/public/v1/documents/upload", data=IDENTITY,
                           files={"file": ("a.bin", b"\x01\x02", "application/octet-stream")})
    assert response.status_code == 401
    assert not stored


def test_opaque_archive_is_not_read_into_memory_or_marked_searchable(monkeypatch, tmp_path):
    raw = tmp_path / "opaque.bin"
    raw.write_bytes(b"synthetic archive")
    monkeypatch.setattr(office, "_storage_path", lambda *args: raw)
    monkeypatch.setattr(type(raw), "read_bytes", lambda *args: pytest.fail("opaque body must not be read for indexing"))
    with pytest.raises(DocumentProcessingError, match="arşivlendi.*aranabilir değil"):
        document_indexing._read_source(uuid4(), "opaque.bin")


def test_quarantined_bytes_are_not_parsed_even_if_they_look_like_pdf():
    from api.document_processing import process_document
    with pytest.raises(DocumentProcessingError, match="arşivlendi.*aranabilir değil"):
        process_document("attachment.bin", b"%PDF-1.7\n", detect_type=True)
