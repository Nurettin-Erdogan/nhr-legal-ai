"""Yeni sohbet kapsamı migrationını sentetik *_test DB'de, gerçek RLS ile sınar.

Canlı veri kopyalanmaz. Yalnız bu komutun oluşturduğu veritabanı kaldırılır.
Temel conversation RLS fonksiyonları mevcut init dosyasından aynen alınır.
"""

from contextlib import contextmanager
from pathlib import Path
import re
import sys
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.ai.conversation_history import load_conversation_context
from api.ai.history import ConversationScopeMismatch, record_exchange
from api.ai.verification import VerifiedAnswer
from api.config import get_settings
from api import conversations

ROOT = Path(__file__).resolve().parents[1]


def main():
    admin_url = get_settings().admin_database_url
    if not admin_url:
        raise SystemExit("DATABASE_ADMIN_URL gerekli.")
    name = f"nhr_conversation_scope_{uuid4().hex[:8]}_test"
    pattern = r"nhr_conversation_scope_[a-f0-9]{8}_test"
    created = False
    with psycopg.connect(admin_url, autocommit=True) as admin:
        try:
            assert admin.execute(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='nhr_runtime'"
            ).fetchone() == (False, False)
            assert re.fullmatch(pattern, name)
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            created = True
            with psycopg.connect(
                make_conninfo(admin_url, dbname=name),
                autocommit=True,
                row_factory=dict_row,
            ) as connection:
                connection.execute("""
                  CREATE FUNCTION app_current_user_id() RETURNS uuid LANGUAGE SQL STABLE AS
                  $$ SELECT nullif(current_setting('app.user_id',true),'')::uuid $$;
                  CREATE FUNCTION app_can_access_project(uuid) RETURNS boolean LANGUAGE SQL STABLE AS $$ SELECT false $$;
                  CREATE FUNCTION app_can_edit_project(uuid) RETURNS boolean LANGUAGE SQL STABLE AS $$ SELECT false $$;
                  CREATE TABLE users(id uuid PRIMARY KEY);
                  CREATE TABLE office_cases(id uuid PRIMARY KEY,owner_id uuid NOT NULL);
                  CREATE TABLE office_projects(id uuid PRIMARY KEY,owner_id uuid NOT NULL,case_id uuid REFERENCES office_cases ON DELETE SET NULL);
                  CREATE TABLE office_case_documents(id uuid PRIMARY KEY,owner_id uuid NOT NULL,case_id uuid,deleted_at timestamptz);
                  CREATE TABLE conversations(id uuid PRIMARY KEY,project_id uuid,created_by uuid NOT NULL,title text,
                    created_at timestamptz DEFAULT clock_timestamp(),updated_at timestamptz DEFAULT clock_timestamp(),deleted_at timestamptz,deleted_by uuid);
                  CREATE TABLE messages(id uuid PRIMARY KEY,conversation_id uuid REFERENCES conversations ON DELETE CASCADE,
                    role text,content text,model_name text,metadata jsonb DEFAULT '{}',created_at timestamptz DEFAULT clock_timestamp(),deleted_at timestamptz);
                  CREATE TABLE legal_sources(id uuid PRIMARY KEY,ingestion_method text,ingest_status text);
                  CREATE TABLE legal_chunks(id uuid PRIMARY KEY,legal_source_id uuid);
                  CREATE TABLE citations(id uuid PRIMARY KEY,message_id uuid REFERENCES messages ON DELETE CASCADE,citation_order integer,
                    marker text,source_title text,source_locator jsonb,snippet text,document_chunk_id uuid,legal_chunk_id uuid,relevance_score real);
                """)
                base = (ROOT / "database/init/004_rls.sql").read_text(encoding="utf-8")
                for function in (
                    "app_can_access_conversation",
                    "app_can_edit_conversation",
                ):
                    body = re.search(
                        r"CREATE OR REPLACE FUNCTION " + function + r"\(.*?\n\$\$;",
                        base,
                        re.S,
                    )
                    assert body
                    connection.execute(body.group(0))
                for table, predicate in (
                    ("office_cases", "owner_id=app_current_user_id()"),
                    ("office_projects", "owner_id=app_current_user_id()"),
                    ("office_case_documents", "owner_id=app_current_user_id()"),
                    ("conversations", "app_can_access_conversation(id)"),
                    ("messages", "app_can_access_conversation(conversation_id)"),
                    (
                        "citations",
                        "EXISTS (SELECT 1 FROM messages WHERE messages.id=message_id)",
                    ),
                ):
                    identifier = sql.Identifier(table)
                    connection.execute(
                        sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(
                            identifier
                        )
                    )
                    if table.startswith("office_"):
                        connection.execute(
                            sql.SQL("ALTER TABLE {} FORCE ROW LEVEL SECURITY").format(
                                identifier
                            )
                        )
                    connection.execute(
                        sql.SQL(
                            "CREATE POLICY visible_rows ON {} FOR SELECT USING ("
                            + predicate
                            + ")"
                        ).format(identifier)
                    )
                    check = (
                        "created_by=app_current_user_id() AND project_id IS NULL"
                        if table == "conversations"
                        else predicate
                    )
                    connection.execute(
                        sql.SQL(
                            "CREATE POLICY write_rows ON {} FOR INSERT WITH CHECK ("
                            + check
                            + ")"
                        ).format(identifier)
                    )
                    connection.execute(
                        sql.SQL(
                            "CREATE POLICY edit_rows ON {} FOR UPDATE USING ("
                            + predicate
                            + ") WITH CHECK ("
                            + predicate
                            + ")"
                        ).format(identifier)
                    )
                    connection.execute(
                        sql.SQL(
                            "CREATE POLICY delete_rows ON {} FOR DELETE USING ("
                            + predicate
                            + ")"
                        ).format(identifier)
                    )
                    connection.execute(
                        sql.SQL(
                            "GRANT SELECT,INSERT,UPDATE,DELETE ON {} TO nhr_runtime"
                        ).format(identifier)
                    )
                connection.execute(
                    "GRANT SELECT ON legal_sources,legal_chunks TO nhr_runtime"
                )
                migration = (
                    ROOT / "database/init/054_conversation_workspace_scope.sql"
                ).read_text(encoding="utf-8")
                connection.execute(migration)
                connection.execute(migration)  # idempotent
                connection.execute(
                    (ROOT / "database/init/055_office_project_documents.sql").read_text(
                        encoding="utf-8"
                    )
                )
                alice, bob, case, foreign_case, project, foreign_project, doc = [
                    uuid4() for _ in range(7)
                ]
                connection.execute("INSERT INTO users VALUES(%s),(%s)", (alice, bob))
                connection.execute(
                    "INSERT INTO office_cases VALUES(%s,%s),(%s,%s)",
                    (case, alice, foreign_case, bob),
                )
                connection.execute(
                    "INSERT INTO office_projects VALUES(%s,%s,%s),(%s,%s,%s)",
                    (project, alice, case, foreign_project, bob, foreign_case),
                )
                connection.execute(
                    "INSERT INTO office_case_documents VALUES(%s,%s,%s,NULL)",
                    (doc, alice, case),
                )
                connection.execute("SET ROLE nhr_runtime")

                @contextmanager
                def as_user(owner):
                    connection.execute(
                        "SELECT set_config('app.user_id',%s,false)", (str(UUID(owner)),)
                    )
                    yield connection

                old = conversations.authenticated_database_connection
                conversations.authenticated_database_connection = as_user
                try:
                    answer = VerifiedAnswer(
                        text="Kaynaklarda yeterli bilgi yok.",
                        contexts=(),
                        unverified_markers=(),
                        unsupported_claims=(),
                    )

                    def exchange(**scope):
                        with as_user(str(alice)):
                            return record_exchange(
                                connection,
                                user_id=alice,
                                conversation_id=None,
                                project_id=None,
                                question="Bu dosyada ne yazıyor?",
                                answer=answer,
                                model_name="synthetic",
                                **scope,
                            )[0]

                    case_chat = exchange(case_id=case, selected_document_ids=[doc])
                    project_chat = exchange(office_project_id=project)
                    assert [
                        item.id
                        for item in conversations.list_conversations(
                            alice, case_id=case, limit=50
                        )
                    ] == [case_chat]
                    assert [
                        item.id
                        for item in conversations.list_conversations(
                            alice, office_project_id=project, limit=50
                        )
                    ] == [project_chat]
                    detached = uuid4()
                    with as_user(str(alice)):
                        connection.execute(
                            "INSERT INTO office_case_documents VALUES(%s,%s,NULL,NULL)",
                            (detached, alice),
                        )
                    try:
                        exchange(
                            office_project_id=project, selected_document_ids=[detached]
                        )
                    except psycopg.errors.ForeignKeyViolation:
                        pass
                    else:
                        raise AssertionError("Proje dışı seçim sohbet kapsamına girdi.")
                    with as_user(str(alice)):
                        connection.execute(
                            "INSERT INTO office_project_documents(id,owner_id,project_id,document_id) VALUES(%s,%s,%s,%s)",
                            (uuid4(), alice, project, detached),
                        )
                    scoped_project_chat = exchange(
                        office_project_id=project, selected_document_ids=[detached]
                    )
                    assert conversations.get_conversation(
                        scoped_project_chat, alice
                    ).selected_document_ids == [detached]
                    detail = conversations.get_conversation(case_chat, alice)
                    assert (
                        detail.case_id == case
                        and detail.selected_document_ids == [doc]
                        and len(detail.messages) == 2
                    )
                    with as_user(str(alice)):
                        context = load_conversation_context(connection, case_chat)
                        assert (
                            context.case_id == case
                            and context.selected_document_ids == (doc,)
                        )
                        record_exchange(
                            connection,
                            user_id=alice,
                            conversation_id=case_chat,
                            project_id=None,
                            case_id=case,
                            selected_document_ids=[doc],
                            question="Peki devamında?",
                            answer=answer,
                            model_name="synthetic",
                        )
                        try:
                            record_exchange(
                                connection,
                                user_id=alice,
                                conversation_id=case_chat,
                                project_id=None,
                                case_id=foreign_case,
                                question="Yanlış kapsam",
                                answer=answer,
                                model_name="synthetic",
                            )
                        except ConversationScopeMismatch:
                            pass
                        else:
                            raise AssertionError("Kapsam değişikliği kabul edildi.")
                    assert conversations.list_conversations(bob, limit=50) == []
                    for scope in (
                        {"case_id": foreign_case},
                        {"office_project_id": foreign_project},
                        {"selected_document_ids": [uuid4()]},
                    ):
                        try:
                            exchange(**scope)
                        except psycopg.errors.ForeignKeyViolation:
                            pass
                        else:
                            raise AssertionError("Yabancı kayıt bağlandı.")
                    with as_user(str(alice)):
                        try:
                            connection.execute(
                                "UPDATE conversations SET case_id=%s WHERE id=%s",
                                (foreign_case, case_chat),
                            )
                        except psycopg.errors.CheckViolation:
                            pass
                        else:
                            raise AssertionError("Sohbet başka davaya taşındı.")
                        connection.execute(
                            "DELETE FROM office_projects WHERE id=%s", (project,)
                        )
                        assert not connection.execute(
                            "SELECT id FROM conversations WHERE id=%s", (project_chat,)
                        ).fetchone()
                        connection.execute(
                            "DELETE FROM office_cases WHERE id=%s", (case,)
                        )
                        assert not connection.execute(
                            "SELECT id FROM conversations WHERE id=%s", (case_chat,)
                        ).fetchone()
                        assert (
                            connection.execute(
                                "SELECT count(*) AS n FROM messages"
                            ).fetchone()["n"]
                            == 0
                        )
                    print(
                        "Sentetik PostgreSQL kabulü geçti: kapsam kaydı/yeniden açma, owner RLS, yabancı FK reddi, değişmez kapsam, devam ve cascade temizliği."
                    )
                finally:
                    conversations.authenticated_database_connection = old
        finally:
            if created:
                assert re.fullmatch(pattern, name)
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
                print(
                    "Yalnız bu testin oluşturduğu sentetik DB kaldırıldı; canlı sohbetler ve belgeler değiştirilmedi."
                )


if __name__ == "__main__":
    main()
