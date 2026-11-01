"""Katmanlı aramada resmî katmanın üst sınırı (migration 050).

Ölçülen sorun (2026-10-08): yaygın tek sözcükte resmî katman yüz binlerce parçayı puanlıyordu; "tazminat" araması 35 sn
bekletip 504 verdi. Sınır yalnız eşleşme çok fazlaysa devreye girer ve sonuç "kısmi" diye işaretlenir.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from api import legal
from tests.test_ai_persistence import TOKEN, connection  # noqa: F401
from tests.test_tiered_lexical_search import _add_decision

db_required = pytest.mark.skipif(
    not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured"
)

MIGRATION = Path("database/migrations/050_capped_official_tier.sql")
INIT = Path("database/init/051_capped_official_tier.sql")


def test_migration_and_init_are_identical_and_keep_the_trust_predicate():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert sql == INIT.read_text(encoding="utf-8")
    assert "SECURITY DEFINER" in sql and "REVOKE ALL" in sql
    assert "SET search_path = pg_catalog, public" in sql
    assert "USING p_query, p_limit, p_seed_cap, p_official_cap" in sql
    assert "p_official_cap integer DEFAULT 5000" in sql
    # Eski üç parametreli sürüm kaldırılır: sınırsız resmî katman hiçbir çağrıda kalmaz.
    assert "DROP FUNCTION IF EXISTS legal_rag_current_lexical_hits_tiered(tsquery, integer, integer);" in sql
    # Uygunluk koşulu iki katmanda da aynıdır: bekleyen toplu karar aranır, doğrulanmamış mevzuat aranmaz.
    assert sql.count("ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending'") == 2
    assert sql.count("verified_against_gazette") == 2 and sql.count("verified_text_against_mbs") == 2
    assert sql.count("ls.deleted_at IS NULL AND ls.is_current") == 2


def test_search_passes_both_caps_and_bounds_the_fallback_too():
    sql = legal._CURRENT_SEARCH_SQL
    assert "%(seed_cap)s, %(official_cap)s)" in sql
    assert 0 < legal._SEARCH_FALLBACK_OFFICIAL_CAP < legal._SEARCH_OFFICIAL_CAP


def _tiered(conn, limit, seed_cap, official_cap=None):
    with conn.transaction():
        conn.execute("SET LOCAL ROLE nhr_runtime")
        if official_cap is None:
            return conn.execute(
                "SELECT * FROM legal_rag_current_lexical_hits_tiered(plainto_tsquery('turkish', %s), %s, %s)",
                (TOKEN, limit, seed_cap),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM legal_rag_current_lexical_hits_tiered(plainto_tsquery('turkish', %s), %s, %s, %s)",
            (TOKEN, limit, seed_cap, official_cap),
        ).fetchall()


@db_required
def test_official_tier_is_complete_and_unflagged_while_matches_fit_the_cap(connection):  # noqa: F811
    best = _add_decision(connection, 1, official=True, repeats=9)
    for n in range(2, 6):
        _add_decision(connection, n, official=True)

    rows = _tiered(connection, 10, 10, 5)  # eşleşme sayısı sınıra tam eşit: kısmi değil

    assert len(rows) == 5 and not any(r["capped"] for r in rows)
    top = connection.execute(
        "SELECT legal_source_id FROM legal_chunks WHERE id = %s", (rows[0]["chunk_id"],)
    ).fetchone()["legal_source_id"]
    assert top == best


@db_required
def test_more_official_matches_than_the_cap_are_sampled_and_flagged(connection):  # noqa: F811
    for n in range(1, 7):
        _add_decision(connection, n, official=True)

    rows = _tiered(connection, 10, 10, 4)

    assert len(rows) == 4 and all(r["capped"] for r in rows)


@db_required
def test_the_default_cap_applies_to_three_argument_calls_and_zero_removes_it(connection):  # noqa: F811
    for n in range(1, 4):
        _add_decision(connection, n, official=True)

    assert len(_tiered(connection, 10, 10)) == 3  # eski çağrı biçimi çalışmaya devam eder
    unbounded = _tiered(connection, 10, 10, 0)
    assert len(unbounded) == 3 and not any(r["capped"] for r in unbounded)


@db_required
def test_no_unverified_bulk_decision_is_returned_even_in_rank_order(connection):  # noqa: F811
    """Toplu kayıt (silinmiş, eski sürüm ya da güncel) hiçbir zaman dönmez (kullanıcı kararı 2026-10-18)."""
    kept = _add_decision(connection, 1, official=False, repeats=1)
    removed = _add_decision(connection, 2, official=False, repeats=9)  # en yüksek puanlı ama silinmiş
    stale = _add_decision(connection, 3, official=False, repeats=5)  # güncel sürüm değil
    connection.execute("UPDATE legal_sources SET deleted_at = now() WHERE id = %s", (removed,))
    connection.execute("UPDATE legal_sources SET is_current = false WHERE id = %s", (stale,))

    rows = _tiered(connection, 10, 100, 100)

    sources = [
        connection.execute("SELECT legal_source_id FROM legal_chunks WHERE id = %s", (r["chunk_id"],)).fetchone()["legal_source_id"]
        for r in rows
    ]
    assert sources == [] and kept


@db_required
def test_both_tiers_still_merge_by_rank(connection):  # noqa: F811
    _add_decision(connection, 1, official=True, repeats=2)
    _add_decision(connection, 2, official=False, repeats=7)
    _add_decision(connection, 3, official=False, repeats=1)

    rows = _tiered(connection, 10, 100, 100)

    assert len(rows) == 1 and not any(r["capped"] for r in rows)  # yalnız doğrulanmış karar


@db_required
def test_search_reports_partial_when_the_official_tier_is_capped(connection, monkeypatch):  # noqa: F811
    for n in range(1, 5):
        _add_decision(connection, n, official=True)
    legal._search_cache.clear()
    monkeypatch.setattr(legal, "_SEARCH_OFFICIAL_CAP", 2)

    @contextmanager
    def database_connection():
        yield connection

    monkeypatch.setattr(legal, "database_connection", database_connection)
    try:
        response = legal.search_legal_sources(q=TOKEN, limit=10, offset=0, as_of=None)
        assert response.partial is True and response.total == 2
        legal._search_cache.clear()
        monkeypatch.setattr(legal, "_SEARCH_OFFICIAL_CAP", 50)
        response = legal.search_legal_sources(q=TOKEN, limit=10, offset=0, as_of=None)
        assert response.partial is False and response.total == 4
    finally:
        legal._search_cache.clear()


def test_a_timed_out_search_falls_back_to_a_smaller_official_sample_without_the_seed_tier(monkeypatch):
    from psycopg.errors import QueryCanceled

    legal._search_cache.clear()
    attempts: list[dict] = []

    class _Connection:
        def execute(self, statement, params=None):
            if isinstance(params, dict) and "query" in params:
                attempts.append({key: params[key] for key in ("seed_cap", "official_cap")})
                if len(attempts) == 1:
                    raise QueryCanceled("canceling statement due to statement timeout")
            return self

        def fetchall(self):
            return []

    @contextmanager
    def database_connection():
        yield _Connection()

    monkeypatch.setattr(legal, "database_connection", database_connection)
    try:
        response = legal.search_legal_sources(q="yedek sorgu denemesi", limit=5, offset=0, as_of=None)
    finally:
        legal._search_cache.clear()

    assert response.total == 0
    assert attempts[0] == {"seed_cap": legal._SEARCH_SEED_CAP, "official_cap": legal._SEARCH_OFFICIAL_CAP}
    assert attempts[1] == {"seed_cap": 0, "official_cap": legal._SEARCH_FALLBACK_OFFICIAL_CAP}
