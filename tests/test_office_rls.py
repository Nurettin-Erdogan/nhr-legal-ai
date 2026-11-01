"""Exercise office policies as the real runtime role, in a rollback-only test DB."""
import os
from uuid import uuid4

import psycopg
import pytest

pytestmark = pytest.mark.skipif(not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured")


@pytest.fixture
def office_db():
    connection = psycopg.connect(os.environ["NHR_TEST_DATABASE_URL"])
    alice, bob, client = uuid4(), uuid4(), uuid4()
    try:
        for user in (alice, bob):
            connection.execute("INSERT INTO users (id, email, password_hash, full_name) VALUES (%s, %s, %s, %s)",
                               (user, f"{user}@test.invalid", "not-a-password", "Test"))
        connection.execute("INSERT INTO office_clients (id, owner_id, full_name) VALUES (%s, %s, %s)", (client, alice, "Private client"))
        connection.execute("SET LOCAL ROLE nhr_runtime")
        connection.execute("SELECT set_config('app.user_id', %s, true)", (str(bob),))
        yield connection, alice, bob, client
    finally:
        connection.rollback()
        connection.close()


def test_other_users_office_records_are_invisible_and_immutable(office_db):
    connection, alice, bob, client = office_db
    assert connection.execute("SELECT id FROM office_clients WHERE id=%s", (client,)).fetchall() == []
    assert connection.execute("UPDATE office_clients SET full_name='bad' WHERE id=%s", (client,)).rowcount == 0
    assert connection.execute("DELETE FROM office_clients WHERE id=%s", (client,)).rowcount == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
        connection.execute("INSERT INTO office_clients (id,owner_id,full_name) VALUES (%s,%s,'bad')", (uuid4(), alice))


def test_cross_owner_foreign_reference_is_rejected(office_db):
    connection, alice, bob, client = office_db
    with pytest.raises(psycopg.errors.ForeignKeyViolation), connection.transaction():
        connection.execute("INSERT INTO office_cases (id,owner_id,client_id,title) VALUES (%s,%s,%s,'bad')", (uuid4(), bob, client))


def test_own_record_and_audit_event_can_be_written(office_db):
    from api.audit import AuditContext, record_event
    connection, alice, bob, client = office_db
    record = uuid4()
    connection.execute("INSERT INTO office_clients (id,owner_id,full_name) VALUES (%s,%s,'Own')", (record, bob))
    record_event(connection, action="office.insert", actor_user_id=bob, context=AuditContext(uuid4()), entity_type="clients", entity_id=record)
    assert connection.execute("SELECT full_name FROM office_clients WHERE id=%s", (record,)).fetchone()[0] == "Own"
    assert connection.execute("SELECT count(*) FROM activity_logs WHERE entity_id=%s", (record,)).fetchone()[0] == 1


def test_case_document_cannot_link_other_users_case(office_db):
    connection, alice, bob, client = office_db
    foreign_case, own_case, own_doc, foreign_doc = uuid4(), uuid4(), uuid4(), uuid4()
    connection.execute("RESET ROLE")
    for case_id, owner in [(foreign_case, alice), (own_case, bob)]:
        connection.execute("INSERT INTO office_cases (id, owner_id, title) VALUES (%s,%s,'Test')", (case_id, owner))
    for doc_id, owner in [(own_doc, bob), (foreign_doc, alice)]:
        connection.execute("INSERT INTO office_case_documents (id,owner_id,file_name,storage_path) VALUES (%s,%s,'test.txt',%s)", (doc_id, owner, f"{owner}/{doc_id}"))
    connection.execute("SET LOCAL ROLE nhr_runtime")
    with pytest.raises(psycopg.errors.ForeignKeyViolation), connection.transaction():
        connection.execute("UPDATE office_case_documents SET case_id=%s WHERE id=%s", (foreign_case, own_doc))
    assert connection.execute("UPDATE office_case_documents SET case_id=%s WHERE id=%s", (own_case, foreign_doc)).rowcount == 0
    assert connection.execute("UPDATE office_case_documents SET case_id=%s WHERE id=%s", (own_case, own_doc)).rowcount == 1
