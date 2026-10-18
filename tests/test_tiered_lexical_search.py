"""Katmanlı sözcük araması: resmî katman tam puanlanır, doğrulanmamış toplu katman sınırlanır."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from api import legal
from tests.test_ai_persistence import TOKEN, _seed_decision, _seed_legislation, connection  # noqa: F401

db_required = pytest.mark.skipif(
    not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured"
)

MIGRATION = Path("database/migrations/032_tiered_lexical_search.sql")
INIT = Path("database/init/033_tiered_lexical_search.sql")


def test_migration_and_init_are_identical_and_keep_the_trust_predicate():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert sql == INIT.read_text(encoding="utf-8")
    assert "SECURITY DEFINER" in sql and "REVOKE ALL" in sql
    assert "SET search_path = pg_catalog, public" in sql
    assert "USING p_query, p_limit, p_seed_cap" in sql
    # Uygunluk koşulu tam sürümle aynı: bekleyen toplu karar aranır, doğrulanmamış mevzuat aranmaz.
    assert "ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending'" in sql
    assert "verified_against_gazette" in sql and "verified_text_against_mbs" in sql
    # Resmî katmanda örnekleme yok: LATERAL uygunluk öncesi LIMIT bulunmaz.
    official = sql.split("seed_raw AS MATERIALIZED")[0]
    assert "LIMIT" not in official.split("CROSS JOIN LATERAL")[0]
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_legal_chunks_search_vector_official" in sql
    assert "WHERE embedding IS NOT NULL" in sql


def test_current_search_uses_the_tiered_function_and_reports_partial():
    sql = legal._CURRENT_SEARCH_SQL
    assert "legal_rag_current_lexical_hits_tiered" in sql
    assert "%(seed_cap)s" in sql
    assert "bool_or(hits.capped)" in sql
    # Geniş (VEYA) yedek yalnız resmî katmanda sınırlı örnektir ve her zaman kısmidir.
    assert "legal_rag_current_lexical_hits_official_bounded" in legal._CURRENT_SEARCH_OR_SQL
    assert "true AS partial" in legal._CURRENT_SEARCH_OR_SQL


def _tiered(conn, limit, seed_cap):
    with conn.transaction():
        conn.execute("SET LOCAL ROLE nhr_runtime")
        return conn.execute(
            "SELECT * FROM legal_rag_current_lexical_hits_tiered(plainto_tsquery('turkish', %s), %s, %s)",
            (TOKEN, limit, seed_cap),
        ).fetchall()


def _add_decision(conn, n: int, *, official: bool, repeats: int = 1) -> str:
    source_id = conn.execute(
        """
        INSERT INTO legal_sources (
            source_type, title, external_id, authority, raw_text, ingest_status,
            canonical_source_name, ingestion_method, source_version, fetched_at, last_verified_at
        )
        VALUES ('court_decision', %s, %s, 'Yargıtay', %s, %s, 'Yargıtay', %s, '1', NOW(), NOW())
        RETURNING id
        """,
        (
            f"Karar {n}",
            f"test/{TOKEN}/tier/{'o' if official else 's'}{n}",
            TOKEN,
            "ready" if official else "pending",
            "yargitay_public_json_http" if official else "bulk_seed",
        ),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO legal_chunks (legal_source_id, chunk_index, content, embedding)"
        " VALUES (%s, 0, %s, CASE WHEN %s THEN '[0.1,0.2,0.3]'::vector END)",
        (source_id, (TOKEN + " ") * repeats, official),
    )
    return source_id


@db_required
def test_official_tier_is_ranked_in_full_and_never_sampled(connection):  # noqa: F811
    best = _add_decision(connection, 1, official=True, repeats=9)
    for n in range(2, 7):
        _add_decision(connection, n, official=True, repeats=1)
    # Seed sınırı 0 olsa bile resmî katman eksiksiz puanlanır. Embedding'siz katman atlanınca sonuç kısmidir: orada
    # embedding'i henüz hazırlanmamış resmî parçalar da olabilir.
    rows = _tiered(connection, 3, 0)
    assert len(rows) == 3 and all(r["capped"] for r in rows)
    top = connection.execute(
        "SELECT legal_source_id FROM legal_chunks WHERE id = %s", (rows[0]["chunk_id"],)
    ).fetchone()["legal_source_id"]
    assert top == best
    assert [r["rank"] for r in rows] == sorted((r["rank"] for r in rows), reverse=True)


@db_required
def test_unverified_bulk_decisions_are_never_returned_whatever_the_seed_cap(connection):  # noqa: F811
    """Uygulamada yalnız doğrulanmış kayıtlar (kullanıcı kararı 2026-10-18): toplu kayıt hiçbir sınırla dönmez."""
    for n in range(1, 5):
        _add_decision(connection, n, official=False)
    for seed_cap in (0, 2, 4, 10):
        assert _tiered(connection, 10, seed_cap) == []


@db_required
def test_both_tiers_merge_by_rank_and_match_the_full_function_when_not_capped(connection):  # noqa: F811
    _add_decision(connection, 1, official=True, repeats=2)
    _add_decision(connection, 2, official=False, repeats=7)
    _add_decision(connection, 3, official=False, repeats=1)
    tiered = _tiered(connection, 10, 100)
    with connection.transaction():
        connection.execute("SET LOCAL ROLE nhr_runtime")
        full = connection.execute(
            "SELECT * FROM legal_rag_current_lexical_hits(plainto_tsquery('turkish', %s), 10)", (TOKEN,)
        ).fetchall()
    assert [(r["chunk_id"], r["rank"]) for r in tiered] == [(r["chunk_id"], r["rank"]) for r in full]
    assert len(tiered) == 1 and not any(r["capped"] for r in tiered)  # yalnız doğrulanmış karar


@db_required
def test_trust_predicate_still_applies_in_both_tiers(connection):  # noqa: F811
    official = _add_decision(connection, 1, official=True)
    seed = _add_decision(connection, 2, official=False)
    unverified_law_chunk = _add_decision(connection, 3, official=True)
    connection.execute(
        "UPDATE legal_sources SET deleted_at = now() WHERE id = %s", (official,)
    )
    connection.execute(
        "UPDATE legal_sources SET is_current = false WHERE id = %s", (unverified_law_chunk,)
    )
    rows = _tiered(connection, 10, 100)
    sources = {
        connection.execute(
            "SELECT legal_source_id FROM legal_chunks WHERE id = %s", (r["chunk_id"],)
        ).fetchone()["legal_source_id"]
        for r in rows
    }
    assert sources == set()  # resmî kayıt silinmiş, diğeri güncel değil, toplu kayıt hiç aranmaz
    assert seed


@db_required
def test_search_never_returns_unverified_bulk_decisions(connection, monkeypatch):  # noqa: F811
    for n in range(1, 4):
        _add_decision(connection, n, official=False)
    official = _add_decision(connection, 9, official=True)
    legal._search_cache.clear()

    @contextmanager
    def database_connection():
        yield connection

    monkeypatch.setattr(legal, "database_connection", database_connection)
    try:
        response = legal.search_legal_sources(q=TOKEN, limit=10, offset=0, as_of=None)
        assert response.partial is False and response.total == 1
        assert [str(result.id) for result in response.results] == [str(official)]
    finally:
        legal._search_cache.clear()


def test_a_timed_out_search_is_reported_as_a_timeout_not_as_a_database_outage(monkeypatch):
    from psycopg.errors import QueryCanceled

    legal._search_cache.clear()

    class _Connection:
        def execute(self, statement, params=None):
            if isinstance(params, dict) and "query" in params:
                raise QueryCanceled("canceling statement due to statement timeout")
            return self

        def fetchall(self):
            return []

    @contextmanager
    def database_connection():
        yield _Connection()

    monkeypatch.setattr(legal, "database_connection", database_connection)

    with pytest.raises(legal.HTTPException) as exc:
        legal.search_legal_sources(q="zaman asimi sorgusu", limit=5, offset=0, as_of=None)

    assert exc.value.status_code == 504
    assert "zaman aşımı" in exc.value.detail


@db_required
def test_or_fallback_scores_only_a_bounded_official_sample_and_keeps_the_trust_predicate(connection):  # noqa: F811
    official = [_add_decision(connection, n, official=True, repeats=n) for n in range(1, 5)]
    _add_decision(connection, 9, official=False)  # toplu katman bu yedekte taranmaz
    deleted = _add_decision(connection, 10, official=True)
    connection.execute("UPDATE legal_sources SET deleted_at = now() WHERE id = %s", (deleted,))

    def fallback(max_candidates):
        with connection.transaction():
            connection.execute("SET LOCAL ROLE nhr_runtime")
            return connection.execute(
                "SELECT * FROM legal_rag_current_lexical_hits_official_bounded("
                "plainto_tsquery('turkish', %s), 10, %s)",
                (TOKEN, max_candidates),
            ).fetchall()

    rows = fallback(100)
    found = {
        connection.execute(
            "SELECT legal_source_id FROM legal_chunks WHERE id = %s", (r["chunk_id"],)
        ).fetchone()["legal_source_id"]
        for r in rows
    }
    assert found == set(official)
    assert len(fallback(2)) <= 2
