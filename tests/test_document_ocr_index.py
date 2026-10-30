"""OCR'ın belge indekslemeye bağlanması: gerçek RLS'li test veritabanında, işlem sonunda geri alınır."""

from __future__ import annotations

import os

import pytest

from api import document_indexing as indexing
from api import document_processing
from tests.test_document_indexing import _chunks, _derived, _office_doc, world as _world_fixture

world = _world_fixture

pytestmark = pytest.mark.skipif(
    not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured"
)

OCR_TEXT = "Bilirkişi raporu: kıdem tazminatı 340.000 TL olarak hesaplanmıştır. Davacı işçi çalışmıştır."


@pytest.fixture
def fake_ocr(monkeypatch):
    calls = []

    def read(data):
        calls.append(len(data))
        return [(1, OCR_TEXT)]

    monkeypatch.setattr(document_processing, "ocr_image_pages", read)
    return calls


def _metadata(connection, office_id):
    connection.execute("RESET ROLE")
    return connection.execute(
        "SELECT metadata FROM documents WHERE office_case_document_id = %s", (office_id,)
    ).fetchone()["metadata"]


def test_scan_is_indexed_with_ocr_and_marked_as_ocr(world, fake_ocr):
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, name="tarama.png", data=b"\x89PNG....")

    outcome = indexing.index_office_document(alice, office_id)

    assert outcome.status == "ready"
    assert fake_ocr == [8]
    derived = _derived(connection, office_id)
    assert derived["status"] == "ready"
    assert _metadata(connection, office_id)["ocr"] is True
    assert "340.000 TL" in " ".join(row["content"] for row in _chunks(connection, derived["id"]))


def test_non_ocr_document_is_not_marked(world):
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, name="notlar.txt", data="Davacı işçi çalışmıştır.".encode())

    assert indexing.index_office_document(alice, office_id).status == "ready"
    assert "ocr" not in _metadata(connection, office_id)


def test_question_time_path_defers_ocr_and_writes_nothing(world, fake_ocr):
    """Soru anındaki hızlı yol dakikalar sürebilecek OCR'ı çalıştırmaz, belgeyi 'işlenmedi' bırakır."""
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, name="tarama.png", data=b"\x89PNG....")

    outcome = indexing.index_office_document(alice, office_id, ocr_mode="defer")

    assert outcome.status == "needs_ocr"
    assert fake_ocr == []
    assert _derived(connection, office_id) is None  # hiçbir kayıt yazılmadı: "işlenmedi" kalır


def test_deferred_ocr_is_rescheduled_in_the_background(world, monkeypatch, fake_ocr):
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, name="tarama.png", data=b"\x89PNG....")
    scheduled = []
    monkeypatch.setattr(indexing, "schedule_index", lambda *args, **kwargs: scheduled.append((args, kwargs)))

    indexing._index_and_embed(alice, office_id, None, ocr_mode="defer")

    assert len(scheduled) == 1
    assert scheduled[0][0][:2] == (alice, office_id)


def test_ocr_unavailable_leaves_a_visible_reason(world, monkeypatch):
    from api.ocr import OcrUnavailable

    def boom(data):
        raise OcrUnavailable("Tesseract OCR kurulu değil.")

    monkeypatch.setattr(document_processing, "ocr_image_pages", boom)
    connection, alice, _, files, _ = world
    office_id = _office_doc(connection, alice, files, name="tarama.png", data=b"\x89PNG....")

    outcome = indexing.index_office_document(alice, office_id)

    assert outcome.status == "failed"
    assert "Tesseract OCR kurulu değil" in outcome.error
    assert _derived(connection, office_id)["status"] == "failed"


def test_coverage_counts_ocr_documents(world, fake_ocr):
    connection, alice, _, files, _ = world
    connection.execute("RESET ROLE")
    case_id = __import__("uuid").uuid4()
    connection.execute("INSERT INTO office_cases (id, owner_id, title) VALUES (%s, %s, 'T')", (case_id, alice))
    scan = _office_doc(connection, alice, files, name="tarama.png", data=b"\x89PNG....", case_id=case_id)
    text = _office_doc(
        connection, alice, files, name="notlar.txt", data="Davacı işçi çalışmıştır.".encode(), case_id=case_id
    )
    indexing.index_office_document(alice, scan)
    indexing.index_office_document(alice, text)

    scope = indexing.case_document_coverage(alice, case_id)

    assert (scope["total"], scope["ready"], scope["ocr"]) == (2, 2, 1)


def test_inflight_ocr_job_is_not_scheduled_twice(monkeypatch):
    started = []
    monkeypatch.setattr(indexing._executor, "submit", lambda fn, *args: started.append((fn, args)))
    owner, document = __import__("uuid").uuid4(), __import__("uuid").uuid4()
    try:
        indexing.schedule_index(owner, document)
        indexing.schedule_index(owner, document)  # süren iş: ikinci kez eklenmez
        assert len(started) == 1
    finally:
        indexing._inflight.discard((owner, document))
