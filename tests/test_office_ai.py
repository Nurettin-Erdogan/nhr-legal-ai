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


# --- Taslak: iskelet kodla, olgular doğrulanmış, dayanaklar kodla listelenir ------------------------------------


def _patch(monkeypatch, *, contexts, output=None, error=None):
    async def retrieve(*args, **kwargs):
        return contexts

    async def generate(*args):
        if error:
            raise error
        return output, "test-model"

    monkeypatch.setattr(office_ai, "_retrieve_sources", retrieve)
    monkeypatch.setattr(office_ai, "_generate", generate)


def _draft(**overrides):
    values = dict(doc_type="dilekce", title=None, parties=["Davacı Ahmet Örnek", "Davalı ABC Ltd. Şti."], subject="Kıdem ve ihbar tazminatı talebi", details="Müvekkil 8 yıl 1 ay çalıştı ve 340.000 TL kıdem tazminatı hesaplandı.", user_id=USER_ID)
    values.update(overrides)
    return asyncio.run(office_ai._draft(values.pop("doc_type"), values.pop("title"), values.pop("parties"), values.pop("subject"), values.pop("details"), values.pop("user_id")))


def test_a_draft_is_produced_even_when_no_verified_source_exists_and_says_so(monkeypatch):
    _patch(monkeypatch, contexts=[_context(verification="third_party")], output="1. Müvekkil 8 yıl 1 ay çalışmıştır.")
    result = _draft()
    assert "Korpusta bu konuyla eşleşen doğrulanmış kaynak bulunamadı" in result["content"]
    assert "6098" not in result["content"] and result["sources"] == []  # doğrulanmamış kaynak asla listelenmez
    assert "Müvekkil 8 yıl 1 ay çalışmıştır." in result["content"]


def test_fabricated_model_facts_never_reach_the_document(monkeypatch):
    _patch(monkeypatch, contexts=[], output="1. Davalı 999.999 TL ödemiştir.\n2. 5237 sayılı Kanun gereği hapis cezası verilir.\n3. Yargıtay 9. HD 2019/1234 E. kararı uyarınca kabul edilir.")
    result = _draft()
    for invented in ("999.999", "5237", "2019/1234", "hapis"):
        assert invented not in result["content"]
    assert "340.000 TL" in result["content"]  # kullanıcının kendi olguları kullanıldı
    assert "sizin yazdığınız bilgilerle oluşturuldu" in result["content"]


def test_a_model_failure_still_yields_a_draft_from_the_users_own_facts(monkeypatch):
    _patch(monkeypatch, contexts=[], error=HTTPException(status_code=502, detail="Ollama yanıtı token sınırında kesildi"))
    result = _draft()
    assert "**AÇIKLAMALAR:**" in result["content"] and "8 yıl 1 ay" in result["content"] and result["model"] is None


def test_supported_model_paragraphs_are_kept_and_renumbered(monkeypatch):
    _patch(monkeypatch, contexts=[], output="1. Müvekkil 8 yıl 1 ay çalışmıştır.\n2. Müvekkil için 340.000 TL kıdem tazminatı hesaplanmıştır.\n3. Davalı 12.345 TL borçludur.")
    result = _draft()
    content = result["content"]
    assert "1. Müvekkil 8 yıl 1 ay çalışmıştır." in content and "2. Müvekkil için 340.000 TL" in content
    assert "12.345" not in content and result["model"] == "test-model"
    assert "sizin yazdığınız bilgilerle oluşturuldu" not in content


def test_verified_statutes_and_decisions_are_listed_by_code_not_by_the_model(monkeypatch):
    decision = _context(source_type="court_decision", law_name=None, law_no=None, article_no=None, court_name="Yargıtay", chamber="9. Hukuk Dairesi", docket_no="2025/412", decision_no="2026/118")
    other = _context(source_type="other", law_name=None, law_no=None, article_no=None, title="Sayıştay ilamı")
    _patch(monkeypatch, contexts=[_context(), _context(), decision, other], output="1. Müvekkil 8 yıl 1 ay çalışmıştır.")
    result = _draft()
    assert result["content"].count("Türk Borçlar Kanunu (6098) m. 344") == 1  # tekrar edilmez
    assert "Yargıtay 9. Hukuk Dairesi, E. 2025/412, K. 2026/118" in result["content"]
    assert "Sayıştay" not in result["content"]
    assert [item["verification"] for item in result["sources"]] == ["official", "official"]


@pytest.mark.parametrize("doc_type,marker", [("dilekce", "SONUÇ VE İSTEM"), ("ihtarname", "İHTAR:"), ("sozlesme", "MADDE 7 – Uyuşmazlık"), ("diger", "SONUÇ VE İSTEM")])
def test_every_document_type_has_its_skeleton_and_unfilled_gaps(monkeypatch, doc_type, marker):
    _patch(monkeypatch, contexts=[], output="1. Müvekkil 8 yıl 1 ay çalışmıştır.")
    content = _draft(doc_type=doc_type, parties=[])["content"]
    assert marker in content and "[…]" in content and "Taslaktır" in content


# --- Analiz ve risk -------------------------------------------------------------------------------------------


def test_document_analysis_summarises_each_marked_document_and_lists_sources_by_code(monkeypatch):
    async def generate(system, prompt):
        return "- Kira bedeli 10.000 TL olarak belirlenmiştir."

    from api import office_analysis

    text = "=== BELGE 1: Kira A ===\nKira bedeli 10.000 TL, süre 1 yıl.\n=== BELGE 2: Kira B ===\nKira bedeli 12.000 TL, süre 2 yıl."
    markdown, sources = asyncio.run(office_analysis.analyze(text, generate, [_context(), _context(verification="third_party")]))
    assert "## 1. Kira A" in markdown and "## 2. Kira B" in markdown
    assert "Kira bedeli 10.000 TL olarak belirlenmiştir." in markdown  # belgeyle doğrulanan madde
    assert "12.000 TL" in markdown and "Belgede geçen olgular" in markdown  # B belgesinin olgusu; uydurma 10.000 B'de elenir
    assert "Hukuki değerlendirme içermez" in markdown and "Türk Borçlar Kanunu (6098) m. 344" in markdown
    assert len(sources) == 1  # üçüncü taraf listelenmez


def test_risk_analysis_never_predicts_outcomes_and_reports_sources(monkeypatch):
    from types import SimpleNamespace

    citation = SimpleNamespace(marker="K1", reference="İŞ KANUNU (4857) m. 41", source_url=None, verification="official", source_type="legislation")

    async def answer(user_id, question, conversation_id):
        return SimpleNamespace(answer=f"Cevap: {question} [K1]", grounded=True, citations=[citation], conversation_id=None)

    monkeypatch.setattr(office_ai, "_deep_answer", answer)
    result = asyncio.run(office_ai._risk("İşçiye fazla mesai ücreti ödenmedi, puantaj var, dava açılırsa riskler neler?", USER_ID))
    assert "Dava sonucu tahmini yapılmaz" in result["content"] and "Risk analizi" in result["content"]
    assert result["sources"] and result["sources"][0]["reference"] == "İŞ KANUNU (4857) m. 41"
