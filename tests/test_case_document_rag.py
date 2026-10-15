"""Dava kapsamlı belge RAG: arama, izolasyon, istek doğrulaması ve pipeline bağlantısı."""

from __future__ import annotations

import contextlib
import io
import os
import zipfile
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import HTTPException
from psycopg.rows import dict_row
from pydantic import ValidationError

from api import document_indexing as indexing
from api.ai import pipeline, retrieval, routes
from api.ai.retrieval import (
    DOCUMENT_CASE_HYBRID_RETRIEVAL_SQL,
    DOCUMENT_HYBRID_RETRIEVAL_SQL,
    retrieve_document_contexts,
)
from api.ai.trust import usable_as_evidence
from api.schemas import AIAnswerRequest

QUESTION = "kıdem tazminatı talebi hakkında ne yazıyor?"


def _udf(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("content.xml", f"<template><content><![CDATA[{text}]]></content></template>")
    return buffer.getvalue()


# --- Veritabanı gerektirmeyen: istek ve SQL kapsamı ------------------------------------------------


def test_request_rejects_project_and_case_scope_together():
    AIAnswerRequest(question=QUESTION, case_id=uuid4())
    AIAnswerRequest(question=QUESTION, project_id=uuid4())
    with pytest.raises(ValidationError, match="birlikte verilemez"):
        AIAnswerRequest(question=QUESTION, project_id=uuid4(), case_id=uuid4())


def test_sql_scopes_are_distinct_and_never_unscoped():
    assert "document.project_id = %(project_id)s" in DOCUMENT_HYBRID_RETRIEVAL_SQL
    assert "%(case_id)s" not in DOCUMENT_HYBRID_RETRIEVAL_SQL
    assert DOCUMENT_CASE_HYBRID_RETRIEVAL_SQL.count("office_doc.case_id = %(case_id)s") == 2
    assert "%(project_id)s" not in DOCUMENT_CASE_HYBRID_RETRIEVAL_SQL
    for sql in (
        retrieval.DOCUMENT_LEXICAL_RETRIEVAL_SQL,
        retrieval.DOCUMENT_LEXICAL_BROAD_SQL,
        retrieval.DOCUMENT_CASE_LEXICAL_RETRIEVAL_SQL,
        retrieval.DOCUMENT_CASE_LEXICAL_BROAD_SQL,
    ):
        assert "%(project_id)s" in sql or "%(case_id)s" in sql


@pytest.mark.parametrize("kwargs", [{}, {"project_id": "a", "case_id": "b"}])
def test_document_search_requires_exactly_one_scope(kwargs):
    with pytest.raises(ValueError, match="tam biri"):
        retrieve_document_contexts(None, question=QUESTION, top_k=3, **kwargs)


def test_case_route_requires_login_and_hides_foreign_cases(monkeypatch):
    assert routes._require_case_access(None, None) is None
    with pytest.raises(HTTPException) as anonymous:
        routes._require_case_access(None, uuid4())
    assert anonymous.value.status_code == 401

    class Empty:
        def execute(self, *args, **kwargs):
            return SimpleNamespace(fetchone=lambda: None)

    @contextlib.contextmanager
    def fake_connection(user_id):
        yield Empty()

    monkeypatch.setattr(routes, "authenticated_database_connection", fake_connection)
    with pytest.raises(HTTPException) as missing:
        routes._require_case_access(uuid4(), uuid4())
    assert missing.value.status_code == 404  # başkasının davası ile olmayan dava ayırt edilemez


def test_pipeline_searches_the_case_scope_and_reports_coverage(monkeypatch):
    user, case = uuid4(), uuid4()
    seen: dict = {}

    @contextlib.contextmanager
    def fake_connection(user_id):
        yield object()

    monkeypatch.setattr(pipeline, "authenticated_database_connection", fake_connection)
    monkeypatch.setattr(pipeline, "retrieve_contexts", lambda *a, **k: [])
    monkeypatch.setattr(pipeline, "_case_statute_contexts", lambda *a, **k: [])
    monkeypatch.setattr(pipeline, "sweep_unindexed", lambda owner, **k: seen.update(sweep=(owner, k)))
    monkeypatch.setattr(
        pipeline, "case_document_coverage", lambda owner, case_id: {"case_id": str(case_id), "ready": 1}
    )

    def fake_documents(connection, **kwargs):
        seen["documents"] = kwargs
        return []

    monkeypatch.setattr(pipeline, "retrieve_document_contexts", fake_documents)
    diagnostics: dict = {}

    pipeline._retrieve(
        AIAnswerRequest(question=QUESTION, case_id=case),
        user_id=user,
        query_embedding=None,
        top_k=5,
        embedding_model="m",
        diagnostics=diagnostics,
    )

    assert seen["sweep"] == (user, {"case_id": case})
    assert seen["documents"]["case_id"] == str(case) and seen["documents"]["project_id"] is None
    assert diagnostics["document_scope"] == {"case_id": str(case), "ready": 1, "file_only": False}


def test_pipeline_rejects_anonymous_case_questions():
    with pytest.raises(HTTPException) as error:
        pipeline._retrieve(
            AIAnswerRequest(question=QUESTION, case_id=uuid4()),
            user_id=None,
            query_embedding=None,
            top_k=5,
            embedding_model="m",
        )
    assert error.value.status_code == 401


# --- Gerçek RLS'li veritabanı ----------------------------------------------------------------------

needs_db = pytest.mark.skipif(
    not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured"
)


@pytest.fixture
def db(monkeypatch):
    connection = psycopg.connect(os.environ["NHR_TEST_DATABASE_URL"], row_factory=dict_row)
    alice, bob = uuid4(), uuid4()
    files: dict[str, bytes] = {}
    try:
        for user in (alice, bob):
            connection.execute(
                "INSERT INTO users (id, email, password_hash, full_name) VALUES (%s, %s, %s, %s)",
                (user, f"{user}@test.invalid", "not-a-password", "Test"),
            )

        def become(user: UUID | None):
            connection.execute("RESET ROLE")
            if user is not None:
                connection.execute("SET LOCAL ROLE nhr_runtime")
                connection.execute("SELECT set_config('app.user_id', %s, true)", (str(user),))

        @contextlib.contextmanager
        def as_user(user_id: str):
            become(UUID(user_id))
            yield connection

        def fake_read(owner_id, storage_path):
            return files[storage_path]

        monkeypatch.setattr(indexing, "authenticated_database_connection", as_user)
        monkeypatch.setattr(indexing, "_read_source", fake_read)
        yield SimpleNamespace(connection=connection, alice=alice, bob=bob, files=files, become=become)
    finally:
        connection.rollback()
        connection.close()


def _case(world, owner, title="Dava"):
    case_id = uuid4()
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_cases (id, owner_id, title) VALUES (%s, %s, %s)", (case_id, owner, title)
    )
    return case_id


def _indexed_document(world, owner, case_id, text, name="karar.udf"):
    document_id = uuid4()
    path = f"{owner}/{document_id}"
    data = _udf(text)
    world.files[path] = data
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_case_documents (id, owner_id, case_id, file_name, storage_path, size_bytes) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (document_id, owner, case_id, name, path, len(data)),
    )
    assert indexing.index_office_document(owner, document_id).status == "ready"
    return document_id


def _search(world, user, case_id, **kwargs):
    world.become(user)
    return retrieve_document_contexts(
        world.connection, question=QUESTION, case_id=str(case_id), top_k=5, **kwargs
    )


@needs_db
def test_explicit_selection_excludes_other_documents_case_and_owner_in_real_rls(db):
    case, other = _case(db, db.alice), _case(db, db.alice)
    text = "Davacı işçi kıdem tazminatı talep etmektedir."
    chosen = _indexed_document(db, db.alice, case, text, "secilen.udf")
    _indexed_document(db, db.alice, case, text, "secilmeyen.udf")
    another_case = _indexed_document(db, db.alice, other, text, "baska.udf")
    assert [c.title for c in _search(db, db.alice, case, document_ids=[str(chosen)])] == ["secilen.udf"]
    assert _search(db, db.bob, case, document_ids=[str(chosen)]) == []
    assert _search(db, db.alice, case, document_ids=[str(another_case)]) == []
    db.become(None)
    db.connection.execute("UPDATE office_case_documents SET deleted_at=now() WHERE id=%s", (chosen,))
    assert _search(db, db.alice, case, document_ids=[str(chosen)]) == []


@needs_db
def test_owner_finds_case_documents_labelled_as_user_documents(db):
    case = _case(db, db.alice)
    _indexed_document(
        db, db.alice, case, "Davacı işçi kıdem tazminatı talep etmektedir. İşten çıkış 2024 yılındadır."
    )

    results = _search(db, db.alice, case)

    assert len(results) == 1
    context = results[0]
    assert context.source_type == "document" and context.verification == "user_document"
    assert context.authority == "Kullanıcı belgesi" and context.title == "karar.udf"
    assert "kıdem tazminatı" in context.content
    assert usable_as_evidence(context)  # kullanıcı belgesi kanıttır ama "resmî" etiketi taşımaz
    assert context.verification != "official"


@needs_db
def test_hybrid_query_runs_in_case_scope_and_keeps_unembedded_chunks_searchable(db):
    case = _case(db, db.alice)
    _indexed_document(db, db.alice, case, "Davacı işçi kıdem tazminatı talep etmektedir.")

    results = _search(db, db.alice, case, query_embedding=[0.01] * 768, embedding_model="nomic-embed-text")

    assert [c.verification for c in results] == ["user_document"]


@needs_db
def test_other_users_and_other_cases_never_see_the_documents(db):
    mine = _case(db, db.alice, "Benim")
    other = _case(db, db.alice, "Başka")
    _indexed_document(db, db.alice, mine, "Davacı işçi kıdem tazminatı talep etmektedir.")

    assert _search(db, db.bob, mine) == []  # başka kullanıcı: RLS
    assert _search(db, db.alice, other) == []  # aynı kullanıcı, başka dava


@needs_db
def test_scope_follows_the_document_when_it_is_linked_to_another_case(db):
    first, second = _case(db, db.alice, "A"), _case(db, db.alice, "B")
    document = _indexed_document(db, db.alice, first, "Davacı işçi kıdem tazminatı talep etmektedir.")
    assert len(_search(db, db.alice, first)) == 1

    db.become(None)
    db.connection.execute("UPDATE office_case_documents SET case_id = %s WHERE id = %s", (second, document))

    assert _search(db, db.alice, first) == []
    assert len(_search(db, db.alice, second)) == 1  # ek bir indeks güncellemesi gerekmedi


@needs_db
def test_failed_documents_are_never_searched_and_show_up_in_coverage(db):
    case = _case(db, db.alice)
    _indexed_document(db, db.alice, case, "Davacı işçi kıdem tazminatı talep etmektedir.", name="iyi.udf")
    db.become(None)
    bad_id = uuid4()
    db.files[f"{db.alice}/{bad_id}"] = b"II*\x00"
    db.connection.execute(
        "INSERT INTO office_case_documents (id, owner_id, case_id, file_name, storage_path, size_bytes) "
        "VALUES (%s, %s, %s, 'tarama.tif', %s, 4)",
        (bad_id, db.alice, case, f"{db.alice}/{bad_id}"),
    )
    indexing.index_office_document(db.alice, bad_id)
    pending_id = uuid4()
    db.connection.execute("RESET ROLE")
    db.connection.execute(
        "INSERT INTO office_case_documents (id, owner_id, case_id, file_name, storage_path, size_bytes) "
        "VALUES (%s, %s, %s, 'bekleyen.pdf', %s, 4)",
        (pending_id, db.alice, case, f"{db.alice}/{pending_id}"),
    )

    coverage = indexing.case_document_coverage(db.alice, case)

    assert coverage["total"] == 3 and coverage["ready"] == 1 and coverage["pending"] == 1
    assert [item["file_name"] for item in coverage["failed"]] == ["tarama.tif"]
    assert "OCR" in coverage["failed"][0]["reason"]
    assert all(c.title == "iyi.udf" for c in _search(db, db.alice, case))


@needs_db
def test_coverage_is_empty_for_another_users_case(db):
    case = _case(db, db.alice)
    _indexed_document(db, db.alice, case, "Davacı işçi kıdem tazminatı talep etmektedir.")

    assert indexing.case_document_coverage(db.bob, case)["total"] == 0
