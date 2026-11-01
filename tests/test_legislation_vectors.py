"""Mevzuat için ayrı anlam araması (migration 060): kopya tablo, tetikleyici eşitlemesi, erişim ve arama kolu."""
from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from api.ai import retrieval
from tests.test_ai_persistence import TOKEN, _seed_decision, _seed_legislation, connection as _connection_fixture

connection = _connection_fixture

db_required = pytest.mark.skipif(not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured")
MODEL = "nomic-embed-text"


def _vector(first: float, second: float = 0.0) -> list[float]:
    return [first, second] + [0.001] * 766


def _literal(values: list[float]) -> str:
    return "[" + ",".join(str(value) for value in values) + "]"


def _chunk(connection, source_type: str):
    return connection.execute(
        "SELECT chunk.id, chunk.legal_source_id FROM legal_chunks chunk JOIN legal_sources ls ON ls.id = chunk.legal_source_id "
        "WHERE ls.source_type = %s AND ls.raw_text LIKE %s", (source_type, TOKEN + "%")).fetchone()


def _embed(connection, chunk_id, values):
    connection.execute("UPDATE legal_chunks SET embedding = %s::vector, embedding_model = %s WHERE id = %s",
                       (None if values is None else _literal(values), MODEL, chunk_id))


def _copied(connection, chunk_id) -> bool:
    return connection.execute("SELECT 1 FROM legislation_chunk_vectors WHERE chunk_id = %s", (chunk_id,)).fetchone() is not None


def test_the_init_copy_matches_the_migration():
    migration = Path("database/migrations/060_legislation_vectors.sql").read_text(encoding="utf-8")
    assert migration == Path("database/init/061_legislation_vectors.sql").read_text(encoding="utf-8")
    assert "SECURITY DEFINER" in migration and "ENABLE ROW LEVEL SECURITY" in migration
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE" in migration


@db_required
def test_only_legislation_vectors_are_copied_and_kept_in_sync(connection):  # noqa: F811
    _seed_legislation(connection)
    _seed_decision(connection)
    law, decision = _chunk(connection, "legislation"), _chunk(connection, "court_decision")
    _embed(connection, law["id"], _vector(1.0))
    _embed(connection, decision["id"], _vector(1.0))
    assert _copied(connection, law["id"]) and not _copied(connection, decision["id"])
    _embed(connection, law["id"], _vector(0.0, 1.0))
    stored = connection.execute("SELECT embedding::text AS e FROM legislation_chunk_vectors WHERE chunk_id = %s",
                                (law["id"],)).fetchone()["e"]
    assert stored.startswith("[0,1,")
    _embed(connection, law["id"], None)
    assert not _copied(connection, law["id"])


@db_required
def test_the_application_role_can_read_but_never_write(connection):  # noqa: F811
    _seed_legislation(connection)
    law = _chunk(connection, "legislation")
    _embed(connection, law["id"], _vector(1.0))
    with connection.transaction():
        connection.execute("SET LOCAL ROLE nhr_runtime")
        assert connection.execute("SELECT count(*) AS n FROM legislation_chunk_vectors WHERE chunk_id = %s",
                                  (law["id"],)).fetchone()["n"] == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
        connection.execute("SET LOCAL ROLE nhr_runtime")
        connection.execute("DELETE FROM legislation_chunk_vectors WHERE chunk_id = %s", (law["id"],))


@db_required
def test_a_relevant_provision_keeps_a_place_next_to_closer_decisions(connection):  # noqa: F811
    """2026-10-22: decisions filled every ANN slot and the governing article (TBK m. 72) never became a candidate."""
    _seed_legislation(connection)
    _seed_decision(connection)
    law, decision = _chunk(connection, "legislation"), _chunk(connection, "court_decision")
    _embed(connection, decision["id"], _vector(1.0))  # identical to the question
    _embed(connection, law["id"], _vector(0.9, 0.3))  # farther than the decision
    question = f"{TOKEN} işveren haklı nedenle feshedebilir mi"
    info = {}
    rows = retrieval.retrieve_contexts(connection, question=question, top_k=1, query_embedding=_vector(1.0),
                                       embedding_model=MODEL, diagnostics=info)
    assert info["legislation_candidates"] >= 1
    assert [row.chunk_id for row in rows] == [law["id"]]


@db_required
def test_a_deleted_or_unverified_provision_is_not_returned_from_the_copy(connection):  # noqa: F811
    _seed_legislation(connection)
    law = _chunk(connection, "legislation")
    _embed(connection, law["id"], _vector(1.0))
    connection.execute("UPDATE legal_sources SET metadata = '{}' WHERE id = %s", (law["legal_source_id"],))
    rows = retrieval._execute_retrieval(connection, retrieval.LEGISLATION_SEMANTIC_SQL, {
        "embedding": _literal(_vector(1.0)), "embedding_model": MODEL, "legislation_limit": 24, "as_of": None,
        "question": TOKEN, "required_phrase": "", "top_k": 5, "candidate_limit": 5})
    assert all(row.chunk_id != law["id"] for row in rows)


def _m3(first: float, second: float = 0.0) -> str:
    return _literal([first, second] + [0.001] * 1022)


@db_required
def test_the_second_model_vector_is_searched_and_dropped_when_the_text_changes(connection):  # noqa: F811
    """Migration 061: bge-m3 vectors for legislation; a re-embedded (changed) chunk loses its stale m3 vector."""
    _seed_legislation(connection)
    _seed_decision(connection)
    law = _chunk(connection, "legislation")
    _embed(connection, law["id"], _vector(0.0, 1.0))  # far for the shared model
    connection.execute("UPDATE legislation_chunk_vectors SET embedding_m3 = %s::vector WHERE chunk_id = %s",
                       (_m3(1.0), law["id"]))
    info = {}
    rows = retrieval.retrieve_contexts(connection, question=f"{TOKEN} işveren haklı nedenle feshedebilir mi", top_k=1,
                                       query_embedding=_vector(1.0), embedding_model=MODEL, diagnostics=info,
                                       legislation_embedding=[1.0, 0.0] + [0.001] * 1022)
    assert info["legislation_m3_candidates"] >= 1 and rows[0].chunk_id == law["id"]
    _embed(connection, law["id"], _vector(0.5, 0.5))  # new text -> new shared vector
    assert connection.execute("SELECT embedding_m3 FROM legislation_chunk_vectors WHERE chunk_id = %s",
                              (law["id"],)).fetchone()["embedding_m3"] is None


def test_the_m3_init_copy_matches_its_migration():
    migration = Path("database/migrations/061_legislation_vectors_m3.sql").read_text(encoding="utf-8")
    assert migration == Path("database/init/062_legislation_vectors_m3.sql").read_text(encoding="utf-8")
