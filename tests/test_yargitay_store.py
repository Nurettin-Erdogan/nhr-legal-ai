"""Aktarım testleri.

Çalışan bir veritabanı gerektirir; `NHR_TEST_DATABASE_URL` tanımlı değilse
testler atlanır. Tüm yazımlar test sonunda geri alınır.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

psycopg = pytest.importorskip("psycopg")

from ingestion.yargitay.models import CourtDecision
from ingestion.yargitay.parser import content_hash
from ingestion.yargitay.store import upsert_decision

DATABASE_URL = os.getenv("NHR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="NHR_TEST_DATABASE_URL tanımlı değil; veritabanı testleri atlandı.",
)

BODY = "\n\n".join(
    [
        "Davacı vekili dava dilekçesinde kıdem tazminatı talep etmiştir.",
        "Mahkemece toplanan deliller değerlendirilmiştir.",
        "Sonuç olarak hükmün bozulmasına karar verilmiştir.",
    ]
)


def _decision(*, raw_text: str = BODY) -> CourtDecision:
    return CourtDecision(
        court_name="Yargıtay",
        chamber="9. Hukuk Dairesi",
        docket_no="2019/999001",
        decision_no="2021/999002",
        decision_date=date(2021, 5, 12),
        title="Yargıtay 9. Hukuk Dairesi, E. 2019/999001, K. 2021/999002 (12.05.2021)",
        raw_text=raw_text,
        external_id="yargitay/9-hukuk-dairesi/2019-999001/2021-999002",
        content_hash=content_hash(raw_text),
        source_url="https://karararama.yargitay.gov.tr/",
        metadata={"header_info": "test"},
    )


@pytest.fixture
def connection():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.transaction():
            yield conn
            raise psycopg.Rollback


def _fetch_one(conn, query: str, params: tuple):
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchone()


def test_upsert_writes_source_details_and_chunks(connection):
    result = upsert_decision(connection, _decision())

    assert result.status == "created"
    assert result.chunk_count >= 1

    with connection.cursor() as cursor:
        # Kaynak ve alt tür kaydının birlikte yazıldığını, ertelenmiş trigger'ı
        # erkene alarak doğrular.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    source = _fetch_one(
        connection,
        "SELECT source_type, ingest_status, published_at, authority"
        " FROM legal_sources WHERE id = %s",
        (result.legal_source_id,),
    )
    assert source == ("court_decision", "ready", date(2021, 5, 12), "Yargıtay")

    details = _fetch_one(
        connection,
        "SELECT court_name, chamber, docket_no, decision_no, decision_date"
        " FROM court_decision_details WHERE legal_source_id = %s",
        (result.legal_source_id,),
    )
    assert details == ("Yargıtay", "9. Hukuk Dairesi", "2019/999001", "2021/999002", date(2021, 5, 12))

    chunk_count, min_index = _fetch_one(
        connection,
        "SELECT count(*), min(chunk_index) FROM legal_chunks WHERE legal_source_id = %s",
        (result.legal_source_id,),
    )
    assert chunk_count == result.chunk_count
    assert min_index == 0


def test_reingesting_same_decision_is_idempotent(connection):
    first = upsert_decision(connection, _decision())
    second = upsert_decision(connection, _decision())

    assert second.status == "unchanged"
    assert second.legal_source_id == first.legal_source_id

    source_count, = _fetch_one(
        connection,
        "SELECT count(*) FROM legal_sources WHERE external_id = %s",
        (first.external_id,),
    )
    chunk_count, = _fetch_one(
        connection,
        "SELECT count(*) FROM legal_chunks WHERE legal_source_id = %s",
        (first.legal_source_id,),
    )

    assert source_count == 1
    assert chunk_count == first.chunk_count


def test_changed_text_updates_source_and_rebuilds_chunks(connection):
    first = upsert_decision(connection, _decision())
    updated_text = BODY + "\n\nEk gerekçe paragrafı eklenmiştir."

    second = upsert_decision(connection, _decision(raw_text=updated_text))

    assert second.status == "updated"
    assert second.legal_source_id == first.legal_source_id

    stored_hash, = _fetch_one(
        connection,
        "SELECT content_hash FROM legal_sources WHERE id = %s",
        (first.legal_source_id,),
    )
    assert stored_hash == content_hash(updated_text)


def test_chunks_are_searchable_via_turkish_full_text_index(connection):
    result = upsert_decision(connection, _decision())

    match_count, = _fetch_one(
        connection,
        "SELECT count(*) FROM legal_chunks"
        " WHERE legal_source_id = %s"
        "   AND search_vector @@ plainto_tsquery('turkish', %s)",
        (result.legal_source_id, "kıdem tazminatı"),
    )

    assert match_count >= 1
