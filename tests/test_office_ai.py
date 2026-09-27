"""Büro AI akışlarının kod tarafı doğrulamaları. Model ve veritabanı gerekmez."""

from __future__ import annotations

from uuid import uuid4
import asyncio

import pytest
from fastapi import HTTPException

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import office_ai
from api.ai.rag import RAGContext
from api.auth.routes import current_user_id
from api.office_ai import router, unsupported_references

USER_ID = uuid4()


def _context(**overrides) -> RAGContext:
    values = dict(
        chunk_id=uuid4(),
        source_id=uuid4(),
        source_type="legislation",
        title="Türk Borçlar Kanunu",
        source_url=None,
        authority=None,
        court_name=None,
        chamber=None,
        docket_no=None,
        decision_no=None,
        decision_date=None,
        law_name="Türk Borçlar Kanunu",
        law_no="6098",
        article_no="344",
        article_title=None,
        content="Kira bedelinin artışı yenileme dönemindeki TÜFE ortalamasını aşamaz.",
        rank=1.0,
    )
    values.update(overrides)
    return RAGContext(**values)


def test_references_found_in_sources_are_accepted():
    text = "6098 sayılı Kanun m. 344 uyarınca artış sınırlıdır."

    assert unsupported_references(text, [_context()]) == []


def test_invented_law_and_decision_numbers_are_flagged():
    text = "5237 sayılı Kanun ve Yargıtay 9. HD, 2019/1234 E. sayılı karar uyarınca..."

    missing = unsupported_references(text, [_context()])

    assert "5237 sayılı" in missing
    assert "2019/1234" in missing


def test_numbers_given_by_the_user_are_not_flagged():
    text = "Dosya 2024/567 esas sayılı olup 4857 sayılı İş Kanunu uygulanır."

    missing = unsupported_references(text, [], given_text="Esas: 2024/567, 4857 sayılı İş Kanunu")

    assert missing == []


def test_sources_footer_marks_unverified_third_party_sources():
    footer = office_ai._sources_footer([_context(), _context(verification="third_party")])

    assert "[K1]" in footer and "[K2]" in footer
    assert footer.count("(doğrulanmadı)") == 1


def test_unknown_module_is_rejected_and_login_required():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.post("/api/office-ai/run", json={"module": "draft", "prompt": "merhaba dünya"}).status_code == 401

    app.dependency_overrides[current_user_id] = lambda: USER_ID
    response = client.post("/api/office-ai/run", json={"module": "research", "prompt": "merhaba dünya"})

    assert response.status_code == 400


def test_ocr_reports_missing_engine(monkeypatch):
    monkeypatch.setattr(office_ai, "_ocr_available", lambda: (False, "Tesseract OCR kurulu değil"))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_user_id] = lambda: USER_ID

    response = TestClient(app).post("/api/office-ai/ocr", json={"images": ["x" * 200]})

    assert response.status_code == 503
    assert "Tesseract" in response.json()["detail"]


@pytest.mark.parametrize("contexts", [[], [_context(verification="third_party")]])
def test_no_generation_without_verified_evidence(monkeypatch, contexts):
    async def retrieve(*args):
        return contexts
    async def generate(*args):
        pytest.fail("Unverified sources must not reach generation")
    monkeypatch.setattr(office_ai, "_retrieve_sources", retrieve)
    monkeypatch.setattr(office_ai, "_generate", generate)
    with pytest.raises(HTTPException) as error:
        asyncio.run(office_ai._run_module("Taslak", "system", "kira artışı", USER_ID, retrieval_query="kira artışı"))
    assert error.value.status_code == 422


@pytest.mark.parametrize("output", [
    "Kiracı her durumda tahliye edilir. [K1]",
    "5237 sayılı Kanun gereği tahliye edilir. [K1]",
    "Kira bedelinin artışı yenileme dönemindeki TÜFE ortalamasını aşamaz. [K99]",
])
def test_unsupported_output_is_blocked_not_only_warned(monkeypatch, output):
    async def retrieve(*args):
        return [_context()]
    async def generate(*args):
        return output, "test"
    monkeypatch.setattr(office_ai, "_retrieve_sources", retrieve)
    monkeypatch.setattr(office_ai, "_generate", generate)
    with pytest.raises(HTTPException) as error:
        asyncio.run(office_ai._run_module("Taslak", "system", "kira artışı", USER_ID, retrieval_query="kira artışı"))
    assert error.value.status_code == 422
    assert output not in error.value.detail


def test_supported_quote_passes_the_shared_evidence_gate(monkeypatch):
    context = _context()
    async def retrieve(*args):
        return [context]
    async def generate(*args):
        return context.content + " [K1]", "test-model"
    monkeypatch.setattr(office_ai, "_retrieve_sources", retrieve)
    monkeypatch.setattr(office_ai, "_generate", generate)
    result = asyncio.run(office_ai._run_module("Analiz", "system", "kira artışı", USER_ID, retrieval_query="kira artışı"))
    assert context.content in result["content"]
    assert result["sources"][0]["verification"] == "official"
    assert result["unverified_references"] == []
