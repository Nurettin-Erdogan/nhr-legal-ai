"""Güncel hukuk kaynağı doğal anahtar bütünlüğü testleri."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")

DATABASE_URL = os.getenv("NHR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="NHR_TEST_DATABASE_URL tanımlı değil; veritabanı testleri atlandı.",
)


@pytest.fixture
def connection():
    with psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row) as conn:
        with conn.transaction():
            yield conn
            raise psycopg.Rollback


def _source(connection, source_type: str) -> str:
    return connection.execute(
        """
        INSERT INTO legal_sources (
            source_type, title, external_id, raw_text, ingest_status,
            canonical_source_name, ingestion_method, source_version,
            fetched_at, last_verified_at
        )
        VALUES (%s, 'Bütünlük testi', %s, 'Test metni', 'ready',
                'Test Kaynağı', 'test_fixture', '1', NOW(), NOW())
        RETURNING id
        """,
        (source_type, f"test/integrity/{uuid4()}"),
    ).fetchone()["id"]


def test_only_one_current_legislation_can_share_a_natural_key(connection):
    first_source_id = _source(connection, "legislation")
    connection.execute(
        """
        INSERT INTO legislation_details (
            legal_source_id, legislation_type, law_name, law_no, article_no
        ) VALUES (%s, 'law', 'Test Kanunu', '999981', '7')
        """,
        (first_source_id,),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        with connection.transaction():
            duplicate_source_id = _source(connection, "legislation")
            connection.execute(
                """
                INSERT INTO legislation_details (
                    legal_source_id, legislation_type, law_name, law_no, article_no
                ) VALUES (%s, 'law', 'Test Kanunu', '999981', '7')
                """,
                (duplicate_source_id,),
            )

    connection.execute(
        "UPDATE legal_sources SET is_current = FALSE WHERE id = %s",
        (first_source_id,),
    )
    replacement_source_id = _source(connection, "legislation")
    connection.execute(
        """
        INSERT INTO legislation_details (
            legal_source_id, legislation_type, law_name, law_no, article_no
        ) VALUES (%s, 'law', 'Test Kanunu', '999981', '7')
        """,
        (replacement_source_id,),
    )

    rows = connection.execute(
        """
        SELECT
            source.is_current AS source_current,
            detail.is_current AS detail_current
        FROM legislation_details AS detail
        JOIN legal_sources AS source ON source.id = detail.legal_source_id
        WHERE detail.law_no = '999981' AND detail.article_no = '7'
        ORDER BY source.is_current
        """
    ).fetchall()
    assert rows == [
        {"source_current": False, "detail_current": False},
        {"source_current": True, "detail_current": True},
    ]


def test_only_one_current_decision_can_share_a_natural_key(connection):
    first_source_id = _source(connection, "court_decision")
    connection.execute(
        """
        INSERT INTO court_decision_details (
            legal_source_id, court_name, chamber, docket_no, decision_no
        ) VALUES (%s, 'Yargıtay', 'Test Dairesi', '2099/11', '2099/22')
        """,
        (first_source_id,),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        with connection.transaction():
            duplicate_source_id = _source(connection, "court_decision")
            connection.execute(
                """
                INSERT INTO court_decision_details (
                    legal_source_id, court_name, chamber, docket_no, decision_no
                ) VALUES (%s, 'Yargıtay', 'Test Dairesi', '2099/11', '2099/22')
                """,
                (duplicate_source_id,),
            )

    connection.execute(
        "UPDATE legal_sources SET is_current = FALSE WHERE id = %s",
        (first_source_id,),
    )
    replacement_source_id = _source(connection, "court_decision")
    connection.execute(
        """
        INSERT INTO court_decision_details (
            legal_source_id, court_name, chamber, docket_no, decision_no
        ) VALUES (%s, 'Yargıtay', 'Test Dairesi', '2099/11', '2099/22')
        """,
        (replacement_source_id,),
    )

    current_count = connection.execute(
        """
        SELECT count(*) AS count
        FROM court_decision_details
        WHERE court_name = 'Yargıtay'
          AND chamber = 'Test Dairesi'
          AND docket_no = '2099/11'
          AND decision_no = '2099/22'
          AND is_current
        """
    ).fetchone()["count"]
    assert current_count == 1
