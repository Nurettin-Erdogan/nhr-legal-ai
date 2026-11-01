"""Dava/büro projesi/seçili belge sohbetinin kapsamı kalıcı ve değiştirilemez."""
import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.ai import history, pipeline, workspace_scope
from api.ai.conversation_history import ConversationContext
from api.ai.verification import VerifiedAnswer
from api.schemas import AIAnswerRequest


def connect(monkeypatch, module, row):
    seen = []
    @contextmanager
    def connection(owner):
        def execute(sql, args):
            seen.append((owner, sql, args))
            return SimpleNamespace(fetchone=lambda: row)
        yield SimpleNamespace(execute=execute)
    monkeypatch.setattr(module, 'authenticated_database_connection', connection)
    return seen


@pytest.mark.parametrize('other', ['case_id', 'project_id'])
def test_office_project_is_not_confused_with_other_scopes(other):
    with pytest.raises(ValidationError):
        AIAnswerRequest(question='Kaynaklarda ne yazıyor?', office_project_id=uuid4(), **{other: uuid4()})


def test_office_project_access_is_owner_scoped_and_can_be_unlinked(monkeypatch):
    project, owner, case = uuid4(), uuid4(), uuid4()
    seen = connect(monkeypatch, workspace_scope, {'case_id': case})
    assert workspace_scope.office_project_case(owner, project) == case
    assert seen[0][0] == str(owner) and seen[0][2] == (project,)
    assert 'c.id IS NOT NULL' in seen[0][1]  # görünmeyen bağlı dava da reddedilir
    connect(monkeypatch, workspace_scope, {'case_id': None})
    assert workspace_scope.office_project_case(owner, project) is None
    connect(monkeypatch, workspace_scope, None)
    for user, status in ((None, 401), (owner, 404)):
        with pytest.raises(HTTPException) as error:
            workspace_scope.office_project_case(user, project)
        assert error.value.status_code == status


@pytest.mark.parametrize('field', ['case_id', 'office_project_id', 'selected_document_ids'])
def test_history_cannot_continue_in_another_or_missing_scope(monkeypatch, field):
    stored = {field: (uuid4(),) if field == 'selected_document_ids' else uuid4()}
    context = ConversationContext(None, (), **stored)
    connect(monkeypatch, pipeline, {})
    monkeypatch.setattr(pipeline, 'load_conversation_context', lambda *args: context)
    for changed in ({}, {field: [uuid4()] if field == 'selected_document_ids' else uuid4()}):
        with pytest.raises(HTTPException) as error:
            asyncio.run(pipeline._load_history(AIAnswerRequest(question='Devamında ne yazıyor?', conversation_id=uuid4(), **changed), uuid4()))
        assert error.value.status_code == 409
    correct = {field: list(stored[field]) if field == 'selected_document_ids' else stored[field]}
    assert asyncio.run(pipeline._load_history(AIAnswerRequest(question='Devamında ne yazıyor?', conversation_id=uuid4(), **correct), uuid4())) == ((), ())


def test_pipeline_resolves_office_project_to_its_case_without_core_project_query(monkeypatch):
    project, case, owner = uuid4(), uuid4(), uuid4()
    seen = {}
    connect(monkeypatch, pipeline, {})
    monkeypatch.setattr(pipeline, 'office_project_case', lambda user, value: case if (user, value) == (owner, project) else None)
    monkeypatch.setattr(pipeline, 'sweep_unindexed', lambda user, **kw: seen.update(sweep=kw))
    monkeypatch.setattr(pipeline, 'case_document_coverage', lambda *a: {'total': 0, 'ready': 0})
    monkeypatch.setattr(pipeline, 'project_document_coverage', lambda *a: {'total': 0, 'ready': 0})
    monkeypatch.setattr(pipeline, 'record_contexts', lambda *a, **kw: [])
    monkeypatch.setattr(pipeline, 'retrieve_document_contexts', lambda *a, **kw: seen.update(documents=kw) or [])
    monkeypatch.setattr(pipeline, 'retrieve_contexts', lambda *a, **kw: pytest.fail('Olgu sorusu korpusa genişletildi'))
    pipeline._retrieve(AIAnswerRequest(question='Bu dosyada borçlu kim?', office_project_id=project), user_id=owner,
                       query_embedding=None, top_k=5, embedding_model='test')
    assert seen['sweep']['case_id'] == case
    assert seen['documents']['case_id'] is None and seen['documents']['project_id'] is None
    assert seen['documents']['office_project_id'] == str(project)


def test_new_exchange_persists_complete_scope_and_generates_ids_in_application():
    calls = []
    class Connection:
        def execute(self, sql, args): calls.append((sql, args))
    case, doc = uuid4(), uuid4()
    result = history.record_exchange(Connection(), user_id=uuid4(), conversation_id=None, project_id=None,
        question='Ödeme tutarı nedir?', answer=VerifiedAnswer(text='Kaynak yetersiz.', contexts=(), unverified_markers=(), unsupported_claims=()),
        model_name='synthetic', case_id=case, selected_document_ids=[doc], document_scope={'total':1,'ready':1,'ocr':1})
    assert calls[0][1][-3:] == (case, None, [doc])
    assert 'RETURNING' not in calls[0][0] and calls[0][1][0] == result[0]
    assert 'INSERT INTO messages (id,' in calls[1][0]
    assert calls[2][1][-1].obj['document_scope']['ocr'] == 1


def test_unlinked_office_project_never_answers_its_facts_from_other_cases(monkeypatch):
    connect(monkeypatch, pipeline, {})
    monkeypatch.setattr(pipeline, 'office_project_case', lambda *args: None)
    monkeypatch.setattr(pipeline, 'project_document_coverage', lambda *args: {'total':0,'ready':0})
    monkeypatch.setattr(pipeline, 'retrieve_document_contexts', lambda *args,**kw: [])
    monkeypatch.setattr(pipeline, 'retrieve_contexts', lambda *args,**kw: pytest.fail('Başka dosyalardaki olgulara bakıldı'))
    monkeypatch.setattr(pipeline, 'database_connection', lambda: pytest.fail('Başka dosyalardaki olgulara bakıldı'))
    info={}
    assert pipeline._retrieve(AIAnswerRequest(question='Ödeme tutarı nedir?',office_project_id=uuid4()),
        user_id=uuid4(),query_embedding=None,top_k=5,embedding_model='test',diagnostics=info)==[]
    assert info['document_scope']['total']==0 and info['document_scope']['file_only']


def test_write_rechecks_scope_under_lock_before_any_messages():
    class Connection:
        def execute(self, sql, args):
            assert 'FOR UPDATE' in sql
            return SimpleNamespace(fetchone=lambda: {'project_id': None, 'case_id': uuid4(), 'office_project_id': None, 'selected_document_ids': []})
    with pytest.raises(history.ConversationScopeMismatch):
        history.record_exchange(Connection(), user_id=uuid4(), conversation_id=uuid4(), project_id=None,
            question='Ödeme tutarı nedir?', answer=VerifiedAnswer(text='Cevap', contexts=(), unverified_markers=(), unsupported_claims=()), model_name='synthetic')


def test_scope_migration_matches_fresh_install_and_never_backfills_or_broadens_rls():
    root = Path(__file__).resolve().parents[1]
    fresh = (root/'database/init/054_conversation_workspace_scope.sql').read_text(encoding='utf-8')
    migration = (root/'database/migrations/053_conversation_workspace_scope.sql').read_text(encoding='utf-8')
    assert migration.removeprefix('\\set ON_ERROR_STOP on\n') == fresh
    assert 'SECURITY DEFINER' not in fresh and 'CREATE POLICY' not in fresh
    assert 'owner_id=NEW.created_by' in fresh and "TG_OP='UPDATE'" in fresh
    assert 'UPDATE conversations SET' not in fresh
