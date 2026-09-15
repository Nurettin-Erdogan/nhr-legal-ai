"""Retrieval ve atıf kaydı testleri.

Çalışan bir veritabanı gerektirir; `NHR_TEST_DATABASE_URL` tanımlı değilse
testler atlanır. Tüm yazımlar test sonunda geri alınır.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

psycopg = pytest.importorskip("psycopg")

from api.ai.history import record_exchange
from api.ai.retrieval import retrieve_contexts, retrieve_document_contexts
from api.ai.verification import verify_answer

DATABASE_URL = os.getenv("NHR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="NHR_TEST_DATABASE_URL tanımlı değil; veritabanı testleri atlandı.",
)

# A token no real source contains. Searching for it alone keeps the seeded rows
# the only match however large the ingested corpus grows.
TOKEN = "PYTESTKORPUS"
QUESTION = TOKEN


@pytest.fixture
def connection():
    with psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row) as conn:
        with conn.transaction():
            yield conn
            raise psycopg.Rollback


def _seed_legislation(conn) -> None:
    source_id = conn.execute(
        """
        INSERT INTO legal_sources (
            source_type, title, external_id, authority, raw_text, ingest_status
        )
        VALUES ('legislation', %s, %s, 'Mevzuat Bilgi Sistemi', %s, 'ready')
        RETURNING id
        """,
        (
            "İş Kanunu madde 25",
            f"test/{TOKEN}/law/4857/25",
            f"{TOKEN} işveren haklı nedenle derhal feshedebilir.",
        ),
    ).fetchone()["id"]
    conn.execute(
        """
        INSERT INTO legislation_details (
            legal_source_id, legislation_type, law_name, law_no, article_no, article_title
        )
        VALUES (%s, 'law', 'İş Kanunu', '4857', '25', 'İşverenin haklı nedenle fesih hakkı')
        """,
        (source_id,),
    )
    conn.execute(
        "INSERT INTO legal_chunks (legal_source_id, chunk_index, content) VALUES (%s, 0, %s)",
        (source_id, f"{TOKEN} işveren haklı nedenle derhal feshedebilir."),
    )


def _seed_decision(conn) -> None:
    source_id = conn.execute(
        """
        INSERT INTO legal_sources (
            source_type, title, external_id, authority, raw_text, published_at, ingest_status
        )
        VALUES ('court_decision', %s, %s, 'Yargıtay', %s, %s, 'ready')
        RETURNING id
        """,
        (
            "Yargıtay 9. Hukuk Dairesi kararı",
            f"test/{TOKEN}/decision/1",
            f"{TOKEN} işçi kıdem tazminatına hak kazanır.",
            date(2026, 1, 2),
        ),
    ).fetchone()["id"]
    conn.execute(
        """
        INSERT INTO court_decision_details (
            legal_source_id, court_name, chamber, docket_no, decision_no, decision_date
        )
        VALUES (%s, 'Yargıtay', '9. Hukuk Dairesi', '2026/1', '2026/2', %s)
        """,
        (source_id, date(2026, 1, 2)),
    )
    conn.execute(
        "INSERT INTO legal_chunks (legal_source_id, chunk_index, content) VALUES (%s, 0, %s)",
        (source_id, f"{TOKEN} işçi kıdem tazminatına hak kazanır."),
    )


def _seed_user(conn) -> str:
    return conn.execute(
        """
        INSERT INTO users (email, password_hash, full_name)
        VALUES (%s, 'x', 'Test Kullanıcı')
        RETURNING id
        """,
        (f"{TOKEN.lower()}@example.test",),
    ).fetchone()["id"]


def _seed_project_document(conn, user_id: str) -> tuple[str, str]:
    project_id = conn.execute(
        "INSERT INTO projects (name, created_by) VALUES (%s, %s) RETURNING id",
        ("Test Projesi", user_id),
    ).fetchone()["id"]
    conn.execute(
        """
        INSERT INTO project_members (project_id, user_id, member_role, added_by)
        VALUES (%s, %s, 'owner', %s)
        """,
        (project_id, user_id, user_id),
    )
    document_id = conn.execute(
        """
        INSERT INTO documents (
            project_id, uploaded_by, file_name, status, processed_at
        )
        VALUES (%s, %s, 'is_sozlesmesi.txt', 'ready', NOW())
        RETURNING id
        """,
        (project_id, user_id),
    ).fetchone()["id"]
    chunk_id = conn.execute(
        """
        INSERT INTO document_chunks (
            document_id, chunk_index, content, page_number, section_title
        )
        VALUES (%s, 0, %s, 2, 'Fesih')
        RETURNING id
        """,
        (document_id, f"{TOKEN} sözleşme 15 Ocak tarihinde feshedildi."),
    ).fetchone()["id"]
    return project_id, chunk_id


def test_retrieval_returns_both_legislation_and_decisions(connection):
    _seed_legislation(connection)
    _seed_decision(connection)

    contexts = retrieve_contexts(connection, question=QUESTION, top_k=10)
    seeded = [context for context in contexts if TOKEN in context.content]

    assert {context.source_type for context in seeded} == {"legislation", "court_decision"}


def test_retrieval_builds_readable_references_per_source_type(connection):
    _seed_legislation(connection)
    _seed_decision(connection)

    contexts = retrieve_contexts(connection, question=QUESTION, top_k=10)
    references = {
        context.source_type: context.reference_line
        for context in contexts
        if TOKEN in context.content
    }

    assert references["legislation"] == (
        "İş Kanunu (4857) m. 25 — İşverenin haklı nedenle fesih hakkı"
    )
    assert references["court_decision"] == (
        "Yargıtay 9. Hukuk Dairesi, E. 2026/1, K. 2026/2, T. 02.01.2026"
    )


def test_project_document_retrieval_builds_page_reference(connection):
    user_id = _seed_user(connection)
    project_id, chunk_id = _seed_project_document(connection, user_id)

    contexts = retrieve_document_contexts(
        connection,
        question=QUESTION,
        project_id=str(project_id),
        top_k=5,
    )

    assert len(contexts) == 1
    assert contexts[0].chunk_id == chunk_id
    assert contexts[0].source_type == "document"
    assert contexts[0].reference_line == "is_sozlesmesi.txt, s. 2, Fesih"


def test_record_exchange_persists_only_cited_sources(connection):
    _seed_legislation(connection)
    _seed_decision(connection)
    user_id = _seed_user(connection)

    contexts = [c for c in retrieve_contexts(connection, question=QUESTION, top_k=10)
                if TOKEN in c.content]
    assert len(contexts) == 2, "test iki kaynak parçası bekliyor"

    answer = verify_answer("Yalnızca ikinci kaynağa dayanıyorum. [K2]", contexts)
    conversation_id, message_id = record_exchange(
        connection,
        user_id=user_id,
        conversation_id=None,
        project_id=None,
        question=QUESTION,
        answer=answer,
        model_name="test-model",
    )

    roles = connection.execute(
        "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY created_at, id",
        (conversation_id,),
    ).fetchall()
    assert [row["role"] for row in roles] == ["user", "assistant"]
    assert roles[0]["content"] == QUESTION

    citations = connection.execute(
        """
        SELECT citation_order, marker, source_title, legal_chunk_id, relevance_score
        FROM citations WHERE message_id = %s ORDER BY citation_order
        """,
        (message_id,),
    ).fetchall()
    assert len(citations) == 1, "yalnızca atıf yapılan kaynak kaydedilmeli"
    assert citations[0]["marker"] == "K1"
    assert citations[0]["legal_chunk_id"] == contexts[1].chunk_id
    assert citations[0]["source_title"] == contexts[1].reference_line
    assert 0.0 <= citations[0]["relevance_score"] <= 1.0


def test_record_exchange_stores_verification_outcome(connection):
    _seed_decision(connection)
    user_id = _seed_user(connection)

    contexts = [c for c in retrieve_contexts(connection, question=QUESTION, top_k=10)
                if TOKEN in c.content]
    answer = verify_answer("Dayanak [K1] ve uydurma [K9].", contexts)

    _, message_id = record_exchange(
        connection,
        user_id=user_id,
        conversation_id=None,
        project_id=None,
        question=QUESTION,
        answer=answer,
        model_name="test-model",
    )

    metadata = connection.execute(
        "SELECT metadata FROM messages WHERE id = %s", (message_id,)
    ).fetchone()["metadata"]

    assert metadata["grounded"] is True
    assert metadata["unverified_markers"] == ["K9"]


def test_record_exchange_persists_document_citation_target(connection):
    user_id = _seed_user(connection)
    project_id, chunk_id = _seed_project_document(connection, user_id)
    contexts = retrieve_document_contexts(
        connection,
        question=QUESTION,
        project_id=str(project_id),
        top_k=5,
    )
    answer = verify_answer("Belgede fesih tarihi yer alır. [K1]", contexts)

    _, message_id = record_exchange(
        connection,
        user_id=user_id,
        conversation_id=None,
        project_id=project_id,
        question=QUESTION,
        answer=answer,
        model_name="test-model",
    )

    citation = connection.execute(
        """
        SELECT document_chunk_id, legal_chunk_id, source_locator
        FROM citations WHERE message_id = %s
        """,
        (message_id,),
    ).fetchone()
    assert citation["document_chunk_id"] == chunk_id
    assert citation["legal_chunk_id"] is None
    assert citation["source_locator"]["page_number"] == "2"
