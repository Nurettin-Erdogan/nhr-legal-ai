"""UYAP → dava → aranabilir belge: ayrı test DB'sinde gerçek runtime/RLS, sonunda rollback."""
from __future__ import annotations

import contextlib
import io
import os
import zipfile
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from starlette.requests import Request

from api import office, office_public, document_indexing, case_summary
from api.audit import AuditContext
from api.uyap_cases import case_number, court_key, link_document

needs_db = pytest.mark.skipif(not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured")


def test_case_identity_requires_a_real_file_number_and_normalizes_only_spacing_and_case():
    assert case_number(" 2024 / 195537 ") == "2024/195537"
    assert case_number("Bir karar 2024/195537 numarasıyla anılıyor") is None
    assert case_number("bilinmiyor") is None
    assert court_key("İSTANBUL  Anadolu  1. İcra Dairesi") == court_key("İstanbul Anadolu 1. İcra Dairesi")
    assert court_key("Ankara 1. İcra Dairesi") != court_key("Ankara 2. İcra Dairesi")


def test_case_lock_precedes_document_lock_during_linking():
    class Unavailable:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params):
            self.calls.append(sql)
            return self

        def fetchone(self):
            return None

    connection = Unavailable()
    assert link_document(connection, uuid4(), uuid4(), file_no="2024/195537",
                         birim="Ankara 1. İcra Dairesi", audit=AuditContext(uuid4())) == "unavailable"
    assert "pg_advisory_xact_lock" in connection.calls[0]
    assert "pg_advisory_xact_lock" in connection.calls[1]
    assert "FOR UPDATE" in connection.calls[2]


@pytest.fixture
def world(monkeypatch, tmp_path):
    connection = psycopg.connect(os.environ["NHR_TEST_DATABASE_URL"], row_factory=dict_row)
    alice, bob = uuid4(), uuid4()
    for owner in (alice, bob):
        connection.execute("INSERT INTO users (id, email, password_hash, full_name) VALUES (%s,%s,'test','Test')",
                           (owner, f"{owner}@test.invalid"))

    @contextlib.contextmanager
    def as_user(owner):
        connection.execute("RESET ROLE")
        connection.execute("SET LOCAL ROLE nhr_runtime")
        connection.execute("SELECT set_config('app.user_id', %s, true)", (str(owner),))
        yield connection

    for module in (office, office_public, document_indexing):
        monkeypatch.setattr(module, "authenticated_database_connection", as_user)
    monkeypatch.setattr(office_public, "_storage_path", lambda owner, key: tmp_path / key)
    monkeypatch.setattr(document_indexing, "_read_source", lambda owner, key: (tmp_path / key).read_bytes())
    try:
        yield connection, alice, bob, as_user
    finally:
        connection.rollback()
        connection.close()


def put(owner, *, birim="İstanbul Anadolu 1. İcra Dairesi", name="evrak.txt", data=b"Belge metni burada yer almaktadir.", evrak="ev-1"):
    return office_public._store(owner, file_name=name, data=data, source="uyap-avukat-eklentisi", mime_type="text/plain",
                               overrides={"uyap_file_no": "2024/195537", "uyap_birim": birim, "evrak_id": evrak},
                               dedupe_by_source=False, audit=AuditContext(uuid4()))


@needs_db
def test_imports_create_one_pending_case_and_retries_do_not_duplicate_evidence(world):
    connection, alice, bob, as_user = world
    outcome, first = put(alice)
    assert outcome == "inserted"
    assert put(alice) == ("duplicate", first)
    assert put(alice, name="ikinci.txt", evrak="ev-2")[0] == "inserted"
    with as_user(alice):
        cases = connection.execute("SELECT id,status,client_id FROM office_cases").fetchall()
        assert len(cases) == 1 and cases[0]["status"] == "pending" and cases[0]["client_id"] is None
        assert connection.execute("SELECT count(*) AS n FROM office_case_documents WHERE case_id=%s", (cases[0]["id"],)).fetchone()["n"] == 2
    with as_user(bob):
        assert connection.execute("SELECT id FROM office_cases").fetchall() == []
        assert connection.execute("SELECT id FROM office_case_documents").fetchall() == []


@needs_db
def test_nul_in_extracted_preview_does_not_reject_or_change_original_upload(world, tmp_path):
    connection, alice, _, as_user = world
    payload = b"120\x00340 lira (synthetic attachment)"
    outcome, document_id = put(alice, name="ek.txt", data=payload, evrak="nul-preview")
    assert outcome == "inserted"
    with as_user(alice):
        row = connection.execute("SELECT storage_path,content_excerpt,checksum_sha256 FROM office_case_documents WHERE id=%s",
                                 (document_id,)).fetchone()
    import hashlib
    assert row["content_excerpt"] == "120 340 lira (synthetic attachment)"
    assert row["checksum_sha256"] == hashlib.sha256(payload).hexdigest()
    assert (tmp_path / row["storage_path"]).read_bytes() == payload
    assert put(alice, name="ek.txt", data=payload, evrak="nul-preview") == ("duplicate", document_id)


@needs_db
def test_opaque_archive_round_trip_checksum_deduplication_and_owner_isolation(world, tmp_path, monkeypatch):
    import hashlib
    from fastapi import HTTPException

    connection, alice, bob, as_user = world
    original = b"MZ\x00\x80\xff" + bytes(range(256)) * 11
    outcome, document_id = put(alice, name="attachment.customformat.bin", data=original, evrak="opaque-archive")
    assert outcome == "inserted"
    with as_user(alice):
        row = connection.execute("SELECT storage_path,checksum_sha256,content_excerpt FROM office_case_documents WHERE id=%s",
                                 (document_id,)).fetchone()
    assert row["checksum_sha256"] == hashlib.sha256(original).hexdigest()
    assert row["content_excerpt"] is None
    assert (tmp_path / row["storage_path"]).read_bytes() == original
    assert put(alice, name="attachment.customformat.bin", data=original, evrak="opaque-archive") == ("duplicate", document_id)
    with as_user(bob):
        assert connection.execute("SELECT id FROM office_case_documents WHERE id=%s", (document_id,)).fetchone() is None
    monkeypatch.setattr(office, "_storage_root", lambda: tmp_path)
    response = office.download_file(key=row["storage_path"], user_id=alice)
    assert response.media_type == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"
    with pytest.raises(HTTPException) as denied:
        office.download_file(key=row["storage_path"], user_id=bob)
    assert denied.value.status_code == 403
    indexed = document_indexing.index_office_document(alice, document_id)
    assert indexed.status == "failed" and "aranabilir değil" in indexed.error
    with as_user(alice):
        assert connection.execute("SELECT count(*) AS n FROM document_chunks c JOIN documents d ON d.id=c.document_id "
                                  "WHERE d.office_case_document_id=%s", (document_id,)).fetchone()["n"] == 0


@needs_db
def test_a_large_upload_is_stored_from_its_temporary_file_and_retries_do_not_duplicate_it(world, monkeypatch, tmp_path):
    """Boyut sınırı yok: büyük ek (canlıda 53 MB'lık zip) belleğe alınmadan temp dosyadan saklanır, özet/boyut doğru yazılır,
    aynı evrak yeniden gelince çoğalmaz. Eşik düşürülerek "büyük dosya" yolu küçük veriyle denenir."""
    from api.upload_stream import Upload

    monkeypatch.setattr(office_public, "IN_MEMORY_PARSE_BYTES", 1024)
    connection, alice, _, as_user = world
    payload = b"PK" + os.urandom(200_000)

    def send():
        upload = Upload.from_stream(io.BytesIO(payload))
        assert upload.small_bytes(1024) is None  # gerçekten "büyük" yoldayız
        return office_public._store(
            alice, file_name="ek-1.zip", data=upload, source="uyap-avukat-eklentisi", mime_type="application/zip",
            overrides={"uyap_file_no": "2024/195537", "uyap_birim": "İstanbul Anadolu 1. İcra Dairesi", "evrak_id": "ek-büyük"},
            dedupe_by_source=False, audit=AuditContext(uuid4()),
        )

    outcome, first = send()
    assert outcome == "inserted"
    with as_user(alice):
        row = connection.execute("SELECT storage_path, size_bytes, checksum_sha256, case_id FROM office_case_documents WHERE id=%s", (first,)).fetchone()
    assert row["size_bytes"] == len(payload) and row["case_id"] is not None
    import hashlib

    assert row["checksum_sha256"] == hashlib.sha256(payload).hexdigest()
    assert (tmp_path / row["storage_path"]).read_bytes() == payload
    files_before = sorted(p.name for p in tmp_path.rglob("*") if p.is_file())

    assert send() == ("duplicate", first)
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == files_before  # ikinci kopya yazılmadı, geçici dosya kalmadı


@needs_db
def test_same_file_number_in_different_courts_and_owners_is_never_merged(world):
    connection, alice, bob, as_user = world
    put(alice)
    put(alice, birim="Ankara 1. İcra Dairesi")
    put(bob)
    with as_user(alice):
        assert connection.execute("SELECT count(*) AS n FROM office_cases").fetchone()["n"] == 2
    with as_user(bob):
        assert connection.execute("SELECT count(*) AS n FROM office_cases").fetchone()["n"] == 1


@needs_db
def test_identical_legacy_files_in_different_courts_are_separate_documents(world):
    connection, alice, bob, as_user = world
    first = put(alice, evrak=None)
    second = put(alice, birim="Ankara 1. İcra Dairesi", evrak=None)
    assert first[0] == second[0] == "inserted" and first[1] != second[1]


@needs_db
def test_missing_court_is_not_deduplicated_against_a_known_court(world):
    connection, alice, bob, as_user = world
    known = put(alice, evrak=None)
    unknown = put(alice, birim=None, evrak=None)
    assert known[0] == unknown[0] == "inserted" and known[1] != unknown[1]
    assert put(alice, birim=None, evrak=None) == ("duplicate", unknown[1])


@needs_db
def test_existing_case_and_its_client_are_reused_without_changing_case_status(world):
    connection, alice, bob, as_user = world
    client, case = uuid4(), uuid4()
    with as_user(alice):
        connection.execute("INSERT INTO office_clients (id,owner_id,full_name) VALUES (%s,%s,'Own client')", (client, alice))
        connection.execute("INSERT INTO office_cases (id,owner_id,client_id,title,esas_no,court,status) VALUES (%s,%s,%s,'Existing','2024 / 195537','İstanbul Anadolu 1. İcra Dairesi','closed')", (case, alice, client))
    _, document = put(alice)
    with as_user(alice):
        row = connection.execute("SELECT case_id,client_id FROM office_case_documents WHERE id=%s", (document,)).fetchone()
        assert row == {"case_id": case, "client_id": client}
        assert connection.execute("SELECT status FROM office_cases WHERE id=%s", (case,)).fetchone()["status"] == "closed"


@needs_db
def test_ambiguous_cases_and_manual_links_are_preserved(world):
    connection, alice, bob, as_user = world
    with as_user(alice):
        ids = [uuid4(), uuid4()]
        for case in ids:
            connection.execute("INSERT INTO office_cases (id,owner_id,title,case_no,court) VALUES (%s,%s,'Own','2024/195537','İstanbul Anadolu 1. İcra Dairesi')", (case, alice))
    _, document = put(alice)
    with as_user(alice):
        assert connection.execute("SELECT case_id FROM office_case_documents WHERE id=%s", (document,)).fetchone()["case_id"] is None
        connection.execute("UPDATE office_case_documents SET case_id=%s WHERE id=%s", (ids[1], document))
        assert link_document(connection, alice, document, file_no="2024/195537", birim="Farklı mahkeme", audit=AuditContext(uuid4())) == "already_linked"
        assert connection.execute("SELECT case_id FROM office_case_documents WHERE id=%s", (document,)).fetchone()["case_id"] == ids[1]
    with as_user(bob):
        assert link_document(connection, bob, document, file_no="2024/195537", birim="İstanbul Anadolu 1. İcra Dairesi", audit=AuditContext(uuid4())) == "unavailable"


@needs_db
def test_quoted_metadata_does_not_create_cases_and_explicit_metadata_links_legacy_duplicates(world):
    connection, alice, bob, as_user = world
    _, document = office_public._store(alice, file_name="eski.txt", data="İstanbul 1. İcra Dairesi 2024/195537 dosyasına atıf.".encode(),
                                      source="uyap", mime_type="text/plain", overrides={}, dedupe_by_source=True, audit=AuditContext(uuid4()))
    with as_user(alice):
        assert connection.execute("SELECT id FROM office_cases").fetchall() == []
        assert link_document(connection, alice, document, file_no="2024/195537", birim="İstanbul 1. İcra Dairesi", audit=AuditContext(uuid4())) == "linked"


@needs_db
def test_facts_count_all_ready_documents_even_when_the_page_is_short(world):
    connection, alice, bob, as_user = world
    for index in range(45):
        _, document = put(alice, name=f"belge-{index}.txt", evrak=f"ev-{index}")
        assert document_indexing.index_office_document(alice, document).status == "ready"
    with as_user(alice):
        case = connection.execute("SELECT id FROM office_cases").fetchone()["id"]
    first = office.case_document_facts(case, alice, offset=0, limit=40)
    last = office.case_document_facts(case, alice, offset=40, limit=40)
    assert first["ready"] == first["total"] == 45 and len(first["documents"]) == 40 and first["has_more"]
    assert last["ready"] == 45 and len(last["documents"]) == 5 and not last["has_more"]
    assert len({item["id"] for item in first["documents"] + last["documents"]}) == 45


@needs_db
def test_zip_attachment_is_indexed_with_member_provenance_in_its_case(world):
    connection, alice, bob, as_user = world
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ekler/beyan.txt", "Davacı 01.03.2025 tarihinde 500 TL yatırdı.")
    _, document = put(alice, name="Ek_1.zip", data=buffer.getvalue())
    assert document_indexing.index_office_document(alice, document).status == "ready"
    with as_user(alice):
        case = connection.execute("SELECT id FROM office_cases").fetchone()["id"]
        text = case_summary.load_ready_documents(connection, case)[0]["text"]
        assert "Arşiv eki: ekler/beyan.txt" in text and "500 TL" in text


@needs_db
def test_existing_archive_can_be_linked_only_with_the_owners_authenticated_endpoint(world):
    connection, alice, bob, as_user = world
    _, document = put(alice, birim=None)
    with as_user(alice):
        connection.execute("UPDATE office_case_documents SET uyap_birim='İstanbul 1. İcra Dairesi' WHERE id=%s", (document,))
    request = Request({"type": "http", "headers": [], "method": "POST", "path": "/api/office/uyap/link-cases"})
    assert office.link_uyap_cases(bob, request)["linked"] == 0
    assert office.link_uyap_cases(alice, request)["linked"] == 1
    assert office.link_uyap_cases(alice, request)["linked"] == 0


@needs_db
def test_link_cursor_reaches_documents_after_a_full_page_of_missing_metadata(world):
    connection, alice, bob, as_user = world
    with as_user(alice):
        for _ in range(501):
            connection.execute(
                "INSERT INTO office_case_documents (id,owner_id,file_name,storage_path,size_bytes,source) "
                "VALUES (%s,%s,'old.txt',%s,1,'uyap')", (uuid4(), alice, str(uuid4())),
            )
    request = Request({"type": "http", "headers": [], "method": "POST", "path": "/api/office/uyap/link-cases"})
    first = office.link_uyap_cases(alice, request)
    assert first["missing_metadata"] == 500 and first["has_more"] and first["next_cursor"]
    from uuid import UUID
    last = office.link_uyap_cases(alice, request, after=UUID(first["next_cursor"]))
    assert last["missing_metadata"] == 1 and not last["has_more"] and last["next_cursor"] is None


@needs_db
def test_same_identity_is_duplicate_after_rename_or_file_number_spacing(world):
    connection, alice, _, as_user = world
    first = put(alice, name="ilk.txt")
    assert put(alice, name="yeni.txt") == ("duplicate", first[1])
    with as_user(alice):
        # Legacy row already stored with whitespace: no destructive migration needed.
        connection.execute("UPDATE office_case_documents SET uyap_file_no='2024 / 195537' WHERE id=%s", (first[1],))
    assert put(alice, name="son.txt") == ("duplicate", first[1])
    with as_user(alice):
        assert connection.execute("SELECT count(*) AS n FROM office_case_documents").fetchone()["n"] == 1
    assert put(alice, name="son.txt", data=b"Actually changed text.")[0] == "changed"


@needs_db
def test_case_link_refuses_a_conflicting_explicit_client(world):
    connection, alice, _, as_user = world
    a, b, case, doc = uuid4(), uuid4(), uuid4(), uuid4()
    with as_user(alice):
        for client in (a, b):
            connection.execute("INSERT INTO office_clients (id,owner_id,full_name) VALUES (%s,%s,'Test')", (client, alice))
        connection.execute("INSERT INTO office_cases (id,owner_id,client_id,title,case_no,court) VALUES (%s,%s,%s,'Test','2024/77','Court')", (case, alice, b))
        connection.execute("INSERT INTO office_case_documents (id,owner_id,client_id,file_name,storage_path,source,uyap_file_no,uyap_birim) VALUES (%s,%s,%s,'test.txt',%s,'uyap','2024/77','Court')", (doc, alice, a, str(doc)))
    request = Request({"type": "http", "headers": [], "method": "POST", "path": "/api/office/uyap/link-cases"})
    assert office.link_uyap_cases(alice, request)["client_conflict"] == 1
    with as_user(alice):
        assert connection.execute("SELECT case_id,client_id FROM office_case_documents WHERE id=%s", (doc,)).fetchone() == {"case_id": None, "client_id": a}


@needs_db
def test_case_creation_preserves_an_explicit_document_client(world):
    connection, alice, _, as_user = world
    client, doc = uuid4(), uuid4()
    with as_user(alice):
        connection.execute("INSERT INTO office_clients (id,owner_id,full_name) VALUES (%s,%s,'Test')", (client, alice))
        connection.execute("INSERT INTO office_case_documents (id,owner_id,client_id,file_name,storage_path,source) VALUES (%s,%s,%s,'test.txt',%s,'uyap')", (doc, alice, client, str(doc)))
        assert link_document(connection, alice, doc, file_no="2024/78", birim="Court", audit=AuditContext(uuid4())) == "linked"
        row = connection.execute("SELECT c.client_id FROM office_cases c JOIN office_case_documents d ON d.case_id=c.id WHERE d.id=%s", (doc,)).fetchone()
        assert row["client_id"] == client


@needs_db
def test_manual_import_hashes_content_checks_sync_owner_and_does_not_infer_case(world):
    connection, alice, bob, as_user = world
    run = uuid4()
    with as_user(bob):
        connection.execute("INSERT INTO office_uyap_sync_runs (id,owner_id,status) VALUES (%s,%s,'running')", (run, bob))
    options = dict(file_name="evrak.txt", data=b"Plain synthetic document.", source="uyap", mime_type="text/plain",
                   overrides={"metadata_name": "2024/88/evrak.txt"}, dedupe_by_source=True, audit=AuditContext(uuid4()))
    assert office_public._store(alice, **options, sync_run_id=run) == ("invalid_sync", None)
    first = office_public._store(alice, **options)
    assert first[0] == "inserted" and office_public._store(alice, **options) == ("duplicate", first[1])
    with as_user(alice):
        row = connection.execute("SELECT checksum_sha256,case_id,uyap_file_no FROM office_case_documents WHERE id=%s", (first[1],)).fetchone()
        assert row["checksum_sha256"] and row["case_id"] is None and row["uyap_file_no"] == "2024/88"


@needs_db
def test_known_ids_are_scoped_to_court_even_for_the_same_number(world):
    connection, alice, _, as_user = world
    put(alice, birim="Ankara 1. İcra Dairesi", evrak="ankara-only")
    put(alice, birim="İstanbul 1. İcra Dairesi", evrak="istanbul-only")
    with as_user(alice):
        assert office_public.stored_keys_on(connection, "2024 / 195537", "Ankara 1. İcra Dairesi") == ["ankara-only"]
        assert office_public.stored_keys_on(connection, "2024/195537", "Different Court") == []
