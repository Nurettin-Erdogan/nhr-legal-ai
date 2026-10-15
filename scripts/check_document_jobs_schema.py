"""Yeni kuyruk şemasını yalnız bu komutun oluşturduğu, boş *_test DB'sinde sınar.

Canlı veriden kopya alınmaz. Geçici DB adı sabit önek + rastgele kimliktir;
sonunda yalnız bu komutun oluşturduğu DB kaldırılır. URL/secret yazdırılmaz.
"""
from pathlib import Path
import re
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from api.config import get_settings


def main():
    admin_url=get_settings().admin_database_url
    if not admin_url: raise SystemExit('DATABASE_ADMIN_URL gerekli.')
    name=f'nhr_document_jobs_{uuid4().hex[:8]}_test'
    assert re.fullmatch(r'nhr_document_jobs_[a-f0-9]{8}_test',name)
    created=False
    alice,bob,doc,job,output,other_job=[uuid4() for _ in range(6)]
    with psycopg.connect(admin_url,autocommit=True) as admin:
        try:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            created=True
            with psycopg.connect(make_conninfo(admin_url,dbname=name),autocommit=True) as connection:
                connection.execute("""
                  CREATE TABLE users(id UUID PRIMARY KEY);
                  CREATE TABLE office_case_documents(id UUID PRIMARY KEY,owner_id UUID REFERENCES users(id));
                  CREATE TABLE office_ai_outputs(id UUID PRIMARY KEY,owner_id UUID REFERENCES users(id));
                  CREATE FUNCTION app_current_user_id() RETURNS UUID LANGUAGE SQL STABLE AS
                    $$ SELECT nullif(current_setting('app.user_id',true),'')::uuid $$;
                  GRANT SELECT,INSERT,UPDATE,DELETE ON users,office_case_documents,office_ai_outputs TO nhr_runtime;
                """)
                migration=(ROOT/'database/migrations/052_document_jobs.sql').read_text(encoding='utf-8')
                connection.execute('\n'.join(line for line in migration.splitlines() if not line.startswith('\\')))
                role=connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='nhr_runtime'").fetchone()
                assert role==(False,False),'Runtime rolü RLS bypass edemez.'
                connection.execute('INSERT INTO users VALUES (%s),(%s)',(alice,bob))
                connection.execute('INSERT INTO office_case_documents VALUES (%s,%s)',(doc,alice))
                connection.execute('SET ROLE nhr_runtime')
                connection.execute("SELECT set_config('app.user_id',%s,false)",(str(alice),))
                connection.execute("INSERT INTO office_document_jobs(id,owner_id,module,document_ids,payload) VALUES(%s,%s,'auto_summary',%s,'{}')",(job,alice,[doc]))
                connection.execute("SELECT set_config('app.user_id',%s,false)",(str(bob),))
                assert connection.execute('SELECT count(*) FROM office_document_jobs').fetchone()[0]==0
                assert connection.execute('DELETE FROM office_document_jobs WHERE id=%s',(job,)).rowcount==0
                try:
                    connection.execute("INSERT INTO office_document_jobs(id,owner_id,module,payload) VALUES(%s,%s,'auto_summary','{}')",(uuid4(),alice))
                except psycopg.errors.InsufficientPrivilege: pass
                else: raise AssertionError('Başka kullanıcı adına iş oluşturuldu.')
                connection.execute("INSERT INTO office_document_jobs(id,owner_id,module,payload) VALUES(%s,%s,'auto_summary','{}')",(other_job,bob))
                connection.execute("SELECT set_config('app.user_id',%s,false)",(str(alice),))
                try:
                    connection.execute("INSERT INTO office_document_jobs(id,owner_id,module,payload) VALUES(%s,%s,'auto_summary','{}')",(uuid4(),alice))
                except psycopg.errors.UniqueViolation: pass
                else: raise AssertionError('Aynı hesapta ikinci aktif iş açıldı.')
                connection.execute('INSERT INTO office_ai_outputs VALUES(%s,%s)',(output,alice))
                connection.execute("UPDATE office_document_jobs SET state='done',output_id=%s WHERE id=%s",(output,job))
                connection.execute('DELETE FROM office_case_documents WHERE id=%s',(doc,))
                assert connection.execute('SELECT count(*) FROM office_document_jobs').fetchone()[0]==0
                assert connection.execute('SELECT count(*) FROM office_ai_outputs').fetchone()[0]==0
                connection.execute('INSERT INTO office_ai_outputs VALUES(%s,%s)',(output,alice))
                connection.execute("INSERT INTO office_document_jobs(id,owner_id,module,state,payload,output_id) VALUES(%s,%s,'auto_summary','done','{}',%s)",(job,alice,output))
                connection.execute('DELETE FROM office_ai_outputs WHERE id=%s',(output,))
                assert connection.execute('SELECT count(*) FROM office_document_jobs').fetchone()[0]==0
                connection.execute("SELECT set_config('app.user_id',%s,false)",(str(bob),))
                assert connection.execute('SELECT id FROM office_document_jobs').fetchone()[0]==other_job
                print('Ayrı test DB: owner RLS, sahte owner reddi, tek aktif iş, kaynak/çıktı silme ve diğer hesabın korunması geçti.')
        finally:
            if created:
                assert re.fullmatch(r'nhr_document_jobs_[a-f0-9]{8}_test',name)
                admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
                print('Yalnız bu testin oluşturduğu geçici, sentetik test veritabanı kaldırıldı.')


if __name__=='__main__':main()
