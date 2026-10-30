"""Opt-in isolated *_test DB only; every synthetic row rolls back."""
import os
import pytest
from tests.test_ai_persistence import (
    connection as _connection_fixture, _seed_decision, _seed_legislation, _seed_user,
    _seed_project_document, TOKEN,
)

connection = _connection_fixture

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


def test_unverified_bulk_records_are_not_searchable_and_stay_unpromoted(connection):
    """Uygulamada yalnız doğrulanmış kayıtlar (kullanıcı kararı 2026-10-18, migration 058); kayıt silinmez, `pending` kalır."""
    _seed_decision(connection)
    connection.execute("UPDATE legal_sources SET ingest_status='pending',ingestion_method='bulk_seed' WHERE raw_text LIKE %s", (TOKEN+'%',))
    assert page(connection) == []
    assert connection.execute('SELECT ingest_status FROM legal_sources WHERE raw_text LIKE %s', (TOKEN+'%',)).fetchone()['ingest_status'] == 'pending'


def bounded_page(connection, query_sql, filter_sql, limit=10, offset=0, max_official=3000, max_seed=2000, params=()):
    with connection.transaction():
        connection.execute('SET LOCAL ROLE nhr_runtime')
        return connection.execute(
            f"SELECT * FROM legal_rag_research_page_bounded({query_sql}, {filter_sql}, %s, %s, %s, %s)",
            (*params, limit, offset, max_official, max_seed),
        ).fetchall()


PLAIN = ("plainto_tsquery('turkish', %s)", "plainto_tsquery('turkish', %s)")


def test_bounded_page_equals_the_complete_page_under_the_caps(connection):
    _seed_decision(connection)
    _seed_legislation(connection)
    source_id = connection.execute("SELECT id FROM legal_sources WHERE source_type='court_decision' AND raw_text LIKE %s", (TOKEN+'%',)).fetchone()['id']
    connection.execute('INSERT INTO legal_chunks(legal_source_id,chunk_index,content) VALUES (%s,1,%s)', (source_id, TOKEN+' ikinci parça.'))
    first = bounded_page(connection, *PLAIN, limit=1, offset=0, params=(TOKEN, TOKEN))
    second = bounded_page(connection, *PLAIN, limit=1, offset=1, params=(TOKEN, TOKEN))
    assert first[0]['total'] == second[0]['total'] == 2 and first[0]['partial'] is False
    assert first[0]['source_id'] != second[0]['source_id']
    assert {row['source_id'] for row in first + second} == {row['source_id'] for row in page(connection, 10, 0)}


def test_bounded_page_still_enforces_the_phrase(connection):
    """Adaylar ifadesiz sorguyla seçilir, ama sonuçta ifade (yan yana kelimeler) yine şarttır."""
    _seed_decision(connection)  # "... işçi kıdem tazminatına hak kazanır."
    other = connection.execute(
        "INSERT INTO legal_sources (source_type, title, external_id, authority, raw_text, ingest_status, canonical_source_name, ingestion_method, source_version) "
        "VALUES ('court_decision', 'Ayrık', %s, 'Yargıtay', %s, 'ready', 'Yargıtay Karar Arama', 'yargitay_public_json_http', '1') RETURNING id",
        (f"test/{TOKEN}/decision/ayrik", f"{TOKEN} kıdem hesabı yapılmadan tazminat istendi."),
    ).fetchone()['id']
    rows = bounded_page(
        connection,
        "plainto_tsquery('turkish', %s) && phraseto_tsquery('turkish', %s)", "plainto_tsquery('turkish', %s)",
        params=(f"{TOKEN} kıdem tazminatı", "kıdem tazminatı", f"{TOKEN} kıdem tazminatı"),
    )
    assert len(rows) == 1 and rows[0]['source_id'] != other


def test_exceeding_a_cap_is_reported_as_partial(connection):
    _seed_decision(connection)
    source_id = connection.execute("SELECT id FROM legal_sources WHERE raw_text LIKE %s", (TOKEN+'%',)).fetchone()['id']
    connection.execute('INSERT INTO legal_chunks(legal_source_id,chunk_index,content) VALUES (%s,1,%s)', (source_id, TOKEN+' ikinci parça.'))
    rows = bounded_page(connection, *PLAIN, max_seed=1, params=(TOKEN, TOKEN))
    assert rows and rows[0]['partial'] is True and rows[0]['total'] == 1
    # Toplu katman hiç taranmazsa (yalnız resmî katman) sonuç yine "kısmi" sayılır.
    assert bounded_page(connection, *PLAIN, max_seed=0, params=(TOKEN, TOKEN)) == []


def test_the_official_tier_is_searched_even_when_the_bulk_tier_is_skipped(connection):
    _seed_decision(connection)
    vector = '[' + ','.join(['0.01'] * 768) + ']'  # sütun boyutsuz `vector`; API varsayılanı 768
    connection.execute(
        "UPDATE legal_chunks SET embedding = %s::vector WHERE legal_source_id IN (SELECT id FROM legal_sources WHERE raw_text LIKE %s)",
        (vector, TOKEN + '%'),
    )
    rows = bounded_page(connection, *PLAIN, max_seed=0, params=(TOKEN, TOKEN))
    assert len(rows) == 1 and rows[0]['partial'] is True
    assert bounded_page(connection, *PLAIN, max_official=0, max_seed=0, params=(TOKEN, TOKEN)) == []


@pytest.mark.parametrize('field', ['deleted_at = now()', 'is_current = false', "ingest_status = 'pending'"])
def test_ineligible_sources_do_not_leak_through_the_bounded_function(connection, field):
    _seed_decision(connection)
    connection.execute(f'UPDATE legal_sources SET {field} WHERE raw_text LIKE %s', (TOKEN+'%',))
    assert bounded_page(connection, *PLAIN, params=(TOKEN, TOKEN)) == []


def test_bounded_page_never_reads_private_documents_or_unverified_laws(connection):
    _seed_decision(connection)
    _seed_legislation(connection)
    _seed_project_document(connection, _seed_user(connection))
    connection.execute("UPDATE legal_sources SET metadata='{}' WHERE source_type='legislation' AND raw_text LIKE %s", (TOKEN+'%',))
    assert bounded_page(connection, *PLAIN, params=(TOKEN, TOKEN))[0]['total'] == 1


def test_a_higher_scoring_unverified_bulk_record_never_appears(connection):
    """Sayfa yalnız doğrulanmış sonuçları gösterir; yüksek puanlı doğrulanmamış toplu kayıt hiç görünmez (2026-10-18)."""
    _seed_decision(connection)  # resmî, TOKEN bir kez geçer
    verified = connection.execute("SELECT id FROM legal_sources WHERE raw_text LIKE %s", (TOKEN + '%',)).fetchone()['id']
    seed = connection.execute(
        "INSERT INTO legal_sources (source_type, title, external_id, authority, raw_text, ingest_status, canonical_source_name, ingestion_method, source_version) "
        "VALUES ('court_decision', 'Toplu', %s, 'Yargıtay', %s, 'pending', 'Yargıtay Karar Arama', 'bulk_seed', '1') RETURNING id",
        (f"test/{TOKEN}/decision/toplu", f"{TOKEN} " * 6),
    ).fetchone()['id']
    connection.execute("INSERT INTO legal_chunks(legal_source_id, chunk_index, content) VALUES (%s, 0, %s)", (seed, f"{TOKEN} " * 6))
    rows = bounded_page(connection, *PLAIN, params=(TOKEN, TOKEN))
    assert [row['source_id'] for row in rows] == [verified] and seed
