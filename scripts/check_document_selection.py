"""Seçili belge SQL/RLS kabulü: yalnız sentetik, bu komutun oluşturduğu *_test DB.

Canlı tablo/veri kopyalanmaz. Secret/bağlantı URL'si yazdırılmaz. Küme rolleri
değiştirilmez; mevcut nhr_runtime rolünün RLS'yi atlayamadığı doğrulanır.
"""
from contextlib import contextmanager
from pathlib import Path
import re
import sys
from uuid import UUID, uuid4
from types import SimpleNamespace

import psycopg
from fastapi import HTTPException
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from api.ai import document_selection
from api.ai import workspace_scope
from api import project_documents, document_jobs
from api.audit import AuditContext
from api.ai.retrieval import retrieve_document_contexts
from api.config import get_settings


def main():
    admin_url = get_settings().admin_database_url
    if not admin_url:
        raise SystemExit('DATABASE_ADMIN_URL gerekli.')
    name = f'nhr_document_selection_{uuid4().hex[:8]}_test'
    pattern = r'nhr_document_selection_[a-f0-9]{8}_test'
    assert re.fullmatch(pattern, name)
    created = False
    with psycopg.connect(admin_url, autocommit=True) as admin:
        try:
            role = admin.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='nhr_runtime'").fetchone()
            assert role == (False, False), 'Runtime rolü RLS atlayamaz.'
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            created = True
            with psycopg.connect(make_conninfo(admin_url, dbname=name), autocommit=True, row_factory=dict_row) as connection:
                connection.execute("""
                    CREATE EXTENSION vector;
                    CREATE FUNCTION app_current_user_id() RETURNS UUID LANGUAGE SQL STABLE AS
                    $$ SELECT nullif(current_setting('app.user_id',true),'')::uuid $$;
                    CREATE TABLE users(id uuid PRIMARY KEY);
                    CREATE TABLE office_cases(id uuid PRIMARY KEY,owner_id uuid NOT NULL);
                    CREATE TABLE office_projects(id uuid PRIMARY KEY,owner_id uuid NOT NULL,case_id uuid);
                    CREATE TABLE office_case_documents (
                        id uuid PRIMARY KEY, owner_id uuid NOT NULL, case_id uuid, deleted_at timestamptz,
                        file_name text DEFAULT '',size_bytes bigint DEFAULT 30,source text DEFAULT 'manual',
                        doc_type text,doc_date date,created_at timestamptz DEFAULT clock_timestamp(),uyap_file_no text,uyap_birim text
                    );
                    CREATE TABLE documents (
                        id uuid PRIMARY KEY, owner_id uuid NOT NULL, project_id uuid,
                        office_case_document_id uuid UNIQUE REFERENCES office_case_documents(id),
                        file_name text NOT NULL, status text NOT NULL, deleted_at timestamptz,
                        metadata jsonb NOT NULL DEFAULT '{}', processing_error text, created_at timestamptz NOT NULL DEFAULT now()
                    );
                    CREATE TABLE document_chunks (
                        id uuid PRIMARY KEY, owner_id uuid NOT NULL, document_id uuid REFERENCES documents(id),
                        content text NOT NULL, search_vector tsvector GENERATED ALWAYS AS (to_tsvector('turkish', content)) STORED,
                        embedding vector(3), embedding_model text, section_title text, page_number integer, chunk_index integer DEFAULT 0
                    );
                    CREATE TABLE office_ai_outputs(id uuid PRIMARY KEY,owner_id uuid NOT NULL,module text,title text,prompt text,output text,
                        sources jsonb,case_id uuid,project_id uuid,created_at timestamptz DEFAULT clock_timestamp());
                """)
                for table in ('office_cases','office_projects','office_case_documents', 'documents', 'document_chunks','office_ai_outputs'):
                    identifier = sql.Identifier(table)
                    connection.execute(sql.SQL('ALTER TABLE {} ENABLE ROW LEVEL SECURITY').format(identifier))
                    connection.execute(sql.SQL('ALTER TABLE {} FORCE ROW LEVEL SECURITY').format(identifier))
                    connection.execute(sql.SQL('CREATE POLICY owner_only ON {} USING (owner_id=app_current_user_id()) WITH CHECK (owner_id=app_current_user_id())').format(identifier))
                    connection.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON {} TO nhr_runtime').format(identifier))
                alice, bob, case, other_case = [uuid4() for _ in range(4)]
                connection.execute('INSERT INTO users VALUES(%s),(%s)',(alice,bob))
                connection.execute('INSERT INTO office_cases VALUES(%s,%s),(%s,%s)',(case,alice,other_case,alice))
                project, inherited_project, foreign_project = uuid4(),uuid4(),uuid4()
                connection.execute('INSERT INTO office_projects VALUES(%s,%s,NULL),(%s,%s,%s),(%s,%s,NULL)',
                    (project,alice,inherited_project,alice,case,foreign_project,bob))
                migration=(ROOT/'database/init/055_office_project_documents.sql').read_text(encoding='utf-8')
                connection.execute(migration)
                connection.execute(migration)
                connection.execute((ROOT/'database/init/053_document_jobs.sql').read_text(encoding='utf-8'))

                def seed(owner, case_id, file_name, *, ready=True, trash=False, derived_trash=False, chunks=True):
                    office_id, document_id = uuid4(), uuid4()
                    connection.execute("INSERT INTO office_case_documents(id,owner_id,case_id,deleted_at,file_name) VALUES (%s,%s,%s,CASE WHEN %s THEN now() END,%s)", (office_id, owner, case_id, trash,file_name))
                    connection.execute("INSERT INTO documents(id,owner_id,office_case_document_id,file_name,status,metadata,deleted_at) VALUES (%s,%s,%s,%s,%s,'{\"ocr\":true}',CASE WHEN %s THEN now() END)",
                                       (document_id, owner, office_id, file_name, 'ready' if ready else 'pending', derived_trash))
                    if chunks:
                        connection.execute("INSERT INTO document_chunks(id,owner_id,document_id,content,embedding,embedding_model) VALUES (%s,%s,%s,%s,'[0.1,0.2,0.3]','synthetic')",
                                           (uuid4(), owner, document_id, 'Kiracı aylık 12.000 TL kira bedelini öder.'))
                    return office_id

                chosen = seed(alice, case, 'secilen.txt')
                seed(alice, case, 'secilmeyen.txt')
                foreign = seed(bob, case, 'diger-hesap.txt')
                another = seed(alice, other_case, 'diger-dava.txt')
                trashed = seed(alice, case, 'cop.txt', trash=True)
                pending = seed(alice, case, 'bekleyen.txt', ready=False)
                empty = seed(alice, case, 'parcasiz.txt', chunks=False)
                derived_trash = seed(alice, case, 'silinen-indeks.txt', derived_trash=True)
                connection.execute('SET ROLE nhr_runtime')

                @contextmanager
                def as_user(owner: str):
                    connection.execute("SELECT set_config('app.user_id',%s,false)", (str(UUID(owner)),))
                    yield connection

                previous = document_selection.authenticated_database_connection
                document_selection.authenticated_database_connection = as_user
                previous_workspace=workspace_scope.authenticated_database_connection
                workspace_scope.authenticated_database_connection=as_user
                previous_project=project_documents.authenticated_database_connection
                project_documents.authenticated_database_connection=as_user
                previous_audit=project_documents.record_event
                project_documents.record_event=lambda *args,**kwargs:None
                previous_jobs=document_jobs.authenticated_database_connection
                document_jobs.authenticated_database_connection=as_user
                previous_jobs_audit=document_jobs.record_event
                document_jobs.record_event=lambda *args,**kwargs:None
                try:
                    coverage = document_selection.selected_document_coverage(alice, [chosen], case)
                    assert coverage['ready'] == coverage['total'] == coverage['ocr'] == 1
                    for document_id, owner, scope, expected in (
                        (foreign, alice, None, 404), (chosen, bob, None, 404),
                        (another, alice, case, 404), (trashed, alice, None, 404),
                        (pending, alice, None, 409), (empty, alice, None, 409),
                        (derived_trash, alice, None, 409),
                    ):
                        try:
                            document_selection.selected_document_coverage(owner, [document_id], scope)
                        except HTTPException as error:
                            assert error.status_code == expected
                        else:
                            raise AssertionError('Erişilemeyen veya okunamayan seçim kabul edildi.')
                    for scope in (None, str(case)):
                        for question in ('kira bedeli', 'kiracı ödeme tutarı nedir?'):
                            for hybrid in (False, True):
                                with as_user(str(alice)):
                                    hits = retrieve_document_contexts(connection, question=question, document_ids=[str(chosen)],
                                        case_id=scope, top_k=5, query_embedding=[0.1,0.2,0.3] if hybrid else None,
                                        embedding_model='synthetic')
                                assert [hit.title for hit in hits] == ['secilen.txt']
                                assert all(hit.verification == 'user_document' for hit in hits)
                    with as_user(str(bob)):
                        assert retrieve_document_contexts(connection, question='kira bedeli', document_ids=[str(chosen)], top_k=5) == []
                    with as_user(str(alice)):
                        for doc in (trashed, derived_trash):
                            assert retrieve_document_contexts(connection, question='kira bedeli', document_ids=[str(doc)], top_k=5) == []
                    request=SimpleNamespace(headers={},client=None,state=SimpleNamespace())
                    attached=project_documents.link_project_documents(project,project_documents.LinkDocuments(document_ids=[chosen,another]),alice,request)
                    assert attached=={'linked':2,'already_linked':0}
                    job_id=document_jobs._create(alice,document_jobs.JobRequest(module='document_analysis',project_id=project,document_ids=[chosen]),AuditContext(uuid4()))
                    lease=uuid4()
                    assert document_jobs._claim(alice,job_id,lease)['state']=='running'
                    assert '12.000 TL' in document_jobs._document(alice,chosen)['text']
                    assert project_documents.link_project_documents(project,project_documents.LinkDocuments(document_ids=[chosen]),alice,request)['linked']==0
                    page=project_documents.list_project_documents(project,alice,limit=500,offset=0)
                    assert page['total']==page['ready']==2 and all(row['direct_linked'] for row in page['documents'])
                    for hybrid in (False,True):
                        with as_user(str(alice)):
                            hits=retrieve_document_contexts(connection,question='kira bedeli',office_project_id=str(project),top_k=20,
                                query_embedding=[0.1,0.2,0.3] if hybrid else None,embedding_model='synthetic')
                            assert {hit.title for hit in hits}=={'secilen.txt','diger-dava.txt'}
                        assert document_selection.selected_document_coverage(alice,[chosen],office_project_id=project)['ready']==1
                    for target,ids in ((foreign_project,[chosen]),(project,[foreign]),(project,[trashed])):
                        try: project_documents.link_project_documents(target,project_documents.LinkDocuments(document_ids=ids),alice,request)
                        except HTTPException as error: assert error.status_code==404
                        else: raise AssertionError('Yabancı/çöp proje bağlantısı kabul edildi.')
                    project_documents.link_project_documents(inherited_project,project_documents.LinkDocuments(document_ids=[chosen]),alice,request)
                    inherited=project_documents.list_project_documents(inherited_project,alice,limit=500,offset=0)
                    assert len({row['id'] for row in inherited['documents']})==inherited['total']
                    project_documents.unlink_project_document(inherited_project,chosen,alice,request)
                    assert chosen in {row['id'] for row in project_documents.list_project_documents(inherited_project,alice,limit=500,offset=0)['documents']}
                    project_documents.unlink_project_document(project,chosen,alice,request)
                    try: workspace_scope.require_project_documents(alice,project,[chosen])
                    except HTTPException as error: assert error.status_code==409
                    else: raise AssertionError('Bağlantısı kaldırılan belge kapsamda kaldı.')
                    payload=document_jobs.JobRequest(module='document_analysis',project_id=project,document_ids=[chosen]).model_dump(mode='json')
                    progress={'total':1,'done':1,'documents':[{'id':str(chosen),'file_name':'secilen.txt','windows_done':1,'windows_total':1}]}
                    assert document_jobs._finish(alice,job_id,lease,progress,'SHOULD_NOT_BE_SAVED','done',payload)
                    with as_user(str(alice)):
                        output=connection.execute('SELECT output,sources,project_id FROM office_ai_outputs').fetchone()
                        assert 'SHOULD_NOT_BE_SAVED' not in output['output'] and output['sources']==[] and output['project_id']==project
                    with as_user(str(alice)):
                        assert connection.execute('SELECT id FROM office_case_documents WHERE id=%s AND deleted_at IS NULL',(chosen,)).fetchone()
                    print('Proje belgeleri kabulü geçti: doğrudan/bağlı dava birleşimi, çift kaydın önlenmesi, lexical/hybrid, yabancı/çöp reddi, yalnız bağlantıyı kaldırma ve kaynak dosyanın korunması.')
                    print('Sentetik PostgreSQL kabulü geçti: lexical/hybrid/broad seçim, dava kesişimi, owner RLS, OCR ve hazır/çöp kontrolleri.')
                finally:
                    document_selection.authenticated_database_connection = previous
                    workspace_scope.authenticated_database_connection=previous_workspace
                    project_documents.authenticated_database_connection=previous_project
                    project_documents.record_event=previous_audit
                    document_jobs.authenticated_database_connection=previous_jobs
                    document_jobs.record_event=previous_jobs_audit
        finally:
            if created:
                assert re.fullmatch(pattern, name)
                admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
                print('Yalnız bu testin oluşturduğu sentetik test veritabanı kaldırıldı; canlı veriler değiştirilmedi.')


if __name__ == '__main__':
    main()
