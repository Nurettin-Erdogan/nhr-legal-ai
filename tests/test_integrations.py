import asyncio
from uuid import uuid4
from xml.etree import ElementTree
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from api import integrations, office_public
from api.auth.routes import current_user_id
from api.upload_stream import Upload


@pytest.mark.parametrize('origin',['http://example.com','https://example.com/path','https://user:secret@example.com','https://example.com?x=1','javascript:evil'])
def test_word_rejects_unsafe_origins(monkeypatch,origin):
    monkeypatch.setenv('WORD_ADDIN_ORIGIN',origin)
    assert integrations.word_origin()==''


def test_word_manifest_has_explicit_document_permission_and_https_taskpane():
    text=integrations.word_manifest('https://legal.example.com')
    ElementTree.fromstring(text)
    assert '/word/taskpane.html' in text and 'ReadWriteDocument' in text
    assert 'https://legal.example.com/jurisai-avukat/images/icon-48.png' in text
    assert 'password' not in text


def test_unconfigured_integrations_do_not_claim_to_be_connected(monkeypatch):
    for name in ('GOOGLE_CLIENT_ID','GOOGLE_DRIVE_CLIENT_ID','GOOGLE_PICKER_API_KEY','GOOGLE_CLOUD_PROJECT_NUMBER','WORD_ADDIN_ORIGIN'):
        monkeypatch.delenv(name,raising=False)
    config=integrations.integration_config()
    assert config['drive']['configured'] is False and config['word']['configured'] is False
    app=FastAPI();app.include_router(integrations.router)
    assert TestClient(app).get('/api/integrations/word/manifest').status_code==503


def test_drive_requires_login_before_reading_upload(monkeypatch):
    async def fail(*args): raise AssertionError('Unauthenticated body read')
    monkeypatch.setattr(office_public,'read_document_upload',fail)
    app=FastAPI();app.include_router(integrations.router)
    assert TestClient(app).post('/api/integrations/drive/import').status_code==401


def test_drive_import_is_scoped_to_authenticated_owner_and_uses_existing_parser(monkeypatch):
    owner=uuid4();document_id=uuid4();seen=[]
    async def read(request):return {},'belge.docx','application/octet-stream',Upload.from_bytes(b'test')
    def store(user,**kwargs):seen.append((user,kwargs));kwargs['data'].discard();return 'inserted',document_id
    monkeypatch.setattr(office_public,'read_document_upload',read);monkeypatch.setattr(office_public,'_store',store)
    app=FastAPI();app.include_router(integrations.router);app.dependency_overrides[current_user_id]=lambda:owner
    response=TestClient(app).post('/api/integrations/drive/import')
    assert response.json()=={'id':str(document_id),'duplicate':False}
    assert seen[0][0]==owner and seen[0][1]['source']=='google_drive'
    assert 'token' not in seen[0][1]


def test_drive_oversized_upload_is_discarded_not_saved(monkeypatch):
    upload=Upload(size=51*1024*1024,sha256='x')
    async def read(request):return {},'big.pdf','application/pdf',upload
    monkeypatch.setattr(office_public,'read_document_upload',read)
    app=FastAPI();app.include_router(integrations.router);app.dependency_overrides[current_user_id]=lambda:uuid4()
    assert TestClient(app).post('/api/integrations/drive/import').status_code==413
    assert upload._closed
