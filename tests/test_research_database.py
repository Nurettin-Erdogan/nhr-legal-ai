"""Opt-in isolated *_test DB only; every synthetic row rolls back."""
import os
import pytest
from tests.test_ai_persistence import (
    connection, _seed_decision, _seed_legislation, _seed_user,
    _seed_project_document, TOKEN,
)

pytestmark = pytest.mark.skipif(not os.getenv('NHR_TEST_DATABASE_URL'), reason='Isolated test DB not configured')


def page(connection, limit=10, offset=0):
    # Exercise the actual application role, not an unrestricted admin read.
    with connection.transaction():
        connection.execute('SET LOCAL ROLE nhr_runtime')
        return connection.execute(
            "SELECT * FROM legal_rag_research_page(plainto_tsquery('turkish', %s), %s, %s)",
            (TOKEN, limit, offset),
        ).fetchall()


def test_research_count_is_distinct_and_all_pages_are_reachable(connection):
    _seed_decision(connection)
    _seed_legislation(connection)
    source_id = connection.execute("SELECT id FROM legal_sources WHERE source_type='court_decision' AND raw_text LIKE %s", (TOKEN+'%',)).fetchone()['id']
    connection.execute('INSERT INTO legal_chunks(legal_source_id,chunk_index,content) VALUES (%s,1,%s)', (source_id, TOKEN+' ikinci parça.'))
    first, second = page(connection,1,0), page(connection,1,1)
    assert first[0]['total'] == second[0]['total'] == 2
    assert first[0]['source_id'] != second[0]['source_id']
    assert page(connection,1,2) == []


def test_research_never_reads_private_documents_or_unverified_laws(connection):
    _seed_decision(connection)
    _seed_legislation(connection)
    _seed_project_document(connection, _seed_user(connection))
    connection.execute("UPDATE legal_sources SET metadata='{}' WHERE source_type='legislation' AND raw_text LIKE %s", (TOKEN+'%',))
    assert page(connection)[0]['total'] == 1


@pytest.mark.parametrize('field', ['deleted_at = now()', 'is_current = false', "ingest_status = 'pending'"])
def test_ineligible_sources_do_not_leak_through_definer_function(connection, field):
    _seed_decision(connection)
    connection.execute(f'UPDATE legal_sources SET {field} WHERE raw_text LIKE %s', (TOKEN+'%',))
    assert page(connection) == []


def test_third_party_remains_searchable_without_being_promoted(connection):
    _seed_decision(connection)
    connection.execute("UPDATE legal_sources SET ingest_status='pending',ingestion_method='bulk_seed' WHERE raw_text LIKE %s", (TOKEN+'%',))
    assert page(connection)[0]['total'] == 1
    assert connection.execute('SELECT ingest_status FROM legal_sources WHERE raw_text LIKE %s', (TOKEN+'%',)).fetchone()['ingest_status'] == 'pending'
