"""Parallel real HTTP handlers + runtime PostgreSQL in an isolated *_test database.

Committed synthetic fixtures are needed for independent connections; only their
generated owner is removed in finally. Never point this test at production.
"""
import contextlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from api import office, office_public
from api.auth.routes import current_user_id

pytestmark = pytest.mark.skipif(not os.getenv('NHR_TEST_DATABASE_URL'), reason='Isolated test DB not configured')


@pytest.fixture
def concurrent_world(monkeypatch, tmp_path):
    dsn = os.environ['NHR_TEST_DATABASE_URL']
    assert conninfo_to_dict(dsn)['dbname'].endswith('_test'), 'Concurrency fixtures require an isolated *_test DB'
    owner = uuid4()
    with psycopg.connect(dsn) as setup:
        setup.execute("INSERT INTO users (id,email,password_hash,full_name) VALUES (%s,%s,'test','Concurrency test')", (owner, f'{owner}@test.invalid'))

    @contextlib.contextmanager
    def as_user(user):
        assert str(user) == str(owner)
        with psycopg.connect(dsn, row_factory=dict_row) as connection:
            connection.execute("SET statement_timeout='8s'")
            connection.execute('SET LOCAL ROLE nhr_runtime')
            connection.execute("SELECT set_config('app.user_id', %s, true)", (str(owner),))
            yield connection

    def path(user, key):
        assert str(user) == str(owner)
        target = (tmp_path / key).resolve()
        assert target.is_relative_to(tmp_path.resolve())
        return target

    monkeypatch.setattr(office, 'authenticated_database_connection', as_user)
    monkeypatch.setattr(office_public, 'authenticated_database_connection', as_user)
    monkeypatch.setattr(office_public, '_storage_path', path)
    monkeypatch.setattr(office_public, '_schedule_index', lambda *args: None)
    monkeypatch.setattr(office_public, '_owner_for_token', lambda token: (uuid4(), owner) if token == 'synthetic-token-for-tests-only' else None)
    app = FastAPI()
    app.include_router(office.router)
    app.include_router(office_public.router)
    app.dependency_overrides[current_user_id] = lambda: owner
    try:
        with TestClient(app) as client:
            yield client, owner, as_user, tmp_path
    finally:
        with psycopg.connect(dsn) as cleanup:
            for table, column in [('activity_logs', 'actor_user_id'), ('office_case_documents', 'owner_id'),
                                  ('office_cases', 'owner_id'), ('office_uyap_sync_runs', 'owner_id')]:
                cleanup.execute(f'DELETE FROM {table} WHERE {column}=%s', (owner,))
            cleanup.execute('DELETE FROM users WHERE id=%s', (owner,))
        with psycopg.connect(dsn) as verify:
            assert verify.execute('SELECT count(*) FROM users WHERE id=%s', (owner,)).fetchone()[0] == 0


def parallel(*functions):
    gate = threading.Barrier(len(functions))
    def run(fn):
        gate.wait(timeout=5)
        return fn()
    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        tasks = [pool.submit(run, fn) for fn in functions]
        return [task.result(timeout=20) for task in tasks]


def test_parallel_manual_http_imports_create_one_hashed_document(concurrent_world):
    client, owner, as_user, tmp_path = concurrent_world
    def upload():
        return client.post('/api/office/uyap/import', files={'file': ('evrak.txt', b'Identical synthetic bytes.')},
                           data={'path': '2024/99/evrak.txt'})
    responses = parallel(upload, upload)
    assert [r.status_code for r in responses] == [200, 200]
    assert sorted(r.json()['duplicate'] for r in responses) == [False, True]
    assert len({r.json()['id'] for r in responses}) == 1
    with as_user(owner) as connection:
        rows = connection.execute('SELECT storage_path,checksum_sha256 FROM office_case_documents').fetchall()
        assert len(rows) == 1 and rows[0]['checksum_sha256']
    assert len(list(tmp_path.rglob('*.txt'))) == 1


def test_parallel_extension_retries_and_renames_do_not_duplicate(concurrent_world):
    client, owner, as_user, _ = concurrent_world
    def upload(name, number):
        return client.post('/api/public/v1/documents/upload',
            headers={'Authorization': 'Bearer synthetic-token-for-tests-only'}, files={'file': (name, b'Identical bytes.')},
            data={'evrakId': 'stable-id', 'dosyaEsasNo': number, 'birim': 'Synthetic Court'})
    responses = parallel(lambda: upload('ilk.txt', '2024/77'), lambda: upload('yeni.txt', '2024 / 77'))
    assert [r.status_code for r in responses] == [200, 200]
    assert len({r.json()['id'] for r in responses}) == 1
    with as_user(owner) as connection:
        assert connection.execute('SELECT count(*) AS n FROM office_case_documents').fetchone()['n'] == 1
        assert connection.execute('SELECT count(*) AS n FROM office_cases').fetchone()['n'] == 1


def test_parallel_cursor_batches_in_opposite_case_order_never_deadlock(concurrent_world):
    client, owner, as_user, _ = concurrent_world
    base = uuid4().int & ~255
    docs = [UUID(int=base + i) for i in range(1, 5)]
    with as_user(owner) as connection:
        for doc, number in zip(docs, ['2024/111', '2024/222', '2024/222', '2024/111']):
            connection.execute("INSERT INTO office_case_documents (id,owner_id,file_name,storage_path,source,uyap_file_no,uyap_birim) VALUES (%s,%s,'synthetic.txt',%s,'uyap',%s,'Synthetic Court')", (doc, owner, f'{owner}/{doc}.txt', number))
    responses = parallel(lambda: client.post('/api/office/uyap/link-cases'),
                         lambda: client.post(f'/api/office/uyap/link-cases?after={docs[0]}'))
    assert [r.status_code for r in responses] == [200, 200]
    with as_user(owner) as connection:
        assert connection.execute('SELECT count(*) AS n FROM office_cases').fetchone()['n'] == 2
        assert connection.execute('SELECT count(*) AS n FROM office_case_documents WHERE case_id IS NOT NULL').fetchone()['n'] == 4


def test_parallel_linking_and_extension_retry_share_the_outer_lock(concurrent_world):
    client, owner, as_user, _ = concurrent_world
    def upload():
        return client.post('/api/public/v1/documents/upload', headers={'Authorization': 'Bearer synthetic-token-for-tests-only'},
            files={'file': ('evrak.txt', b'Identical bytes.')}, data={'evrakId': 'stable-id', 'dosyaEsasNo': '2024/77', 'birim': 'Synthetic Court'})
    first = upload()
    assert first.status_code == 200
    with as_user(owner) as connection:
        connection.execute('UPDATE office_case_documents SET case_id=NULL')
    responses = parallel(upload, lambda: client.post('/api/office/uyap/link-cases'))
    assert [r.status_code for r in responses] == [200, 200]
    with as_user(owner) as connection:
        assert connection.execute('SELECT count(*) AS n FROM office_case_documents WHERE case_id IS NOT NULL').fetchone()['n'] == 1
        assert connection.execute('SELECT count(*) AS n FROM office_cases').fetchone()['n'] == 1
