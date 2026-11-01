"""Authenticated manual upload contract; bounded multipart, no client identity trust."""
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api import office, office_public
from api.auth.routes import current_user_id


@pytest.fixture
def client(monkeypatch):
    owner, document = uuid4(), uuid4()
    calls, scheduled = [], []
    def store(user, **kwargs):
        calls.append((user, kwargs))
        return 'inserted', document
    monkeypatch.setattr(office_public, '_store', store)
    monkeypatch.setattr(office_public, '_schedule_index', lambda *args: scheduled.append(args))
    app = FastAPI()
    app.include_router(office.router)
    app.dependency_overrides[current_user_id] = lambda: owner
    yield TestClient(app), owner, document, calls, scheduled, app


def test_manual_import_requires_session_before_reading_body(client):
    browser, _, _, calls, _, app = client
    app.dependency_overrides.clear()
    assert browser.post('/api/office/uyap/import', files={'file': ('x.odt', b'x')}).status_code == 401
    assert not calls


def test_manual_import_owner_hash_and_identity_are_not_client_controlled(client):
    browser, owner, document, calls, scheduled, _ = client
    run = uuid4()
    response = browser.post('/api/office/uyap/import', files={'file': ('evrak.odt', b'odt bytes')},
        data={'path': '2024/99/evrak.odt', 'syncRunId': str(run), 'owner_id': str(uuid4()),
              'checksum_sha256': 'forged', 'evrakId': 'forged', 'source': 'forged', 'dosyaEsasNo': '2024/55'})
    assert response.json() == {'ok': True, 'duplicate': False, 'id': str(document)}
    user, options = calls[0]
    assert user == owner and options['source'] == 'uyap' and options['sync_run_id'] == run
    assert options['overrides'] == {'metadata_name': '2024/99/evrak.odt', 'uyap_path': '2024/99/evrak.odt'}
    assert 'checksum_sha256' not in options and scheduled


def test_manual_duplicate_is_success_without_indexing_again(client, monkeypatch):
    browser, _, document, _, scheduled, _ = client
    monkeypatch.setattr(office_public, '_store', lambda *args, **kwargs: ('duplicate', document))
    response = browser.post('/api/office/uyap/import', files={'file': ('evrak.txt', b'bytes')})
    assert response.status_code == 200 and response.json()['duplicate'] and not scheduled


@pytest.mark.parametrize('name,data,status', [('x.exe', b'MZ', 415), ('x.txt', b'', 400)])
def test_manual_invalid_files_are_not_stored(client, name, data, status):
    browser, _, _, calls, _, _ = client
    assert browser.post('/api/office/uyap/import', files={'file': (name, data)}).status_code == status
    assert not calls


def test_manual_size_is_bounded_without_a_content_length(client, monkeypatch):
    browser, _, _, calls, _, _ = client
    monkeypatch.setenv('MAX_UPLOAD_BYTES', '4')  # işletmecinin isteğe bağlı üst sınırı
    monkeypatch.setattr(office_public, 'MULTIPART_OVERHEAD_BYTES', 1)
    response = browser.post('/api/office/uyap/import', content=iter([b'x' * 20]), headers={'content-type': 'multipart/form-data; boundary=a'})
    assert response.status_code == 413 and not calls


def test_manual_invalid_sync_and_storage_errors_are_never_success(client, monkeypatch):
    browser, _, _, calls, _, _ = client
    assert browser.post('/api/office/uyap/import', files={'file': ('evrak.txt', b'bytes')}, data={'syncRunId': 'bad'}).status_code == 400
    assert not calls
    monkeypatch.setattr(office_public, '_store', lambda *args, **kwargs: ('invalid_sync', None))
    assert browser.post('/api/office/uyap/import', files={'file': ('evrak.txt', b'bytes')}).status_code == 404


def test_generic_insert_cannot_bypass_uyap_atomic_upload(client):
    browser, _, _, calls, _, _ = client
    # The generic path rejects UYAP provenance before preparing or inserting a row.
    from contextlib import contextmanager
    class NoWrite:
        def execute(self, *args):
            raise AssertionError('No DB write should run')
    @contextmanager
    def connection(_):
        yield NoWrite()
    from unittest.mock import patch
    with patch.object(office, 'authenticated_database_connection', connection), patch.object(office, '_columns', return_value={'id': 'uuid', 'owner_id': 'uuid'}):
        response = browser.post('/api/office/case_documents', json={'op': 'insert', 'values': {'source': 'uyap', 'file_name': 'evrak.txt'}})
    assert response.status_code == 409 and not calls


@pytest.mark.parametrize('name,expected', [('odeme_31.02.2025.pdf', None), ('odeme_29.02.2024.pdf', '2024-02-29'), ('odeme_2025-10-05.pdf', '2025-10-05')])
def test_server_metadata_dates_are_valid(name, expected):
    from api.uyap_meta import parse_uyap_meta
    assert parse_uyap_meta(name)['doc_date'] == expected
