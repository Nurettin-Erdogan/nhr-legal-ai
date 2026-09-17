"""Hukuk araştırması API'sinin karar ve mevzuatı birlikte sunma testleri."""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest

psycopg = pytest.importorskip("psycopg")

from api import legal

DATABASE_URL = os.getenv("NHR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="NHR_TEST_DATABASE_URL tanımlı değil; veritabanı testleri atlandı.",
)

TOKEN = "pytest987654"
TEST_LAW_NO = "999992"


@pytest.fixture
def connection():
    with psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row) as conn:
        with conn.transaction():
            yield conn
            raise psycopg.Rollback


def _seed_legislation(connection):
    source_id = connection.execute(
        """
        INSERT INTO legal_sources (
            source_type, title, external_id, authority, raw_text, ingest_status, metadata,
            canonical_source_name, ingestion_method, source_version,
            fetched_at, last_verified_at
        )
        VALUES (
            'legislation', %s, %s, 'Mevzuat Bilgi Sistemi', %s, 'ready',
            '{"verified_against_gazette":true,"verified_against_mbs":true}',
            'Mevzuat Bilgi Sistemi', 'bedesten_public_json_http', '1',
            NOW(), NOW()
        )
        RETURNING id
        """,
        (
            "İş Kanunu m. 25 — Haklı fesih",
            f"test/{TOKEN}/law/{TEST_LAW_NO}/25",
            f"{TOKEN} işveren haklı nedenle derhal feshedebilir.",
        ),
    ).fetchone()["id"]
    connection.execute(
        """
        INSERT INTO legislation_details (
            legal_source_id, legislation_type, law_name, law_no, article_no,
            article_title, official_gazette_no
        )
        VALUES (%s, 'law', 'İş Kanunu', %s, '25', 'Haklı fesih', '25134')
        """,
        (source_id, TEST_LAW_NO),
    )
    connection.execute(
        """
        INSERT INTO legal_chunks (legal_source_id, chunk_index, content)
        VALUES (%s, 0, %s)
        """,
        (source_id, f"{TOKEN} işveren haklı nedenle derhal feshedebilir."),
    )
    return source_id


def _use_connection(monkeypatch, connection) -> None:
    @contextmanager
    def database_connection():
        yield connection

    monkeypatch.setattr(legal, "database_connection", database_connection)


def test_search_returns_legislation_metadata(connection, monkeypatch):
    source_id = _seed_legislation(connection)
    _use_connection(monkeypatch, connection)

    response = legal.search_legal_sources(
        q=f"{TOKEN} eşleşmeyenifade",
        limit=10,
        offset=0,
    )

    result = next(item for item in response.results if item.id == source_id)
    assert result.source_type == "legislation"
    assert result.law_name == "İş Kanunu"
    assert result.law_no == TEST_LAW_NO
    assert result.article_no == "25"
    assert result.chamber is None


def test_unverified_legislation_is_not_public(connection, monkeypatch):
    source_id = _seed_legislation(connection)
    connection.execute(
        "UPDATE legal_sources SET metadata = '{}'::jsonb WHERE id = %s",
        (source_id,),
    )
    _use_connection(monkeypatch, connection)

    response = legal.search_legal_sources(q=TOKEN, limit=10, offset=0)
    assert all(item.id != source_id for item in response.results)
    with pytest.raises(legal.HTTPException) as exc:
        legal.legal_source_detail(source_id)
    assert exc.value.status_code == 404


def test_source_detail_returns_legislation_and_chunks(connection, monkeypatch):
    source_id = _seed_legislation(connection)
    _use_connection(monkeypatch, connection)

    source = legal.legal_source_detail(source_id)

    assert source.source_type == "legislation"
    assert source.law_name == "İş Kanunu"
    assert source.official_gazette_no == "25134"
    assert len(source.chunks) == 1
    assert TOKEN in source.raw_text
