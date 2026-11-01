"""Büro belgesi indeksleme: gerçek RLS'li test veritabanında, işlem sonunda geri alınır."""

from __future__ import annotations

import contextlib
import io
import os
import zipfile
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from api import document_indexing as indexing
from api.document_processing import DocumentProcessingError

pytestmark = pytest.mark.skipif(
    not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured"
)

_UDF_XML = (
    "<template><content><![CDATA[Davacı işçi kıdem tazminatı talep etmektedir. "
    "İş sözleşmesi haklı nedenle feshedilmiştir.]]></content></template>"
)


def _udf(xml: str = _UDF_XML) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("content.xml", xml)
    return buffer.getvalue()


@pytest.fixture
def world(monkeypatch):
    connection = psycopg.connect(os.environ["NHR_TEST_DATABASE_URL"], row_factory=dict_row)
    alice, bob = uuid4(), uuid4()
    files: dict[str, bytes] = {}
    current = {"user": alice}
    try:
        for user in (alice, bob):
            connection.execute(
                "INSERT INTO users (id, email, password_hash, full_name) VALUES (%s, %s, %s, %s)",
                (user, f"{user}@test.invalid", "not-a-password", "Test"),
            )

        @contextlib.contextmanager
        def as_user(user_id: str):
            # Üretimdeki `authenticated_database_connection` gibi: runtime rolü + RLS kimliği.
            connection.execute("RESET ROLE")
            connection.execute("SET LOCAL ROLE nhr_runtime")
            connection.execute("SELECT set_config('app.user_id', %s, true)", (user_id,))
            yield connection

        def fake_read(owner_id, storage_path):
            if storage_path not in files:
                raise OSError("yok")
            return files[storage_path]

        monkeypatch.setattr(indexing, "authenticated_database_connection", as_user)
        monkeypatch.setattr(indexing, "_read_source", fake_read)
        yield connection, alice, bob, files, current
    finally:
        connection.rollback()
        connection.close()


def _office_doc(connection, owner, files, *, name="karar.udf", data=None, case_id=None):
    document_id = uuid4()
    path = f"{owner}/{document_id}"
    if data is not None:
        files[path] = data
    connection.execute("RESET ROLE")
    connection.execute(
        "INSERT INTO office_case_documents (id, owner_id, case_id, file_name, storage_path, size_bytes) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (document_id, owner, case_id, name, path, len(data or b"")),
    )
    return document_id


def _derived(connection, office_id):
    connection.execute("RESET ROLE")
    return connection.execute(
        "SELECT id, project_id, uploaded_by, status, processing_error, checksum_sha256 "
        "FROM documents WHERE office_case_document_id = %s",
        (office_id,),
    ).fetchone()


def _chunks(connection, document_id):
    connection.execute("RESET ROLE")
    return connection.execute(
        "SELECT content FROM document_chunks WHERE document_id = %s ORDER BY chunk_index", (document_id,)
    ).fetchall()


def test_udf_is_indexed_privately_for_its_owner(world):
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, data=_udf())

    outcome = indexing.index_office_document(alice, office_id)

    derived = _derived(connection, office_id)
    assert outcome.status == "ready" and outcome.chunk_count >= 1
    assert derived["status"] == "ready" and derived["processing_error"] is None
    assert derived["project_id"] is None and derived["uploaded_by"] == alice
    assert "kıdem tazminatı" in _chunks(connection, derived["id"])[0]["content"]


@pytest.mark.parametrize("source,expected", [("uyap", "ready"), ("manual", "failed")])
def test_misnamed_xml_is_recovered_only_for_uyap_documents(world, source, expected):
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, name="yanlis.pdf",
                           data=b'<?xml version="1.0"?><dava><konu>Ornek konu metni</konu></dava>')
    connection.execute("UPDATE office_case_documents SET source=%s WHERE id=%s", (source, office_id))
    outcome = indexing.index_office_document(alice, office_id)
    assert outcome.status == expected
    derived = _derived(connection, office_id)
    if expected == "ready":
        assert "Ornek konu metni" in _chunks(connection, derived["id"])[0]["content"]
        assert connection.execute("SELECT mime_type FROM documents WHERE id=%s", (derived["id"],)).fetchone()["mime_type"] == "application/xml"


def test_old_parser_cache_is_reprocessed_even_when_source_checksum_matches(world):
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, data=_udf())
    assert indexing.index_office_document(alice, office_id).status == "ready"
    connection.execute("RESET ROLE")
    connection.execute("UPDATE documents SET metadata='{}'::jsonb WHERE office_case_document_id=%s", (office_id,))
    assert indexing.index_office_document(alice, office_id).status == "ready"
    assert indexing.index_office_document(alice, office_id).status == "unchanged"


def test_unchanged_content_is_not_reprocessed_and_changed_content_replaces_chunks(world):
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, data=_udf())
    indexing.index_office_document(alice, office_id)
    first_id = _derived(connection, office_id)["id"]

    assert indexing.index_office_document(alice, office_id).status == "unchanged"

    files[f"{alice}/{office_id}"] = _udf("<t><content><![CDATA[Tamamen farklı yeni metin içeriği.]]></content></t>")
    assert indexing.index_office_document(alice, office_id).status == "ready"
    derived = _derived(connection, office_id)
    texts = " ".join(row["content"] for row in _chunks(connection, derived["id"]))
    assert derived["id"] == first_id  # aynı satır güncellendi, ikinci kayıt yok
    assert "yeni metin" in texts and "kıdem" not in texts


def test_force_reindexes_even_when_content_is_identical(world):
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, data=_udf())
    indexing.index_office_document(alice, office_id)

    assert indexing.index_office_document(alice, office_id, force=True).status == "ready"


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("tarama.tif", b"II*\x00fake", "OCR"),
        ("bozuk.udf", b"not a zip", "UDF"),
        ("sahte.pdf", b"plain", "PDF"),
    ],
)
def test_unreadable_documents_are_recorded_as_failed_with_a_reason_never_ready(world, name, data, expected):
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, name=name, data=data)

    outcome = indexing.index_office_document(alice, office_id)

    derived = _derived(connection, office_id)
    assert outcome.status == "failed" and expected in outcome.error
    assert derived["status"] == "failed" and expected in derived["processing_error"]
    assert _chunks(connection, derived["id"]) == []


def test_missing_file_is_failed_not_silently_ready(world):
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, data=None)

    assert indexing.index_office_document(alice, office_id).status == "failed"
    assert "bulunamadı" in _derived(connection, office_id)["processing_error"]


def test_failed_then_fixed_document_becomes_ready_and_drops_the_error(world):
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, name="karar.udf", data=b"not a zip")
    assert indexing.index_office_document(alice, office_id).status == "failed"

    files[f"{alice}/{office_id}"] = _udf()
    assert indexing.index_office_document(alice, office_id).status == "ready"
    assert _derived(connection, office_id)["processing_error"] is None


def test_another_user_cannot_index_or_see_the_document(world):
    connection, alice, bob, files, _ = world
    office_id = _office_doc(connection, alice, files, data=_udf())

    assert indexing.index_office_document(bob, office_id).status == "missing"
    assert _derived(connection, office_id) is None


def test_derived_document_cannot_point_at_another_users_office_document(world):
    connection, alice, bob, files, _ = world
    office_id = _office_doc(connection, alice, files, data=_udf())
    connection.execute("RESET ROLE")
    connection.execute("SET LOCAL ROLE nhr_runtime")
    connection.execute("SELECT set_config('app.user_id', %s, true)", (str(bob),))

    with pytest.raises(psycopg.errors.ForeignKeyViolation), connection.transaction():
        connection.execute(
            "INSERT INTO documents (id, project_id, uploaded_by, file_name, status, office_case_document_id) "
            "VALUES (%s, NULL, %s, 'x.udf', 'ready', %s)",
            (uuid4(), bob, office_id),
        )


def test_deleting_the_source_removes_derived_text(world):
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, data=_udf())
    indexing.index_office_document(alice, office_id)
    derived_id = _derived(connection, office_id)["id"]
    assert _chunks(connection, derived_id)

    connection.execute("RESET ROLE")
    connection.execute("DELETE FROM office_case_documents WHERE id = %s", (office_id,))

    assert _derived(connection, office_id) is None
    assert _chunks(connection, derived_id) == []


def test_sweep_indexes_only_unattempted_documents_in_scope_and_does_not_retry_failures(world, monkeypatch):
    connection, alice, bob, files, _ = world
    case_id = uuid4()
    connection.execute(
        "INSERT INTO office_cases (id, owner_id, title) VALUES (%s, %s, 'Dava')", (case_id, alice)
    )
    in_case = _office_doc(connection, alice, files, data=_udf(), case_id=case_id)
    outside = _office_doc(connection, alice, files, data=_udf())
    broken = _office_doc(connection, alice, files, name="b.udf", data=b"not a zip", case_id=case_id)
    foreign = _office_doc(connection, bob, files, data=_udf())
    monkeypatch.setattr(indexing, "embed_office_document", lambda *a, **k: 0)

    assert indexing.sweep_unindexed(alice, case_id=case_id) == 2
    assert _derived(connection, in_case)["status"] == "ready"
    assert _derived(connection, broken)["status"] == "failed"
    assert _derived(connection, outside) is None  # kapsam dışı
    assert _derived(connection, foreign) is None  # başka kullanıcı

    # Başarısız belge tekrar denenmez; kapsam dışı olan genel taramada işlenir.
    assert indexing.sweep_unindexed(alice, case_id=case_id) == 0
    assert indexing.sweep_unindexed(alice) == 1
    assert _derived(connection, outside)["status"] == "ready"


def test_sweep_respects_the_time_budget(world, monkeypatch):
    connection, alice, _, files, _ = world
    for _ in range(3):
        _office_doc(connection, alice, files, data=_udf())
    monkeypatch.setattr(indexing, "embed_office_document", lambda *a, **k: 0)

    assert indexing.sweep_unindexed(alice, budget_seconds=0) == 0


def test_processing_failures_with_unexpected_exceptions_are_recorded_generically(world, monkeypatch):
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, data=_udf())

    def boom(*args, **kwargs):
        raise RuntimeError("iç ayrıntı /secret/path")

    monkeypatch.setattr(indexing, "process_document", boom)

    outcome = indexing.index_office_document(alice, office_id)

    assert outcome.status == "failed"
    assert "secret" not in outcome.error  # iç ayrıntı kullanıcıya/DB'ye sızmaz
    assert _derived(connection, office_id)["processing_error"] == "Belge işlenemedi."


def test_processing_error_type_is_user_facing():
    assert issubclass(DocumentProcessingError, ValueError)
