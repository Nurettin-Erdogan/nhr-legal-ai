"""Klasör sınırları, kategori sayımları ve gerçek PostgreSQL üzerinde salt-okunur sorgu testi."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from api.document_organization import folder_key, organized_documents, parse_folder


@pytest.mark.parametrize("value", ['null', '{}', '["uyap"]', '["uyap", {}, null]', '["other", null, null]', 'invalid'])
def test_invalid_folder_rejected(value):
    with pytest.raises(HTTPException) as error:
        parse_folder(value)
    assert error.value.status_code == 422


def test_organization_queries_keep_owner_filters_and_use_bound_parameters():
    owner = uuid4()
    evil_birim = "Ankara'; DROP TABLE office_case_documents; --"
    calls = []

    class Result:
        def fetchall(self):
            return []

    class Connection:
        def execute(self, statement, params):
            calls.append((statement, params))
            return Result()

    result = organized_documents(
        Connection(), owner, q="Ek_%", source="uyap", category="decision",
        folder=folder_key("uyap", "2024/100", evil_birim), order="date_asc", offset=50, limit=50,
    )
    assert result["total"] == 0
    assert len(calls) == 2
    for statement, params in calls:
        assert "owner_id = %s AND deleted_at IS NULL" in statement
        assert params[0] == owner
        assert params[1:5] == ("%Ek\\_\\%%",) * 4
        assert evil_birim not in statement
    assert calls[1][1][-5:] == ("uyap", "2024/100", evil_birim, 50, 50)
    assert "doc_date ASC NULLS LAST" in calls[1][0]


def verify_postgres_organization(connection):
    """Gerçek tabloya erişmeden JSON fixture üzerinden aynı SELECT'leri çalıştırır."""
    owner, other = uuid4(), uuid4()
    now = datetime.now(timezone.utc).isoformat()

    def doc(kind, *, birim="Ankara 1. İcra Dairesi", user=owner, deleted=None, source="uyap", day="2024-09-20"):
        return {
            "id": str(uuid4()), "file_name": "8237f5c406b3-Ek_1.odt", "storage_path": "fixture",
            "size_bytes": 100, "source": source, "uyap_file_no": "2024/100", "uyap_birim": birim,
            "doc_type": kind, "doc_date": day, "case_id": None, "created_at": now,
            "owner_id": str(user), "deleted_at": deleted,
        }

    data = [doc("Ödeme İcra Emri") for _ in range(54)] + [doc("Takip Talebi")] + [
        doc("İstinaf Kararı", day="2024-10-01"), doc("Vekâlet Pulu Makbuzu"),
        doc(None), doc("Dilekçe", birim="Ankara 2. İcra Dairesi"),
        doc("Karar", user=other), doc("Karar", deleted=now),
        doc("Dilekçe", source="manual", day=None),
    ]

    class FixtureConnection:
        def execute(self, statement, params):
            statement = statement.replace("FROM office_case_documents", """FROM jsonb_to_recordset(%s) AS office_case_documents(
                id uuid, file_name text, storage_path text, size_bytes bigint, source text,
                uyap_file_no text, uyap_birim text, doc_type text, doc_date date, case_id uuid,
                created_at timestamptz, owner_id uuid, deleted_at timestamptz)""")
            return connection.execute(statement, (Jsonb(data), *params))

    def search(**overrides):
        options = dict(q="", source="uyap", category="", folder="", order="recent", offset=0, limit=50)
        options.update(overrides)
        return organized_documents(FixtureConnection(), owner, **options)

    result = search()
    assert result["total"] == 59 and len(result["rows"]) == 50
    assert sorted(item["count"] for item in result["folders"]) == [1, 58]
    assert sum(item["count"] for item in result["categories"]) == 59
    assert len(search(offset=50)["rows"]) == 9
    second_folder = folder_key("uyap", "2024/100", "Ankara 2. İcra Dairesi")
    isolated = search(folder=second_folder)
    assert isolated["total"] == 1 and isolated["rows"][0]["category"] == "petition"
    assert search(category="decision")["rows"][0]["doc_type"] == "İstinaf Kararı"
    assert search(category="financial")["rows"][0]["doc_type"] == "Vekâlet Pulu Makbuzu"
    assert search(category="attachment")["total"] == 1
    assert search(category="enforcement")["total"] == 55
    summary = search(category="enforcement", summary_only=True)
    assert summary["rows"] == [] and summary["total"] == 55
    assert sorted(item["matching_count"] for item in summary["folders"]) == [0, 55]
    assert search(order="date_desc")["rows"][0]["doc_type"] == "İstinaf Kararı"
    assert search(source="manual")["total"] == 1
    assert search(q="olmayan")["total"] == 0
    assert search(source="all")["total"] == 60


@pytest.mark.skipif(not os.getenv("NHR_TEST_DATABASE_URL"), reason="NHR_TEST_DATABASE_URL tanımlı değil")
def test_postgres_categories_folders_pagination_and_owner_scope():
    with psycopg.connect(os.environ["NHR_TEST_DATABASE_URL"], row_factory=dict_row) as connection:
        verify_postgres_organization(connection)
