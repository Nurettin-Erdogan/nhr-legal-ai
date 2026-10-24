"""Panel sayaç tetikleyicileri (migration 059) gerçek şemada: fark satırı, katlama, sayım anı tutarlılığı."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from tests.test_ai_persistence import connection  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured")


def _insert(connection, *, status="pending", source_type="court_decision", authority="Yargıtay", metadata="{}"):  # noqa: F811
    return connection.execute(
        """
        INSERT INTO legal_sources (
            source_type, title, external_id, authority, raw_text, ingest_status, metadata,
            canonical_source_name, ingestion_method, source_version, fetched_at, last_verified_at
        )
        VALUES (%s, 'Sayaç testi', %s, %s, 'Test metni', %s, %s::jsonb,
                'Test Kaynağı', 'test_fixture', '1', NOW(), NOW())
        RETURNING id
        """,
        (source_type, f"test/counter/{uuid4()}", authority, status, metadata),
    ).fetchone()["id"]


def _deltas(connection):  # noqa: F811
    return {
        row["key"]: row["s"]
        for row in connection.execute("SELECT key, sum(delta)::int AS s FROM corpus_counter_deltas GROUP BY key").fetchall()
    }


@pytest.fixture
def clean(connection):  # noqa: F811
    connection.execute("DELETE FROM corpus_counter_deltas")
    return connection


def test_only_ready_current_records_are_counted(clean):
    _insert(clean, status="pending")  # doğrulanmamış: sayılmaz
    assert _deltas(clean) == {}
    _insert(clean, status="ready")
    assert _deltas(clean) == {"src|court_decision|Yargıtay": 1}


def test_becoming_ready_adds_and_going_back_removes(clean):
    source_id = _insert(clean, status="pending")
    clean.execute("UPDATE legal_sources SET ingest_status = 'ready' WHERE id = %s", (source_id,))
    assert _deltas(clean) == {"src|court_decision|Yargıtay": 1}
    clean.execute("UPDATE legal_sources SET ingest_status = 'pending' WHERE id = %s", (source_id,))
    assert _deltas(clean).get("src|court_decision|Yargıtay", 0) == 0


def test_text_only_updates_do_not_touch_counters(clean):
    source_id = _insert(clean, status="ready")
    before = clean.execute("SELECT count(*) AS n FROM corpus_counter_deltas").fetchone()["n"]
    clean.execute("UPDATE legal_sources SET raw_text = 'başka metin' WHERE id = %s", (source_id,))
    assert clean.execute("SELECT count(*) AS n FROM corpus_counter_deltas").fetchone()["n"] == before


def test_deleting_or_soft_deleting_removes_the_count(clean):
    first = _insert(clean, status="ready")
    second = _insert(clean, status="ready")
    clean.execute("UPDATE legal_sources SET deleted_at = NOW() WHERE id = %s", (first,))
    assert _deltas(clean)["src|court_decision|Yargıtay"] == 1
    clean.execute("DELETE FROM legal_sources WHERE id = %s", (second,))
    assert _deltas(clean).get("src|court_decision|Yargıtay", 0) == 0


def test_legislation_counts_only_when_verified_against_an_official_catalog(clean):
    _insert(clean, status="ready", source_type="legislation", authority="Mevzuat")
    assert _deltas(clean) == {}
    _insert(clean, status="ready", source_type="legislation", authority="Mevzuat", metadata='{"verified_against_mbs": "true"}')
    assert _deltas(clean) == {"src|legislation|Mevzuat": 1}


def test_counts_are_base_plus_deltas_and_compaction_keeps_the_totals(clean):
    clean.execute("DELETE FROM corpus_counters")
    clean.execute("INSERT INTO corpus_counters VALUES ('src|court_decision|Yargıtay', 1000)")
    _insert(clean, status="ready")
    _insert(clean, status="ready")
    totals = {row["key"]: row["n"] for row in clean.execute("SELECT * FROM corpus_counts()").fetchall()}
    assert totals["src|court_decision|Yargıtay"] == 1002
    folded = clean.execute("SELECT corpus_counters_compact() AS n").fetchone()["n"]
    assert folded == 2
    assert clean.execute("SELECT count(*) AS n FROM corpus_counter_deltas").fetchone()["n"] == 0
    totals = {row["key"]: row["n"] for row in clean.execute("SELECT * FROM corpus_counts()").fetchall()}
    assert totals["src|court_decision|Yargıtay"] == 1002


def test_nothing_is_reported_before_the_base_is_built(clean):
    clean.execute("DELETE FROM corpus_counters")
    _insert(clean, status="ready")
    assert clean.execute("SELECT * FROM corpus_counts()").fetchall() == []


def test_rebuild_refuses_to_run_outside_repeatable_read(clean):
    with pytest.raises(Exception, match="REPEATABLE READ"):
        clean.execute("SELECT corpus_counters_rebuild()")
