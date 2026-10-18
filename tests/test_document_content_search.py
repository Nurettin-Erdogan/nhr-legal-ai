"""Content search: literal matching, safe excerpts, real SQL on in-memory JSON fixtures."""

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from api.document_content_search import MATCH_JOIN, content_pattern, match_excerpt
from api.document_organization import folder_key, organized_documents
from api.main import app
from api import office
from api.auth.routes import current_user_id


def test_literal_turkish_phrase_and_safe_excerpt():
    excerpt = match_excerpt("Başlangıç\n\tİCRA   EMRİ <script>son</script>", "icra emri", page_number=7)
    assert excerpt == dict(before="Başlangıç ", match="İCRA EMRİ", after=" <script>son</script>",
                           page_number=7, section_title=None)
    assert content_pattern("  %50_indirim\\  ") == "%\\%50\\_indirim\\\\%"
    assert match_excerpt("başka", "olmayan") is None
    assert match_excerpt("metin", "") is None


def test_excerpt_is_bounded_and_does_not_invent_a_page():
    excerpt = match_excerpt("a" * 5000 + " İCRA " + "b" * 5000, "icra")
    assert len(excerpt["before"]) == 111 and len(excerpt["after"]) == 161
    assert excerpt["page_number"] is None
    assert excerpt["before"].startswith("…") and excerpt["after"].endswith("…")


@pytest.mark.parametrize("options", [{"search_in": "bad", "q": "abc"}, {"search_in": "content", "q": "a"}])
def test_invalid_mode_or_short_content_query_rejected_before_database(options):
    with pytest.raises(HTTPException) as error:
        organized_documents(None, uuid4(), source="all", category="", folder="", order="recent",
                            offset=0, limit=100, **options)
    assert error.value.status_code == 422


def test_content_endpoint_requires_login():
    assert TestClient(app).get("/api/office/case-documents/search",
                               params={"q": "icra", "search_in": "content"}).status_code == 401


def test_authenticated_route_validates_mode_and_passes_scope_and_timeout(monkeypatch):
    owner = uuid4()
    statements, forwarded = [], []

    class Connection:
        def execute(self, statement):
            statements.append(statement)

    @contextmanager
    def connection(user):
        assert user == str(owner)
        yield Connection()

    def search(conn, user, **kwargs):
        assert user == owner
        forwarded.append(kwargs)
        return dict(rows=[], total=0, folders=[], categories=[], content_coverage=dict(total=0, ready=0, pending=0, failed=0))

    monkeypatch.setattr(office, "authenticated_database_connection", connection)
    monkeypatch.setattr(office, "organized_documents", search)
    app.dependency_overrides[current_user_id] = lambda: owner
    try:
        client = TestClient(app)
        result = client.get("/api/office/case-documents/search", params={"q": "icra emri", "search_in": "content", "source": "uyap"})
        assert result.status_code == 200 and result.json()["content_coverage"]["ready"] == 0
        assert statements == ["SET LOCAL statement_timeout = '8s'"]
        assert forwarded[0]["search_in"] == "content" and forwarded[0]["source"] == "uyap"
        assert client.get("/api/office/case-documents/search", params={"search_in": "bad"}).status_code == 422
        assert client.get("/api/office/case-documents/search", params={"q": "a" * 101}).status_code == 422
        assert len(forwarded) == 1
    finally:
        app.dependency_overrides.pop(current_user_id, None)


def test_query_has_explicit_source_and_derived_ownership_and_no_excerpt_fallback():
    assert "indexed.uploaded_by = office_case_documents.owner_id" in MATCH_JOIN
    assert "indexed.deleted_at IS NULL AND indexed.status = 'ready'" in MATCH_JOIN
    assert "document_chunks" in MATCH_JOIN and "content_excerpt" not in MATCH_JOIN


def verify_postgres_content_search(connection):
    """CTEs shadow all actual tables; nothing in the user's archive is read or written."""
    owner, other = uuid4(), uuid4()
    now = datetime.now(timezone.utc).isoformat()
    sources, indexed, chunks = [], [], []

    def document(name="karar.pdf", *, who=owner, state="ready", source="uyap", deleted=None,
                 index_deleted=None, index_owner=None, kind="Karar", birim="Ankara", body="Ödeme İCRA\n EMRİ tebliğ edildi."):
        source_id, index_id = uuid4(), uuid4()
        sources.append(dict(id=str(source_id), owner_id=str(who), file_name=name, storage_path="fixture",
                            size_bytes=20, source=source, uyap_file_no="2024/100", uyap_birim=birim,
                            doc_type=kind, doc_date="2024-10-01", case_id=None, created_at=now, deleted_at=deleted))
        if state is not None:
            indexed.append(dict(id=str(index_id), office_case_document_id=str(source_id),
                                uploaded_by=str(index_owner or who), status=state, deleted_at=index_deleted))
        if body is not None:
            chunks.extend([
                dict(id=str(uuid4()), document_id=str(index_id), chunk_index=0, content="Sadece giriş.", page_number=1, section_title=None),
                dict(id=str(uuid4()), document_id=str(index_id), chunk_index=1, content=body, page_number=12, section_title="Sonuç"),
                dict(id=str(uuid4()), document_id=str(index_id), chunk_index=2, content=body, page_number=14, section_title=None),
            ])
        return str(source_id)

    target = document()
    manual = document(source="manual", kind="Dilekçe", birim="İstanbul")
    document(who=other)
    document(deleted=now)
    document(index_deleted=now)
    document(index_owner=other)
    document(state="failed")
    document(state=None, body=None)
    document(body=None)  # ready but no chunks: not searchable
    name_only = document("İCRA EMRİ.pdf", body="Başka konu.")
    literal = document(body="İndirim %50_belgesi hakkında.")

    class Fixtures:
        def execute(self, statement, params):
            prefix = """WITH office_case_documents AS (
                SELECT * FROM jsonb_to_recordset(%s) AS fixture(
                    id uuid, owner_id uuid, file_name text, storage_path text, size_bytes bigint,
                    source text, uyap_file_no text, uyap_birim text, doc_type text, doc_date date,
                    case_id uuid, created_at timestamptz, deleted_at timestamptz, uyap_account_id uuid)
            ), documents AS (
                SELECT * FROM jsonb_to_recordset(%s) AS fixture(id uuid, office_case_document_id uuid,
                    uploaded_by uuid, status text, deleted_at timestamptz)
            ), document_chunks AS (
                SELECT * FROM jsonb_to_recordset(%s) AS fixture(id uuid, document_id uuid,
                    chunk_index int, content text, page_number int, section_title text)
            ), """
            return connection.execute(prefix + statement.strip()[5:],
                                      (Jsonb(sources), Jsonb(indexed), Jsonb(chunks), *params))

    def search(**overrides):
        options = dict(q="icra emri", search_in="content", source="all", category="", folder="",
                       order="recent", offset=0, limit=100)
        options.update(overrides)
        return organized_documents(Fixtures(), owner, **options)

    result = search()
    assert {str(row["id"]) for row in result["rows"]} == {target, manual}
    assert result["total"] == 2  # duplicate chunks do not duplicate documents
    assert result["content_coverage"] == dict(total=9, ready=4, pending=4, failed=1)
    for row in result["rows"]:
        assert row["content_match"]["match"] == "İCRA EMRİ"
        assert row["content_match"]["page_number"] == 12
        assert "match_content" not in row
    assert search(offset=1, limit=1)["total"] == 2
    assert len(search(offset=1, limit=1)["rows"]) == 1
    assert search(summary_only=True)["rows"] == []
    assert sum(item["matching_count"] for item in result["folders"]) == 2
    assert search(source="uyap")["total"] == 1
    assert search(category="petition")["content_coverage"]["total"] == 1
    assert search(category="petition")["total"] == 1
    assert search(folder=folder_key("manual", "2024/100", "İstanbul"))["content_coverage"]["total"] == 1
    assert {str(row["id"]) for row in search(q="%50_")["rows"]} == {literal}
    assert search(q="'; DROP TABLE documents; --")["total"] == 0
    assert search(q="bulunamayan")["content_coverage"]["ready"] == 4
    assert search(q="")["total"] == 9  # empty query shows archive, not fake content matches
    assert {str(row["id"]) for row in search(search_in="metadata")["rows"]} == {name_only}


@pytest.mark.skipif(not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured")
def test_postgres_content_matching_filters_and_isolation():
    with psycopg.connect(os.environ["NHR_TEST_DATABASE_URL"], row_factory=dict_row) as connection:
        verify_postgres_content_search(connection)
