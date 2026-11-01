"""Proje-belge API/RAG/kuyruk sınırları; canlı veri/ağ/model kullanılmaz."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api import project_documents as projects, document_jobs as jobs
from api.ai import workspace_scope, retrieval
from api.audit import AuditContext


def fake_connection(monkeypatch, module, handler):
    calls = []

    @contextmanager
    def connect(owner):
        class Connection:
            def execute(self, sql, args):
                calls.append((owner, sql, args))
                value = handler(sql, args)
                return SimpleNamespace(
                    fetchall=lambda: value,
                    fetchone=lambda: value,
                    rowcount=value if isinstance(value, int) else 0,
                )

        yield Connection()

    monkeypatch.setattr(module, "authenticated_database_connection", connect)
    return calls


def test_project_document_endpoints_require_login():
    app = FastAPI()
    app.include_router(projects.router)
    client = TestClient(app)
    path = f"/api/office/projects/{uuid4()}/documents"
    for response in (
        client.get(path),
        client.post(path, json={"document_ids": [str(uuid4())]}),
        client.delete(path + "/" + str(uuid4())),
    ):
        assert response.status_code == 401


def test_attach_is_owner_scoped_deduplicated_idempotent_and_audited(monkeypatch):
    owner, project, first, second = uuid4(), uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(projects, "office_project_case", lambda user, value: None)
    calls = fake_connection(
        monkeypatch,
        projects,
        lambda sql, args: [
            {"id": first, "needs_index": True},
            {"id": second, "needs_index": False},
        ]
        if sql.startswith("SELECT")
        else 1,
    )
    events = []
    scheduled = []
    monkeypatch.setattr(projects, "record_event", lambda *a, **kw: events.append(kw))
    monkeypatch.setattr(
        projects, "schedule_index", lambda *a, **kw: scheduled.append(a)
    )
    body = projects.LinkDocuments(document_ids=[first, second, first])
    result = projects.link_project_documents(
        project,
        body,
        owner,
        SimpleNamespace(headers={}, client=None, state=SimpleNamespace()),
    )
    assert result == {"linked": 1, "already_linked": 1}
    assert calls[0][0] == str(owner) and calls[0][2] == ([first, second],)
    insert = calls[1]
    assert (
        "ON CONFLICT(project_id,document_id) DO NOTHING" in insert[1]
        and "RETURNING" not in insert[1]
    )
    assert (
        insert[2][0:2] == (owner, project)
        and len(set(insert[2][2])) == 2
        and insert[2][3] == [first, second]
    )
    assert events[0]["actor_user_id"] == owner and events[0]["metadata"] == result
    assert scheduled == [(owner, first)]


def test_foreign_or_deleted_batch_member_rejects_whole_attach_before_writes(
    monkeypatch,
):
    monkeypatch.setattr(projects, "office_project_case", lambda *a: None)
    first = uuid4()
    calls = fake_connection(
        monkeypatch, projects, lambda *a: [{"id": first, "needs_index": False}]
    )
    with pytest.raises(HTTPException) as error:
        projects.link_project_documents(
            uuid4(),
            projects.LinkDocuments(document_ids=[first, uuid4()]),
            uuid4(),
            None,
        )
    assert error.value.status_code == 404 and len(calls) == 1


def test_unlink_only_removes_the_association_never_the_source_file(monkeypatch):
    monkeypatch.setattr(projects, "office_project_case", lambda *a: None)
    calls = fake_connection(monkeypatch, projects, lambda *a: 1)
    monkeypatch.setattr(projects, "record_event", lambda *a, **kw: None)
    assert (
        projects.unlink_project_document(
            uuid4(),
            uuid4(),
            uuid4(),
            SimpleNamespace(headers={}, client=None, state=SimpleNamespace()),
        ).status_code
        == 204
    )
    assert len(calls) == 1 and calls[0][1].startswith(
        "DELETE FROM office_project_documents WHERE project_id="
    )


def test_retrieval_uses_project_union_in_every_sql_path(monkeypatch):
    calls = []
    monkeypatch.setattr(
        retrieval,
        "_execute_retrieval",
        lambda conn, sql, args: calls.append((sql, args)) or [],
    )
    project = str(uuid4())
    for hybrid in (False, True):
        retrieval.retrieve_document_contexts(
            None,
            question="kira bedeli",
            office_project_id=project,
            top_k=5,
            query_embedding=[0.1] if hybrid else None,
            embedding_model="test",
        )
    for sql, args in calls:
        assert (
            "office_doc.case_id=p.case_id OR EXISTS" in sql
            and "office_project_documents" in sql
        )
        assert (
            "office_doc.deleted_at IS NULL" in sql
            and args["office_project_id"] == project
        )
        assert project not in sql


def test_same_owner_document_outside_project_cannot_be_used_as_selected_scope(
    monkeypatch,
):
    monkeypatch.setattr(workspace_scope, "office_project_case", lambda *a: None)
    fake_connection(monkeypatch, workspace_scope, lambda *a: [])
    with pytest.raises(HTTPException) as error:
        workspace_scope.require_project_documents(uuid4(), uuid4(), [uuid4()])
    assert error.value.status_code == 409


def test_project_analysis_rejects_out_of_scope_documents_before_job_creation(
    monkeypatch,
):
    def refused(*args):
        raise HTTPException(409, "Kapsam dışı")

    monkeypatch.setattr(jobs, "require_project_documents", refused)
    monkeypatch.setattr(
        jobs,
        "authenticated_database_connection",
        lambda *a: pytest.fail("Kapsam dışı iş yazıldı"),
    )
    with pytest.raises(HTTPException) as error:
        jobs._create(
            uuid4(),
            jobs.JobRequest(
                module="document_analysis", project_id=uuid4(), document_ids=[uuid4()]
            ),
            AuditContext(uuid4()),
        )
    assert error.value.status_code == 409


def test_new_schema_matches_upgrade_and_is_owner_rls_with_cascade_not_file_delete():
    root = Path(__file__).resolve().parents[1]
    fresh = (root / "database/init/055_office_project_documents.sql").read_text(
        encoding="utf-8"
    )
    upgrade = (root / "database/migrations/054_office_project_documents.sql").read_text(
        encoding="utf-8"
    )
    assert upgrade.removeprefix("\\set ON_ERROR_STOP on\n") == fresh
    assert (
        "FORCE ROW LEVEL SECURITY" in fresh
        and "owner_id=app_current_user_id()" in fresh
    )
    assert "SECURITY DEFINER" not in fresh and "owner_id=NEW.owner_id" in fresh
    assert (
        "DELETE FROM office_case_documents" not in fresh
        and "UNIQUE(project_id,document_id)" in fresh
    )


def test_project_scope_is_rechecked_before_saving_analysis_output(monkeypatch):
    document_id = uuid4()
    calls = []

    class Connection:
        def execute(self, sql, args):
            calls.append((sql, args))
            return SimpleNamespace(
                fetchone=lambda: {
                    "id": uuid4(),
                    "document_ids": [document_id],
                    "output_id": None,
                },
                fetchall=lambda: [],
            )

    @contextmanager
    def connection(owner):
        yield Connection()

    monkeypatch.setattr(jobs, "authenticated_database_connection", connection)
    monkeypatch.setattr(jobs, "record_event", lambda *a, **kw: None)
    payload = jobs.JobRequest(
        module="document_analysis", project_id=uuid4(), document_ids=[document_id]
    ).model_dump(mode="json")
    progress = {
        "total": 1,
        "done": 1,
        "documents": [
            {
                "id": str(document_id),
                "file_name": "Belge",
                "windows_done": 1,
                "windows_total": 1,
            }
        ],
    }
    jobs._finish(uuid4(), uuid4(), uuid4(), progress, "SOURCE_SECRET", "done", payload)
    assert any("office_project_documents" in sql for sql, args in calls)
    inserted = next(
        args for sql, args in calls if sql.startswith("INSERT INTO office_ai_outputs")
    )
    assert "SOURCE_SECRET" not in inserted[5] and inserted[6].obj == []
