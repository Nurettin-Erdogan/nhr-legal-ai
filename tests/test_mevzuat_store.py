"""Mevzuat aktarım testleri.

Çalışan bir veritabanı gerektirir; `NHR_TEST_DATABASE_URL` tanımlı değilse
testler atlanır. Tüm yazımlar test sonunda geri alınır.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

from ingestion.mevzuat.parser import record_from_article
from ingestion.mevzuat.store import CitedLegislationChangedError, upsert_legislation
from ingestion.text import content_hash

DATABASE_URL = os.getenv("NHR_TEST_DATABASE_URL")
FIXTURES = Path(__file__).parent / "fixtures" / "mevzuat"
TEST_LAW_NO = "999999"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="NHR_TEST_DATABASE_URL tanımlı değil; veritabanı testleri atlandı.",
)


@pytest.fixture
def connection():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            yield conn
            raise psycopg.Rollback


def _record(*, raw_text: str | None = None):
    document = json.loads((FIXTURES / "search_kanun_4857.json").read_text(encoding="utf-8"))
    html = (FIXTURES / "article_4857_m25.html").read_text(encoding="utf-8")
    record = record_from_article(
        document=document["data"]["mevzuatList"][0],
        article={
            "maddeId": "1656939",
            "maddeNo": 25,
            "title": "İşverenin haklı nedenle derhal fesih hakkı",
            "mevzuatId": "103054",
        },
        article_html=html,
    )
    record = replace(
        record,
        law_no=TEST_LAW_NO,
        external_id=f"mevzuat:kanun:{TEST_LAW_NO}:m.25",
    )
    if raw_text is None:
        return record
    return replace(record, raw_text=raw_text, content_hash=content_hash(raw_text))


def _fetch_one(conn, query: str, params: tuple):
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchone()


def test_upsert_writes_legislation_details_and_chunks(connection):
    result = upsert_legislation(connection, _record())

    assert result.status == "created"
    assert result.chunk_count >= 1

    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    source = _fetch_one(
        connection,
        "SELECT source_type, ingest_status, authority, external_id"
        " FROM legal_sources WHERE id = %s",
        (result.legal_source_id,),
    )
    assert source == (
        "legislation",
        "ready",
        "Mevzuat Bilgi Sistemi",
        f"mevzuat:kanun:{TEST_LAW_NO}:m.25",
    )

    details = _fetch_one(
        connection,
        "SELECT legislation_type, law_no, article_no"
        " FROM legislation_details WHERE legal_source_id = %s",
        (result.legal_source_id,),
    )
    assert details == ("law", TEST_LAW_NO, "25")


def test_reingesting_same_article_is_idempotent(connection):
    first = upsert_legislation(connection, _record())
    second = upsert_legislation(connection, _record())

    assert second.status == "unchanged"
    assert second.legal_source_id == first.legal_source_id


def test_changed_text_does_not_replace_cited_chunks(connection):
    first = upsert_legislation(connection, _record())
    original = _record()
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO users (email, full_name) VALUES (%s, %s) RETURNING id",
            ("mevzuat-citation-guard@example.test", "Citation Guard"),
        )
        user_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO conversations (created_by, title) VALUES (%s, %s) RETURNING id",
            (user_id, "Test"),
        )
        conversation_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO messages (conversation_id, role, content)"
            " VALUES (%s, 'assistant', %s) RETURNING id",
            (conversation_id, "Kaynaklı cevap"),
        )
        message_id = cursor.fetchone()[0]
        cursor.execute(
            "SELECT id FROM legal_chunks WHERE legal_source_id = %s ORDER BY chunk_index LIMIT 1",
            (first.legal_source_id,),
        )
        chunk_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO citations (message_id, legal_chunk_id, citation_order, source_title)"
            " VALUES (%s, %s, 1, %s)",
            (message_id, chunk_id, "İş Kanunu m. 25"),
        )

    with pytest.raises(CitedLegislationChangedError, match="Atıf verilmiş"):
        upsert_legislation(connection, _record(raw_text=original.raw_text + "\n\nDeğişen metin."))

    stored_hash, = _fetch_one(
        connection,
        "SELECT content_hash FROM legal_sources WHERE id = %s",
        (first.legal_source_id,),
    )
    assert stored_hash == original.content_hash
