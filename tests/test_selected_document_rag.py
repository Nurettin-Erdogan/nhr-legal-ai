"""Explicit office-document selection: authorization, SQL scope and pipeline regression."""
import contextlib
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.ai import document_selection, pipeline, retrieval, routes
from api.ai.cache import answer_cache_key
from api.auth.routes import current_user_id
from api.schemas import AIAnswerRequest

QUESTION = "Seçili belgede ödeme tutarı nedir?"


def test_request_selection_is_bounded_deduplicated_and_can_narrow_a_case():
    doc, case = uuid4(), uuid4()
    request = AIAnswerRequest(question=QUESTION, case_id=case, selected_document_ids=[doc, doc])
    assert request.selected_document_ids == [doc]
    for options in ({"project_id": uuid4(), "selected_document_ids": [doc]},
                    {"selected_document_ids": [uuid4() for _ in range(41)]},
                    {"selected_document_ids": ["not-a-uuid"]}):
        with pytest.raises(ValidationError):
            AIAnswerRequest(question=QUESTION, **options)


def connection_rows(monkeypatch, rows):
    seen = []

    @contextlib.contextmanager
    def connect(owner):
        def execute(sql, args):
            seen.append((owner, sql, args))
            return SimpleNamespace(fetchall=lambda: rows)
        yield SimpleNamespace(execute=execute)

    monkeypatch.setattr(document_selection, "authenticated_database_connection", connect)
    return seen


def test_selection_validates_every_id_under_owner_rls_and_preserves_ocr(monkeypatch):
    owner, doc, case = uuid4(), uuid4(), uuid4()
    seen = connection_rows(monkeypatch, [{"id": doc, "ready": True, "ocr": True}])
    coverage = document_selection.selected_document_coverage(owner, [doc], case)
    assert coverage == {"total": 1, "ready": 1, "pending": 0, "ocr": 1, "failed": []}
    assert seen[0][0] == str(owner) and seen[0][2] == ([doc], case, case)
    assert "od.deleted_at IS NULL" in seen[0][1] and "d.deleted_at IS NULL" in seen[0][1]
    assert "document_chunks" in seen[0][1]


@pytest.mark.parametrize("kind,status", [("anonymous", 401), ("foreign", 404), ("missing", 404),
                                        ("trash", 404), ("wrong_case", 404), ("pending", 409)])
def test_inaccessible_or_unreadable_selection_never_falls_back_to_the_corpus(monkeypatch, kind, status):
    doc = uuid4()
    rows = [{"id": doc, "ready": False, "ocr": False}] if kind == "pending" else []
    connection_rows(monkeypatch, rows)
    with pytest.raises(HTTPException) as error:
        document_selection.selected_document_coverage(None if kind == "anonymous" else uuid4(), [doc])
    assert error.value.status_code == status


def test_database_failure_is_not_reported_as_missing_documents(monkeypatch):
    @contextlib.contextmanager
    def broken(owner):
        raise psycopg.OperationalError("unavailable")
        yield
    monkeypatch.setattr(document_selection, "authenticated_database_connection", broken)
    with pytest.raises(HTTPException) as error:
        document_selection.selected_document_coverage(uuid4(), [uuid4()])
    assert error.value.status_code == 503


@pytest.mark.parametrize("endpoint", ["/answer", "/answer/progress"])
def test_both_endpoints_reject_foreign_selection_before_model_or_stream(monkeypatch, endpoint):
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[current_user_id] = lambda: uuid4()
    connection_rows(monkeypatch, [])
    response = TestClient(app).post("/api/ai" + endpoint, json={
        "question": QUESTION, "selected_document_ids": [str(uuid4())],
    })
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("hybrid", [False, True])
def test_all_retrieval_paths_are_parameterized_and_selection_scoped(monkeypatch, hybrid):
    calls = []
    monkeypatch.setattr(retrieval, "_execute_retrieval", lambda connection, sql, params: calls.append((sql, params)) or [])
    monkeypatch.setattr(retrieval, "lexical_hits_insufficient", lambda *args: True)
    doc, case = str(uuid4()), str(uuid4())
    retrieval.retrieve_document_contexts(None, question=QUESTION, case_id=case, document_ids=[doc], top_k=5,
                                        query_embedding=[0.1] if hybrid else None, embedding_model="m")
    assert len(calls) == 2  # strict/hybrid plus broad fallback
    for sql, params in calls:
        assert "office_doc.id = ANY(%(document_ids)s::uuid[])" in sql
        assert "office_doc.deleted_at IS NULL" in sql and "document.deleted_at IS NULL" in sql
        assert "office_doc.case_id = %(case_id)s" in sql
        assert params["document_ids"] == [doc] and params["case_id"] == case
        assert doc not in sql and case not in sql
    if hybrid:
        assert calls[0][0].count("office_doc.id = ANY(%(document_ids)s::uuid[])") == 2


def test_selected_scope_without_case_is_supported_but_project_mix_is_rejected(monkeypatch):
    monkeypatch.setattr(retrieval, "_execute_retrieval", lambda *args: [])
    assert retrieval.retrieve_document_contexts(None, question=QUESTION, document_ids=[str(uuid4())], top_k=5) == []
    with pytest.raises(ValueError):
        retrieval.retrieve_document_contexts(None, question=QUESTION, project_id=str(uuid4()), document_ids=[str(uuid4())], top_k=5)


@pytest.mark.parametrize("case_scoped", [False, True])
def test_selected_facts_never_inject_unselected_case_records_or_general_law(monkeypatch, case_scoped):
    doc, owner = uuid4(), uuid4()
    seen = {}

    @contextlib.contextmanager
    def connect(user):
        assert user == str(owner)
        yield object()

    def forbidden(*args, **kwargs):
        pytest.fail("Selection widened beyond chosen documents")

    def documents(connection, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(pipeline, "authenticated_database_connection", connect)
    monkeypatch.setattr(pipeline, "selected_document_coverage", lambda *a: {"total": 1, "ready": 1, "ocr": 1})
    monkeypatch.setattr(pipeline, "retrieve_document_contexts", documents)
    for name in ("record_contexts", "retrieve_contexts", "sweep_unindexed"):
        monkeypatch.setattr(pipeline, name, forbidden)
    info = {}
    result = pipeline._retrieve(AIAnswerRequest(question=QUESTION, selected_document_ids=[doc],
                                               case_id=uuid4() if case_scoped else None),
                                user_id=owner, top_k=5, query_embedding=None, embedding_model="m", diagnostics=info)
    assert result == [] and seen["document_ids"] == [str(doc)]
    assert info["document_scope"]["file_only"] and info["document_scope"]["ocr"] == 1


def test_selected_legal_question_also_searches_verified_law(monkeypatch):
    @contextlib.contextmanager
    def connect(owner):
        yield object()
    seen = []
    monkeypatch.setattr(pipeline, "authenticated_database_connection", connect)
    monkeypatch.setattr(pipeline, "selected_document_coverage", lambda *a: {})
    monkeypatch.setattr(pipeline, "retrieve_document_contexts", lambda *a, **kw: [])
    monkeypatch.setattr(pipeline, "retrieve_contexts", lambda *a, **kw: seen.append(kw) or [])
    monkeypatch.setattr(pipeline, "_case_statute_contexts", lambda *a, **kw: [])
    pipeline._retrieve(AIAnswerRequest(question="Seçili sözleşme kanuna uygun mu?", selected_document_ids=[uuid4()]),
                       user_id=uuid4(), top_k=5, query_embedding=None, embedding_model="m")
    assert len(seen) == 1


def test_cache_separates_selections_and_owners_even_if_retrieved_chunks_overlap():
    first, second, owner = uuid4(), uuid4(), uuid4()
    base = dict(question=QUESTION, project_id=None, as_of=None, model="m", fingerprint="same-chunks")
    one = answer_cache_key(**base, selected_document_ids=[first], user_id=owner)
    assert one != answer_cache_key(**base, selected_document_ids=[first, second], user_id=owner)
    assert one != answer_cache_key(**base, selected_document_ids=[first], user_id=uuid4())
    assert answer_cache_key(**base, selected_document_ids=[first, second]) == answer_cache_key(**base, selected_document_ids=[second, first])


def test_selected_documents_cannot_be_bypassed_by_the_fast_statute_shortcut(monkeypatch):
    settings = SimpleNamespace(ai_provider="deepseek", ai_model="synthetic", ollama_base_url="http://127.0.0.1",
        ollama_timeout_seconds=1, ollama_max_output_tokens=256, ollama_num_ctx=4096, ollama_keep_alive="1m",
        rag_top_k=6, rag_context_chars=2400, rag_query_embedding=False, embedding_model="test")
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(pipeline, "create_provider", lambda **kw: SimpleNamespace(model="synthetic"))
    for name in ("pause_embeddings", "resume_embeddings", "unload_ollama_model", "verify_pending_statute", "verify_relevant_pending_statute"):
        monkeypatch.setattr(pipeline, name, lambda *a, **kw: None)
    seen = []
    async def retrieve(request, **kwargs):
        seen.extend(request.selected_document_ids)
        return []
    def forbidden(**kwargs):
        pytest.fail("Fast statute lookup silently discarded the document selection")
    monkeypatch.setattr(pipeline, "_retrieve_with_warm_retry", retrieve)
    monkeypatch.setattr(pipeline, "try_fast_statute", forbidden)
    doc = uuid4()
    with pytest.raises(HTTPException) as error:
        asyncio.run(pipeline.execute_answer(AIAnswerRequest(question="TBK 344 maddesine göre seçili sözleşme uygun mu?",
                                                           selected_document_ids=[doc]), uuid4()))
    assert error.value.status_code == 422 and seen == [doc]
