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
    # Doğrulama rozeti yazılmaz (AGENTS.md, 2026-10-18): ne ✓ ne olumsuz ibare.
    assert "✓" not in footer and "Resmî metin" not in footer and "doğrulanmadı" not in footer


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


def _patch(monkeypatch, *, contexts, output=None, error=None, hints=(), reject=()):
    async def retrieve(*args, **kwargs):
        return contexts

    async def generate(system, prompt):
        if error:
            raise error
        if "denetçisisin" in system:  # model denetimi: `reject` içindeki sözcüğü taşıyan paragrafı reddeder
            import json

            items = json.loads(prompt)["MADDELER"]
            return json.dumps({"results": [not any(word in item for word in reject) for item in items]}), "test-model"
        return output, "test-model"

    monkeypatch.setattr(office_ai, "_retrieve_sources", retrieve)
    monkeypatch.setattr(office_ai, "_generate", generate)
    monkeypatch.setattr(office_ai, "_statute_hints", lambda text: list(hints))


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


def test_draft_retains_late_facts_when_model_omits_them(monkeypatch):
    _patch(monkeypatch, contexts=[], output="1. Müvekkil 8 yıl 1 ay çalışmıştır.")
    details = "Müvekkil 8 yıl 1 ay çalışmıştır. " + "İşyeri teslim tutanağı düzenlendi. " * 65 + "Hosting ücreti kapsam dışıdır."
    result = _draft(details=details)
    assert "Hosting ücreti kapsam dışıdır." in result["content"]
    assert "Kullanıcının verdiği açıklama:" in result["content"]


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


def test_role_prefixes_are_not_printed_twice_and_parties_land_in_their_own_rows(monkeypatch):
    """Canlıda "DAVACI: Davacı: Ayşe Demir" çıkıyordu; taraflar ters sırada yazılsa da doğru satıra gider."""
    _patch(monkeypatch, contexts=[], output="1. Müvekkil 8 yıl 1 ay çalışmıştır.")
    content = _draft(parties=["Davalı: Mehmet Kaya", "Davacı: Ayşe Demir"])["content"]
    assert "**DAVACI:** Ayşe Demir" in content and "**DAVALI:** Mehmet Kaya" in content
    plain = _draft(parties=["Davacı Ahmet Örnek", "Davalı ABC Ltd. Şti."])["content"]
    assert "**DAVACI:** Ahmet Örnek" in plain and "**DAVALI:** ABC Ltd. Şti." in plain
    unlabelled = _draft(parties=["Ayşe Demir", "Mehmet Kaya"])["content"]
    assert "**DAVACI:** Ayşe Demir" in unlabelled and "**DAVALI:** Mehmet Kaya" in unlabelled


def test_a_paragraph_rejected_by_the_model_checker_never_reaches_the_document(monkeypatch):
    _patch(monkeypatch, contexts=[], output="1. Müvekkil 8 yıl 1 ay çalışmıştır.\n2. Müvekkil için 340.000 TL kıdem tazminatı hesaplanmıştır.", reject=("340.000",))
    content = _draft()["content"]
    assert "1. Müvekkil 8 yıl 1 ay çalışmıştır." in content and "2. Müvekkil için 340.000 TL" not in content


def test_an_invented_sentence_is_cut_out_of_an_otherwise_supported_paragraph(monkeypatch):
    """Canlıda görüldü: doğru cümlenin yanına eklenen uydurma cümle paragrafla birlikte geçiyordu."""
    output = "1. Müvekkil 8 yıl 1 ay çalışmıştır. Bu süre işyerindeki yetersiz denetimin sonucu oluşmuştur."
    _patch(monkeypatch, contexts=[], output=output)
    content = _draft()["content"]
    assert "1. Müvekkil 8 yıl 1 ay çalışmıştır." in content and "yetersiz denetimin" not in content


def test_the_model_is_not_asked_to_write_facts_when_none_were_given(monkeypatch):
    """Yalnız konu satırıyla model "davalı da talepte bulunmaktadır" gibi cümleler uyduruyordu: olgu yoksa model çağrılmaz."""
    calls = []

    async def generate(system, prompt):
        calls.append(system)
        return "1. Davalı firma da tahsilat talebinde bulunmaktadır.", "test-model"

    _patch(monkeypatch, contexts=[])
    monkeypatch.setattr(office_ai, "_generate", generate)
    result = _draft(details=None, subject="Kıdem ve ihbar tazminatı ile fazla mesai alacağının tahsili")
    assert calls == [] and "tahsilat talebinde" not in result["content"]
    assert "Olgu verilmediği için açıklamalar bölümü boş bırakıldı" in result["content"] and result["model"] is None


def test_without_facts_the_subject_opens_the_explanations_instead_of_an_empty_section(monkeypatch):
    _patch(monkeypatch, contexts=[], error=HTTPException(status_code=502, detail="model yok"))
    content = _draft(details=None, subject="Kira bedelinin ödenmemesi nedeniyle tahliye")["content"]
    assert "1. Dava konusu: Kira bedelinin ödenmemesi nedeniyle tahliye." in content and "2. […]" in content


def test_topic_hints_are_listed_first_as_suggestions_and_never_twice(monkeypatch):
    hint = {"reference": "TÜRK BORÇLAR KANUNU (6098) m. 315", "source_url": "https://mevzuat.gov.tr/x", "verification": "official",
            "source_type": "legislation", "law_no": "6098", "article_no": "315"}
    same_article = _context(law_no="6098", article_no="315", law_name="TÜRK BORÇLAR KANUNU")
    _patch(monkeypatch, contexts=[same_article, _context()], output="1. Müvekkil 8 yıl 1 ay çalışmıştır.", hints=[hint])
    result = _draft()
    content = result["content"]
    assert "Konuya göre otomatik önerilen maddeler" in content and content.count("m. 315") == 1
    assert content.index("m. 315") < content.index("Aramada bulunan diğer mevzuat") < content.index("m. 344")
    assert "uygunluğunu avukat kontrol etmelidir" in content and result["sources"][0]["reference"].endswith("m. 315")


def test_an_unknown_topic_gets_no_statute_suggestion():
    from api import statute_hints

    assert statute_hints.suggest("Komşunun köpeği bahçeme giriyor") == []
    assert [(h.law_no, h.article_no) for h in statute_hints.suggest("Kira bedelinin ödenmemesi nedeniyle tahliye")] == [("6098", "315"), ("6098", "352")]
    assert [(h.law_no, h.article_no) for h in statute_hints.suggest("Kira artış oranının tespiti")] == [("6098", "344"), ("6098", "345")]
    hint = statute_hints.suggest("Kıdem tazminatı alacağı")[0]
    assert statute_hints.text_matches(hint, "Kıdem tazminatı: Madde 14 – Bu Kanuna tabi işçilerin...") and not statute_hints.text_matches(hint, "Yürürlük: Bu Kanun yayımı tarihinde yürürlüğe girer.")


def test_emsal_list_prefers_higher_courts_and_is_capped(monkeypatch):
    from api import draft_documents

    def decision(court, chamber, docket):
        return _context(source_type="court_decision", law_name=None, law_no=None, article_no=None, court_name=court, chamber=chamber, docket_no=docket, decision_no="2026/1")

    contexts = [decision("Ankara 9. Asliye Ticaret Mahkemesi", None, "2024/18"), decision("İstanbul Bölge Adliye Mahkemesi", "14. Hukuk Dairesi", "2022/1842"),
                decision("Yargıtay", "3. Hukuk Dairesi", "2025/5173"), decision("Yargıtay", "Hukuk Genel Kurulu", "2024/785"), decision("Kayseri 1. Asliye Ticaret Mahkemesi", None, "2024/665")]
    legal = draft_documents.legal_references(contexts)
    assert len(legal.decisions) == draft_documents.MAX_DECISIONS
    assert "Hukuk Genel Kurulu" in legal.decisions[0] and "Yargıtay 3. Hukuk Dairesi" in legal.decisions[1] and "Bölge Adliye" in legal.decisions[2]


def test_verified_statutes_and_decisions_are_listed_by_code_not_by_the_model(monkeypatch):
    decision = _context(source_type="court_decision", law_name=None, law_no=None, article_no=None, court_name="Yargıtay", chamber="9. Hukuk Dairesi", docket_no="2025/412", decision_no="2026/118")
    other = _context(source_type="other", law_name=None, law_no=None, article_no=None, title="Sayıştay ilamı")
    _patch(monkeypatch, contexts=[_context(), _context(), decision, other], output="1. Müvekkil 8 yıl 1 ay çalışmıştır.")
    result = _draft(subject="Türk Borçlar Kanunu kira artışına ilişkin talepler")
    assert result["content"].count("Türk Borçlar Kanunu (6098) m. 344") == 1  # tekrar edilmez
    assert "Yargıtay 9. Hukuk Dairesi, E. 2025/412, K. 2026/118" in result["content"]
    assert "Sayıştay" not in result["content"]
    assert [item["verification"] for item in result["sources"]] == ["official", "official"]


def test_unrelated_regulation_cannot_become_contract_legal_basis(monkeypatch):
    from api.draft_documents import legal_references

    unrelated = _context(law_name="Tarımda kullanılan gübrelerin piyasa gözetimi ve denetimi yönetmeliği",
                         title="Gübre yönetmeliği", law_no="38682", article_no="10")
    legal = legal_references([unrelated], question="Web sitesi hazırlanması ve hosting hizmeti")
    assert legal.statutes == [] and legal.sources == []


@pytest.mark.parametrize("doc_type,marker", [("dilekce", "SONUÇ VE İSTEM"), ("ihtarname", "İHTAR:"), ("sozlesme", "MADDE 7 – Uyuşmazlık"), ("diger", "SONUÇ VE İSTEM")])
def test_every_document_type_has_its_skeleton_and_unfilled_gaps(monkeypatch, doc_type, marker):
    _patch(monkeypatch, contexts=[], output="1. Müvekkil 8 yıl 1 ay çalışmıştır.")
    content = _draft(doc_type=doc_type, parties=[])["content"]
    assert marker in content and "[…]" in content and "Taslaktır" in content


# --- Analiz ve risk -------------------------------------------------------------------------------------------


def test_analysis_filters_unrelated_sources_using_document_not_instruction():
    import json
    from api import office_analysis

    async def generate(system, prompt):
        if "denetçisisin" in system:
            return json.dumps({"results": [True] * len(json.loads(prompt)["MADDELER"])})
        return "- Teslim süresi 30 gündür."

    unrelated = _context(law_name="Tarımsal destekler kararı", content="Gübre ve tohum desteği ödenir.")
    markdown, sources = asyncio.run(office_analysis.analyze(
        "Tarımsal destekler kararı hakkında incele", generate, [unrelated],
        documents=[("Hizmet", "Web sitesi hazırlanacaktır. Teslim süresi 30 gündür.")],
    ))
    assert sources == []
    assert "Tarımsal destekler kararı" not in markdown


def test_analysis_preserves_percent_payment_and_explicitly_related_source():
    import json
    from api import office_analysis

    async def generate(system, prompt):
        if "denetçisisin" in system:
            return json.dumps({"results": [True] * len(json.loads(prompt)["MADDELER"])})
        return "- Ödemenin yüzde 50’si başlangıçta, kalan yüzde 50’si teslimde yapılacaktır."

    document = "Türk Borçlar Kanunu kapsamında hizmet. Ödemenin %50’si başlangıçta, %50’si teslimde yapılacaktır."
    related = _context(content=document)
    markdown, sources = asyncio.run(office_analysis.analyze(document, generate, [related]))
    assert "kalan yüzde 50’si teslimde" in markdown
    assert "madde belgeyle eşleşmediği" not in markdown
    assert len(sources) == 1


def test_document_analysis_summarises_each_marked_document_and_lists_sources_by_code(monkeypatch):
    async def generate(system, prompt):
        if "denetçisisin" in system:  # model denetimi: kod denetimini geçen maddeyi onaylar
            import json

            return json.dumps({"results": [True] * len(json.loads(prompt)["MADDELER"])})
        return "- Kira bedeli 10.000 TL olarak belirlenmiştir."

    from api import office_analysis

    text = "=== BELGE 1: Kira A ===\nKira bedeli 10.000 TL, süre 1 yıl.\n=== BELGE 2: Kira B ===\nKira bedeli 12.000 TL, süre 2 yıl."
    markdown, sources = asyncio.run(office_analysis.analyze(text, generate, [_context(), _context(verification="third_party")]))
    assert "## 1. Kira A" in markdown and "## 2. Kira B" in markdown
    assert "Kira bedeli 10.000 TL olarak belirlenmiştir." in markdown  # belgeyle doğrulanan madde
    assert "12.000 TL" in markdown and "Belgede geçen olgular" in markdown  # B belgesinin olgusu; uydurma 10.000 B'de elenir
    assert "Hukuki değerlendirme içermez" in markdown
    assert all(source["verification"] == "official" for source in sources)


def test_selected_analysis_keeps_documents_separate_and_does_not_summarize_the_instruction():
    from api import office_analysis

    async def generate(system, prompt):
        if "denetçisisin" in system:
            import json
            return json.dumps({"results": [True] * len(json.loads(prompt)["MADDELER"])})
        return "- Kira bedeli 10.000 TL olarak belirlenmiştir."

    markdown, _ = asyncio.run(office_analysis.analyze(
        "Bu talimat belge içeriği değildir: 999.999 TL.", generate, [],
        documents=[("Kira A.pdf", "Kira bedeli 10.000 TL olarak belirlenmiştir."), ("Kira B.pdf", "Kira bedeli 12.000 TL olarak belirlenmiştir.")],
    ))
    assert "## 1. Kira A.pdf" in markdown and "## 2. Kira B.pdf" in markdown
    assert "12.000 TL" in markdown
    assert "999.999" not in markdown


def test_selected_analysis_uses_authenticated_scope_and_refuses_any_missing_document(monkeypatch):
    import contextlib
    from types import SimpleNamespace

    first, second = uuid4(), uuid4()
    seen = []
    rows = [{"id": first, "file_name": "A.pdf", "text": "Kira 10.000 TL."}]

    @contextlib.contextmanager
    def connection(owner):
        seen.append(owner)
        def execute(sql, params):
            assert "deleted_at IS NULL" in sql and "d.status = 'ready'" in sql
            assert params == ([first, second], [first, second])
            return SimpleNamespace(fetchall=lambda: rows)
        yield SimpleNamespace(execute=execute)

    monkeypatch.setattr(office_ai, "authenticated_database_connection", connection)
    with pytest.raises(HTTPException) as failure:
        office_ai._selected_analysis_documents(USER_ID, [first, second])
    assert failure.value.status_code == 409
    assert seen == [str(USER_ID)]
    rows.append({"id": second, "file_name": "B.pdf", "text": "Kira 12.000 TL."})
    assert office_ai._selected_analysis_documents(USER_ID, [first, second]) == [("A.pdf", "Kira 10.000 TL."), ("B.pdf", "Kira 12.000 TL.")]
    with pytest.raises(HTTPException) as limit:
        office_ai._selected_analysis_documents(USER_ID, [uuid4() for _ in range(5)])
    assert limit.value.status_code == 422


def test_risk_analysis_never_predicts_outcomes_and_reports_sources(monkeypatch):
    from types import SimpleNamespace

    citation = SimpleNamespace(marker="K1", reference="İŞ KANUNU (4857) m. 41", source_url=None, verification="official", source_type="legislation")

    async def answer(user_id, question, conversation_id):
        return SimpleNamespace(answer=f"Cevap: {question} [K1]", grounded=True, citations=[citation], conversation_id=None)

    monkeypatch.setattr(office_ai, "_deep_answer", answer)
    result = asyncio.run(office_ai._risk("İşçiye fazla mesai ücreti ödenmedi, puantaj var, dava açılırsa riskler neler?", USER_ID))
    assert "Dava sonucu tahmini yapılmaz" in result["content"] and "Risk analizi" in result["content"]
    assert result["sources"] and result["sources"][0]["reference"] == "İŞ KANUNU (4857) m. 41"


def test_risk_exposes_unverified_sections_to_document_queue(monkeypatch):
    from types import SimpleNamespace

    async def answer(user_id, question, conversation_id):
        return SimpleNamespace(answer=f"Eksik: {question}", grounded=False, citations=[], conversation_id=None)

    monkeypatch.setattr(office_ai, "_deep_answer", answer)
    result = asyncio.run(office_ai._risk("Sentetik olay için süre ve ispat incelemesi", USER_ID))
    assert len(result["errors"]) == 3
    assert "her bölümün cevabı kendi kaynaklarına karşı doğrulanmıştır" not in result["content"]


def test_risk_grounded_but_incomplete_sections_are_still_partial(monkeypatch):
    from types import SimpleNamespace

    async def answer(user_id, question, conversation_id):
        return SimpleNamespace(answer=f"Kaynaklı: {question}", grounded=True, coverage_complete=False,
                               citations=[], conversation_id=None)

    monkeypatch.setattr(office_ai, "_deep_answer", answer)
    result = asyncio.run(office_ai._risk("Sentetik olay için kaynak ve kapsam incelemesi", USER_ID))
    assert len(result["errors"]) == 3
    assert all("tamamı karşılanmadı" in error for error in result["errors"])
