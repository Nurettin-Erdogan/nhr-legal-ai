"""Mevzuat aktarım testleri.

Çalışan bir veritabanı gerektirir; `NHR_TEST_DATABASE_URL` tanımlı değilse
testler atlanır. Tüm yazımlar test sonunda geri alınır.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

psycopg = pytest.importorskip("psycopg")

from ingestion.mevzuat.models import LegislationRecord
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
        "pending",
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


def test_both_official_checks_are_required_for_ready(connection):
    record = _record()
    verified = replace(
        record,
        metadata={
            **record.metadata,
            "verified_against_gazette": True,
            "verified_against_mbs": True,
        },
    )
    result = upsert_legislation(connection, verified)
    source = _fetch_one(
        connection,
        "SELECT ingest_status, last_verified_at IS NOT NULL FROM legal_sources WHERE id = %s",
        (result.legal_source_id,),
    )
    assert source == ("ready", True)


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

    second = upsert_legislation(
        connection, _record(raw_text=original.raw_text + "\n\nDeğişen metin.")
    )

    assert second.status == "new_version"
    assert second.legal_source_id != first.legal_source_id

    stored_hash, is_current = _fetch_one(
        connection,
        "SELECT content_hash, is_current FROM legal_sources WHERE id = %s",
        (first.legal_source_id,),
    )
    assert stored_hash == original.content_hash
    assert is_current is False


def _version(record, *, day: date, suffix: str):
    text = f"{record.raw_text}\n\n{suffix}"
    return replace(
        record,
        raw_text=text,
        content_hash=content_hash(text),
        version_date=day,
    )


def test_revisiting_historical_version_preserves_current_and_lineage(connection):
    base = _record()
    old = _version(base, day=date(2023, 5, 22), suffix="Eski metin")
    current = _version(base, day=date(2024, 8, 20), suffix="Güncel metin")
    first = upsert_legislation(connection, old)
    second = upsert_legislation(connection, current)

    revisit = upsert_legislation(connection, old)
    assert revisit.status == "unchanged"
    assert revisit.legal_source_id == first.legal_source_id
    rows = connection.execute(
        "SELECT id, revision, is_current, superseded_by_id, content_hash "
        "FROM legal_sources WHERE source_type = 'legislation' AND external_id = %s "
        "ORDER BY revision",
        (old.external_id,),
    ).fetchall()
    assert len(rows) == 2
    assert rows[0] == (
        UUID(first.legal_source_id), 1, False,
        UUID(second.legal_source_id), old.content_hash,
    )
    assert rows[1] == (UUID(second.legal_source_id), 2, True, None, current.content_hash)
    assert _fetch_one(
        connection,
        "SELECT count(*) FROM legal_source_revisions WHERE legal_source_id IN (%s, %s)",
        (first.legal_source_id, second.legal_source_id),
    ) == (2,)


def test_new_older_snapshot_is_archived_without_demoting_current(connection):
    base = _record()
    old = _version(base, day=date(2023, 5, 22), suffix="İlk metin")
    current = _version(base, day=date(2024, 8, 20), suffix="Güncel metin")
    middle = _version(base, day=date(2024, 1, 1), suffix="Ara metin")
    first = upsert_legislation(connection, old)
    second = upsert_legislation(connection, current)
    third = upsert_legislation(connection, middle)

    assert third.status == "new_version"
    rows = connection.execute(
        "SELECT id, revision, is_current, superseded_by_id FROM legal_sources "
        "WHERE source_type = 'legislation' AND external_id = %s ORDER BY revision",
        (old.external_id,),
    ).fetchall()
    assert rows == [
        (UUID(first.legal_source_id), 1, False, UUID(second.legal_source_id)),
        (UUID(second.legal_source_id), 2, True, None),
        (UUID(third.legal_source_id), 3, False, UUID(second.legal_source_id)),
    ]

    newest = _version(base, day=date(2025, 1, 1), suffix="Sonraki metin")
    fourth = upsert_legislation(connection, newest)
    assert fourth.status == "new_version"
    rows = connection.execute(
        "SELECT id, revision, is_current, superseded_by_id FROM legal_sources "
        "WHERE source_type = 'legislation' AND external_id = %s ORDER BY revision",
        (old.external_id,),
    ).fetchall()
    assert rows == [
        (UUID(first.legal_source_id), 1, False, UUID(second.legal_source_id)),
        (UUID(second.legal_source_id), 2, False, UUID(fourth.legal_source_id)),
        (UUID(third.legal_source_id), 3, False, UUID(second.legal_source_id)),
        (UUID(fourth.legal_source_id), 4, True, None),
    ]


def _article_lineage(connection, external_id: str):
    return connection.execute(
        "SELECT ls.id, ls.revision, ls.is_current, ls.superseded_by_id, "
        "ls.content_hash, ls.source_version, details.version_identity, details.version_date "
        "FROM legal_sources ls "
        "JOIN legislation_details details ON details.legal_source_id = ls.id "
        "WHERE ls.source_type = 'legislation' AND ls.external_id = %s "
        "ORDER BY ls.revision",
        (external_id,),
    ).fetchall()


def test_same_text_with_shifted_portal_date_stays_unchanged(connection):
    """5302 m.14: guncellemeTarihi kayınca aynı metin yeni sürüm sanılmamalı."""
    base = _record()
    first_date = replace(base, version_date=date(2023, 5, 22))
    shifted_date = replace(base, version_date=date(2024, 8, 20))
    first = upsert_legislation(connection, first_date)
    second = upsert_legislation(connection, shifted_date)

    assert first.status == "created"
    assert second.status == "unchanged"
    assert second.legal_source_id == first.legal_source_id
    rows = _article_lineage(connection, base.external_id)
    assert len(rows) == 1
    assert rows[0][2] is True
    assert rows[0][4] == base.content_hash
    assert rows[0][6] == f"2023-05-22:{base.content_hash}"
    assert rows[0][7] == date(2023, 5, 22)

    third = upsert_legislation(connection, first_date)
    assert third.status == "unchanged"
    assert third.legal_source_id == first.legal_source_id
    assert _article_lineage(connection, base.external_id) == rows


def test_historical_version_identity_is_not_reinserted(connection):
    """Eski sürüm tekrar gelince unique ihlali yerine unchanged."""
    base = _record()
    old = _version(base, day=date(2023, 5, 22), suffix="Eski metin")
    current = _version(base, day=date(2024, 8, 20), suffix="Güncel metin")
    first = upsert_legislation(connection, old)
    second = upsert_legislation(connection, current)
    before = _article_lineage(connection, old.external_id)

    again = upsert_legislation(connection, old)
    assert again.status == "unchanged"
    assert again.legal_source_id == first.legal_source_id
    assert _article_lineage(connection, old.external_id) == before
    assert before[0][2] is False
    assert before[1][0] == UUID(second.legal_source_id)
    assert before[1][2] is True


def test_corpus_5302_article_14_reingest_preserves_versions(connection):
    """Canlı 5302 m.14 satırlarını silmeden/ezmeden yeniden aktar."""
    before = connection.execute(
        "SELECT ls.id, ls.revision, ls.is_current, ls.superseded_by_id, "
        "ls.content_hash, ls.source_version, details.version_identity, details.version_date "
        "FROM legal_sources ls "
        "JOIN legislation_details details ON details.legal_source_id = ls.id "
        "WHERE details.law_no = %s AND details.article_no = %s "
        "AND details.legislation_type = %s "
        "ORDER BY ls.revision",
        ("5302", "14", "law"),
    ).fetchall()
    if not before:
        pytest.skip("5302 m.14 korpusta yok")

    archive = Path(__file__).resolve().parents[1] / "data" / "raw" / "mevzuat" / "mevzuat__kanun__5302__m.14.json"
    if archive.exists():
        record = LegislationRecord.from_json(json.loads(archive.read_text(encoding="utf-8")))
    else:
        current = connection.execute(
            "SELECT ls.raw_text, ls.content_hash, ls.title, details.law_name, "
            "details.article_title, details.official_gazette_no, details.official_gazette_date, "
            "ls.source_url "
            "FROM legal_sources ls "
            "JOIN legislation_details details ON details.legal_source_id = ls.id "
            "WHERE details.law_no = %s AND details.article_no = %s AND ls.is_current",
            ("5302", "14"),
        ).fetchone()
        record = replace(
            _record(),
            law_no="5302",
            article_no="14",
            law_name=current[3],
            article_title=current[4],
            title=current[2],
            raw_text=current[0],
            content_hash=current[1],
            external_id="mevzuat:kanun:5302:m.14",
            official_gazette_no=current[5],
            official_gazette_date=current[6],
            source_url=current[7],
            version_date=date(2023, 5, 22),
        )

    first = upsert_legislation(connection, record)
    assert first.status == "unchanged"
    shifted = replace(record, version_date=date(2024, 8, 20))
    second = upsert_legislation(connection, shifted)
    assert second.status == "unchanged"
    after = connection.execute(
        "SELECT ls.id, ls.revision, ls.is_current, ls.superseded_by_id, "
        "ls.content_hash, ls.source_version, details.version_identity, details.version_date "
        "FROM legal_sources ls "
        "JOIN legislation_details details ON details.legal_source_id = ls.id "
        "WHERE details.law_no = %s AND details.article_no = %s "
        "AND details.legislation_type = %s "
        "ORDER BY ls.revision",
        ("5302", "14", "law"),
    ).fetchall()
    assert after == before

    newer = replace(
        record,
        raw_text=record.raw_text + "\n\nYeni fıkra.",
        content_hash=content_hash(record.raw_text + "\n\nYeni fıkra."),
        version_date=date(2026, 1, 1),
    )
    created = upsert_legislation(connection, newer)
    assert created.status == "new_version"
    assert created.legal_source_id not in {str(row[0]) for row in before}
    preserved = connection.execute(
        "SELECT ls.id, ls.content_hash, ls.source_version, details.version_identity "
        "FROM legal_sources ls "
        "JOIN legislation_details details ON details.legal_source_id = ls.id "
        "WHERE ls.id = ANY(%s) "
        "ORDER BY ls.revision",
        ([row[0] for row in before],),
    ).fetchall()
    assert preserved == [(row[0], row[4], row[5], row[6]) for row in before]
    current_flags = connection.execute(
        "SELECT ls.id, ls.is_current FROM legal_sources ls WHERE ls.id = ANY(%s) ORDER BY ls.revision",
        ([row[0] for row in before],),
    ).fetchall()
    assert all(flag is False for _id, flag in current_flags)
