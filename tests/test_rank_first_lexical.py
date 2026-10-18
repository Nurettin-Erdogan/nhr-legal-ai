"""Full ranking and trust predicates must survive the latency optimization."""
import os
from pathlib import Path

import pytest

from tests.test_ai_persistence import connection, _seed_decision, _seed_legislation, TOKEN


def test_rank_first_migration_is_safe_and_keeps_unlimited_compatibility():
    sql = Path('database/migrations/028_rank_first_lexical.sql').read_text(encoding='utf-8')
    assert sql == Path('database/init/029_rank_first_lexical.sql').read_text(encoding='utf-8')
    assert 'USING p_query, p_limit' in sql
    assert 'SECURITY DEFINER' in sql and 'REVOKE ALL' in sql
    assert 'SET search_path = pg_catalog, public' in sql
    assert 'document_chunks' not in sql and 'p_max_candidates' not in sql
    before_filter = sql.split('CROSS JOIN LATERAL')[0]
    assert 'LIMIT' not in before_filter  # no first-N sampling before trust/ranking
    assert 'verified_text_against_mbs' in sql


db_required = pytest.mark.skipif(not os.getenv('NHR_TEST_DATABASE_URL'), reason='Isolated test DB not configured')


def hits(conn, limit=None):
    with conn.transaction():
        conn.execute('SET LOCAL ROLE nhr_runtime')
        return conn.execute("SELECT * FROM legal_rag_current_lexical_hits(plainto_tsquery('turkish',%s),%s)", (TOKEN,limit)).fetchall()


@db_required
def test_full_rank_and_limit_match_reference_query(connection):
    _seed_decision(connection)
    _seed_legislation(connection)
    source_id = connection.execute("SELECT id FROM legal_sources WHERE source_type='court_decision' AND raw_text LIKE %s", (TOKEN+'%',)).fetchone()['id']
    for i in range(1,5):
        connection.execute('INSERT INTO legal_chunks(legal_source_id,chunk_index,content) VALUES (%s,%s,%s)', (source_id,i,(TOKEN+' ')*(i+1)))
    expected = connection.execute("SELECT id AS chunk_id,ts_rank_cd(search_vector,plainto_tsquery('turkish',%s))::real AS rank FROM legal_chunks WHERE search_vector @@ plainto_tsquery('turkish',%s) ORDER BY rank DESC",(TOKEN,TOKEN)).fetchall()
    assert {r['chunk_id'] for r in hits(connection)} == {r['chunk_id'] for r in expected}
    assert [r['rank'] for r in hits(connection,3)] == [r['rank'] for r in expected[:3]]
    assert hits(connection,0) == []


@db_required
@pytest.mark.parametrize('field', ["is_current=false", "deleted_at=now()", "ingest_status='pending'"])
def test_filtered_high_rank_does_not_displace_valid_lower_rank(connection,field):
    _seed_decision(connection)
    _seed_legislation(connection)
    connection.execute(f"UPDATE legal_sources SET {field} WHERE source_type='court_decision' AND raw_text LIKE %s", (TOKEN+'%',))
    connection.execute("UPDATE legal_chunks SET content=%s WHERE legal_source_id IN (SELECT id FROM legal_sources WHERE source_type='court_decision' AND raw_text LIKE %s)",((TOKEN+' ')*20,TOKEN+'%'))
    rows=hits(connection,1)
    assert len(rows)==1
    assert connection.execute('SELECT source_type FROM legal_sources WHERE id=(SELECT legal_source_id FROM legal_chunks WHERE id=%s)',(rows[0]['chunk_id'],)).fetchone()['source_type']=='legislation'


@db_required
def test_unverified_bulk_decision_and_unverified_law_are_both_excluded(connection):
    """Uygulamada yalnız doğrulanmış kayıtlar (kullanıcı kararı 2026-10-18); toplu kayıt silinmez, `pending` kalır."""
    _seed_decision(connection)
    _seed_legislation(connection)
    connection.execute("UPDATE legal_sources SET ingest_status='pending',ingestion_method='bulk_seed' WHERE source_type='court_decision' AND raw_text LIKE %s", (TOKEN+'%',))
    connection.execute("UPDATE legal_sources SET metadata='{}' WHERE source_type='legislation' AND raw_text LIKE %s", (TOKEN+'%',))
    assert len(hits(connection))==0
    assert connection.execute("SELECT ingest_status FROM legal_sources WHERE source_type='court_decision' AND raw_text LIKE %s",(TOKEN+'%',)).fetchone()['ingest_status']=='pending'
