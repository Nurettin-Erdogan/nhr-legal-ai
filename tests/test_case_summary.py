"""Dosya özeti: olgu çıkarımı, pencereleme, kodda özet doğrulama ve arka plan işi (gerçek RLS'li veritabanında)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from api import case_summary as summary
from api import office, office_ai
from tests.test_case_document_rag import _case, _indexed_document, db, needs_db  # noqa: F401  (fixture)

SOURCE = (
    "Davacı Ahmet Örnek, 01.03.2015 ile 15.04.2023 tarihleri arasında Deneme Tekstil Sanayi A.Ş.'de çalışmıştır. "
    "İş sözleşmesi haklı neden gösterilmeden feshedilmiştir. Kıdem tazminatı 340.000 TL, ihbar tazminatı 77.000 TL "
    "olarak hesaplanmıştır. Esas No: 2025/412, Karar No: 2026/118. 4857 sayılı İş Kanunu uygulanmıştır."
)


# --- Olgu çıkarımı --------------------------------------------------------------------------------


def test_facts_are_extracted_verbatim_and_invalid_dates_are_rejected():
    facts = summary.extract_facts(SOURCE + " Geçersiz tarih 31.02.2020 ve 15 Nisan 2023 ile 3 Mart 2021.")
    assert facts["dates"] == ["01.03.2015", "15.04.2023", "15 Nisan 2023", "3 Mart 2021"]
    assert facts["amounts"] == ["340.000 TL", "77.000 TL"]
    assert facts["esas"] == ["2025/412"] and facts["karar"] == ["2026/118"] and facts["laws"] == ["4857"]
    for values in (facts["dates"], facts["amounts"], facts["esas"], facts["karar"], facts["laws"]):
        assert all(value in SOURCE + " 15 Nisan 2023 3 Mart 2021" for value in values)  # her değer metinde aynen geçer


def test_identity_numbers_are_never_extracted():
    facts = summary.extract_facts("Davacı TCKN 12345678901 numaralıdır. IBAN TR330006100519786457841326. Tel 05321234567.")
    flat = json.dumps(facts, ensure_ascii=False)
    assert "12345678901" not in flat and "TR33" not in flat and "05321234567" not in flat


def test_docket_numbers_are_labelled_by_context():
    facts = summary.extract_facts("E. 2019/7 K. 2020/9 ile Esas: 2018/1, karar no 2018/2 ve ayrıca 2021/55 sayılı dosya.")
    assert facts["esas"] == ["2019/7", "2018/1"] and facts["karar"] == ["2020/9", "2018/2"] and facts["numbers"] == ["2021/55"]


def test_amount_forms_and_duplicates():
    facts = summary.extract_facts("Bedel 1.250,50 TL, ayrıca 500 ₺ ve 1.250,50 TL; 20 kişi katıldı.")
    assert facts["amounts"] == ["1.250,50 TL", "500 ₺"]


# --- Pencereleme -----------------------------------------------------------------------------------


def test_short_text_is_one_window_with_full_coverage():
    windows, coverage = summary.split_windows("Kısa bir metin.\n\nİkinci paragraf.")
    assert windows == ["Kısa bir metin.\n\nİkinci paragraf."] and coverage == 1.0
    assert summary.split_windows("   ") == ([], 1.0)


def test_windows_respect_the_size_and_paragraph_boundaries():
    paragraphs = [f"Paragraf {n}: " + "söz " * 120 for n in range(12)]
    windows, coverage = summary.split_windows("\n\n".join(paragraphs), size=1200, limit=100)
    assert coverage == 1.0 and all(len(window) <= 1200 for window in windows)
    assert " ".join(windows).split() == " ".join(paragraphs).split()  # hiçbir söz kaybolmaz


def test_coverage_reports_what_was_left_out():
    text = "\n\n".join("söz " * 300 for _ in range(30))
    windows, coverage = summary.split_windows(text, size=1000, limit=3)
    assert len(windows) == 3 and 0 < coverage < 0.2


def test_a_single_overlong_paragraph_is_cut_at_word_boundaries():
    windows, _ = summary.split_windows("kelime " * 2000, size=500, limit=100)
    assert all(len(window) <= 500 and not window.endswith("keli") for window in windows)


# --- Özet doğrulama --------------------------------------------------------------------------------


def test_bullets_are_parsed_without_markers_bold_or_intro_lines():
    raw = "İşte belgenin özeti:\n1. **Davacı** çalışmıştır.\n- Kıdem tazminatı 340.000 TL hesaplanmıştır.\n\n* Esas No: 2025/412."
    assert summary.parse_bullets(raw) == ["Davacı çalışmıştır.", "Kıdem tazminatı 340.000 TL hesaplanmıştır.", "Esas No: 2025/412."]


@pytest.mark.parametrize(
    "bullet",
    [
        "Kıdem tazminatı 340.000 TL olarak hesaplanmıştır.",
        "Davacı 01.03.2015 tarihinde işe başlamıştır.",
        "Esas No 2025/412 ve Karar No 2026/118 belirtilmiştir.",
        "Fesih haklı neden gösterilmeden yapılmıştır.",
        "4857 sayılı İş Kanunu uygulanmıştır.",
        "Davacı çalışmıştır.",  # kısa: yalnız rakam denetimi
    ],
)
def test_supported_bullets_are_kept(bullet):
    assert summary.bullet_supported(bullet, SOURCE)


@pytest.mark.parametrize(
    "bullet",
    [
        "Kıdem tazminatı 999.999 TL olarak hesaplanmıştır.",  # belgede olmayan tutar
        "Davacı 05.05.2010 tarihinde işe başlamıştır.",  # belgede olmayan tarih
        "Dosya 2024/111 esas numarasını taşımaktadır.",  # belgede olmayan numara
        "6098 sayılı Kanun uygulanmıştır.",  # belgede olmayan kanun
        "Mahkeme tahliye ve kira bedelinin tespitine hükmetmiştir.",  # belgeyle örtüşmeyen içerik
    ],
)
def test_unsupported_bullets_are_dropped(bullet):
    assert not summary.bullet_supported(bullet, SOURCE)


def test_verify_summary_counts_what_it_drops():
    kept, dropped = summary.verify_summary(
        "- Kıdem tazminatı 340.000 TL hesaplanmıştır.\n- Davacıya 999.999 TL ödenmiştir.\n- Tahliye davası açılmıştır kira bedeli.", SOURCE
    )
    assert kept == ["Kıdem tazminatı 340.000 TL hesaplanmıştır."] and dropped == 2


# --- Model hattı -----------------------------------------------------------------------------------


def _text_of(prompt: str) -> str:
    return prompt.split('"""\n', 1)[1].split('\n"""', 1)[0]


def _approve_all(prompt: str) -> str:
    """Denetçi çağrısına "hepsi doğru" yanıtı (model denetimi ayrı testlerde sınanır)."""
    import json

    return json.dumps({"results": [True] * len(json.loads(prompt)["MADDELER"])})


def _echo_generate(calls: list):
    async def generate(system, prompt):
        if "denetçisisin" in system:
            return _approve_all(prompt)
        calls.append(prompt)
        if "bölüm özetleri" in system:
            return "- Kıdem tazminatı 340.000 TL hesaplanmıştır."
        return "- " + _text_of(prompt).split(". ")[0][:120] + "."  # ilk cümle (tarihteki noktadan bölünmez)

    return generate


def test_a_long_document_is_summarised_per_window_then_merged():
    calls: list = []
    text = "\n\n".join(f"Bölüm {n}. {SOURCE}" for n in range(12))
    result = asyncio.run(summary.summarize_document(uuid4(), "uzun.pdf", text, ocr=False, generate=_echo_generate(calls)))
    windows, _ = summary.split_windows(text)
    assert len(calls) == len(windows) + 1 and result.bullets == ["Kıdem tazminatı 340.000 TL hesaplanmıştır."] and result.error is None


def test_fabricated_model_output_yields_an_error_not_a_summary():
    async def liar(system, prompt):
        assert "denetçisisin" not in system  # kod denetiminden madde geçmediği için model denetimi hiç çağrılmaz
        return "- Davacıya 999.999 TL ödenmiştir.\n- 6098 sayılı Kanun uygulanmıştır."

    result = asyncio.run(summary.summarize_document(uuid4(), "x.udf", SOURCE, ocr=False, generate=liar))
    assert result.bullets == [] and result.dropped == 2 and "doğrulanamadı" in result.error


NOTICE = (
    "İHTARNAME\nKeşideci: Ayşe Demir\nMuhatap: Mehmet Kaya\nKonu: 2025 yılı Ocak, Şubat ve Mart aylarına ait toplam 55.500 TL kira "
    "borcunun 30 gün içinde ödenmesi, aksi halde TBK m. 315 uyarınca sözleşmenin feshedileceği ve tahliye davası açılacağı ihtarıdır."
)


def test_a_bullet_that_turns_an_otherwise_clause_into_a_positive_condition_is_dropped():
    """Canlıda görüldü: "ödenmesi, aksi halde feshedileceği" → "ödenmesi halinde feshedileceği" (anlam tersine döner)."""
    flipped = "Kira borcunun 30 gün içinde ödenmesi halinde sözleşmenin feshedileceği ve tahliye davası açılacağı uyarısı yapılmıştır."
    assert summary.flips_otherwise(flipped, NOTICE) and not summary.bullet_supported(flipped, NOTICE)
    for faithful in (
        "Kira borcu 30 gün içinde ödenmezse sözleşmenin feshedileceği ve tahliye davası açılacağı ihtar edilmiştir.",
        "Kira borcunun 30 gün içinde ödenmesi, aksi halde sözleşmenin feshedileceği ihtar edilmiştir.",
        "Borç tutarı olarak toplam 55.500 TL belirtilmiştir.",
    ):
        assert not summary.flips_otherwise(faithful, NOTICE) and summary.bullet_supported(faithful, NOTICE)


def test_true_bullets_are_not_dropped_for_their_own_reporting_verbs():
    lease = "Aylık kira bedeli 18.500 TL olup her ayın 5'ine kadar ödenir. Depozito 37.000 TL'dir. Süre 1 yıldır."
    assert summary.bullet_supported("Depozito tutarı 37.000 TL olarak belirlenmiştir.", lease)
    assert summary.bullet_supported("Aylık kira bedeli 18.500 TL olup her ayın 5'ine kadar ödenmesi şarttır.", lease)
    assert not summary.bullet_supported("Depozito tutarı 99.000 TL olarak belirlenmiştir.", lease)  # sayı denetimi aynen sürer


def test_line_breaks_inside_a_paragraph_survive_windowing():
    windows, coverage = summary.split_windows("Keşideci:  Ayşe Demir\nMuhatap: Mehmet Kaya\n\nKonu: kira")
    assert windows == ["Keşideci: Ayşe Demir\nMuhatap: Mehmet Kaya\n\nKonu: kira"] and coverage == 1.0


def test_the_model_checker_only_removes_bullets_and_fails_closed_on_unreadable_output():
    bullets = ["Davalı duruşmaya gelmiştir.", "Bir sonraki duruşma 18.09.2025 tarihine bırakıldı."]
    window = ["Davalı gelmedi. Bir sonraki duruşma 18.09.2025 tarihine bırakıldı."]

    async def strict(system, prompt):
        assert "denetçisisin" in system and "Davalı gelmedi" in prompt
        return '{"results": [false, true]}'

    assert asyncio.run(summary.check_bullets(bullets, window, strict)) == (["Bir sonraki duruşma 18.09.2025 tarihine bırakıldı."], 1)

    async def broken(system, prompt):
        return "üzgünüm, JSON yazamadım"

    assert asyncio.run(summary.check_bullets(bullets, window, broken)) == ([], 2)

    async def wrong_length(system, prompt):
        return '{"results": [true]}'

    assert asyncio.run(summary.check_bullets(bullets, window, wrong_length)) == ([], 2)


def test_a_bullet_rejected_by_the_checker_is_counted_as_dropped():
    async def generate(system, prompt):
        if "denetçisisin" in system:
            return '{"results": [false]}'
        return "- Kıdem tazminatı 340.000 TL hesaplanmıştır."

    result = asyncio.run(summary.summarize_document(uuid4(), "x.udf", SOURCE, ocr=False, generate=generate))
    assert result.bullets == [] and result.dropped == 1 and "doğrulanamadı" in result.error


def test_empty_text_is_reported():
    result = asyncio.run(summary.summarize_document(uuid4(), "bos.udf", "  ", ocr=False, generate=_echo_generate([])))
    assert result.error and not result.bullets


def test_markdown_states_coverage_ocr_and_dropped_items():
    item = summary.DocumentSummary(uuid4(), "tarama.pdf", ocr=True, coverage=0.5, bullets=["Madde bir."], dropped=2)
    markdown = summary.render_markdown([item])
    assert "%50" in markdown and "OCR" in markdown and "2 madde belgeyle eşleşmediği" in markdown and "- Madde bir." in markdown
    assert "hukuki dayanak" in markdown  # özet resmî kaynak gibi sunulmaz


# --- Uç noktalar (gerçek RLS'li veritabanı) --------------------------------------------------------


@pytest.fixture
def world(db, monkeypatch):  # noqa: F811
    @contextlib.contextmanager
    def as_user(user_id: str):
        db.become(UUID(user_id))
        yield db.connection

    monkeypatch.setattr(office, "authenticated_database_connection", as_user)
    monkeypatch.setattr(office_ai, "authenticated_database_connection", as_user)
    summary.registry.clear()
    state = SimpleNamespace(prompts=[], gate=None, fail_for=set(), reply=None)

    async def fake_generate(system, prompt):
        if "denetçisisin" in system:  # model denetimi ayrı testlerde sınanır; burada kod denetimini geçenler onaylanır
            return _approve_all(prompt)
        state.prompts.append(prompt)
        if state.gate is not None:
            await state.gate.wait()
        text = _text_of(prompt)
        if any(marker in text for marker in state.fail_for):
            raise HTTPException(status_code=503, detail="Model şu an yanıt vermiyor")
        if state.reply is not None:
            return state.reply
        return "- " + text.split(". ")[0][:120] + "."  # ilk cümle (tarihteki noktadan bölünmez)

    monkeypatch.setattr(office_ai, "_generate", lambda system, prompt: _pair(fake_generate(system, prompt)))
    db.state = state
    yield db
    summary.registry.clear()


async def _pair(coroutine):
    return await coroutine, "test-model"


async def _run(user, case, ids):
    response = await office_ai.start_case_summary(case, office_ai.CaseSummaryRequest(document_ids=ids), user)
    job = summary.registry.latest_for(user, case)
    for _ in range(500):
        if job.state != "running":
            break
        await asyncio.sleep(0.01)
    return response, job


def _start(user, case, ids):
    return asyncio.run(_run(user, case, ids))


@needs_db
def test_a_summary_job_runs_saves_the_result_and_audits_ids_only(world):
    case = _case(world, world.alice)
    first = _indexed_document(world, world.alice, case, SOURCE, name="gizli-muvekkil.udf")
    second = _indexed_document(world, world.alice, case, "Kiracı kira bedelini ödemiştir. Sözleşme 2020 yılında yapılmıştır.", name="kira.udf")

    response, job = _start(world.alice, case, [first, second])

    assert response["total"] == 2 and job.state == "done" and job.done == 2 and job.error is None
    assert sorted(r.file_name for r in job.results) == ["gizli-muvekkil.udf", "kira.udf"] and all(r.bullets for r in job.results)  # aynı işlemde created_at eşit: sıra kimliğe bağlı
    world.become(None)
    [row] = world.connection.execute(
        "SELECT module, title, output, sources, model, case_id FROM office_ai_outputs WHERE id = %s", (job.saved_id,)
    ).fetchall()
    assert row["module"] == "case_summary" and row["case_id"] == case and row["model"] == "test-model"
    assert "# Dosya özeti" in row["output"] and "gizli-muvekkil.udf" in row["output"]
    assert [item["verification"] for item in row["sources"]] == ["user_document", "user_document"] and row["sources"][0]["bullets"]
    [event] = world.connection.execute(
        "SELECT metadata FROM activity_logs WHERE action = 'office.case_summary' AND entity_id = %s", (job.saved_id,)
    ).fetchall()
    assert event["metadata"] == {"case_id": str(case), "documents": 2} and "gizli" not in json.dumps(event["metadata"])


@needs_db
def test_the_saved_summary_is_readable_by_its_owner_only(world):
    case = _case(world, world.alice)
    document = _indexed_document(world, world.alice, case, SOURCE)
    _start(world.alice, case, [document])
    summary.registry.clear()  # API yeniden başladı: iş kaydı gitti, sonuç veritabanında kalır

    mine = office_ai.get_case_summary(case, world.alice)
    assert mine["job"] is None and mine["latest"]["documents"][0]["bullets"] and "# Dosya özeti" in mine["latest"]["markdown"]
    assert office_ai.get_case_summary(case, world.bob) == {"job": None, "latest": None}


@needs_db
def test_foreign_cases_unknown_and_unready_documents_are_refused(world):
    case = _case(world, world.alice)
    ready = _indexed_document(world, world.alice, case, SOURCE)
    trashed = _indexed_document(world, world.alice, case, SOURCE + " Ek.")
    world.become(None)
    world.connection.execute("UPDATE office_case_documents SET deleted_at = NOW() WHERE id = %s", (trashed,))

    with pytest.raises(HTTPException) as foreign:
        _start(world.bob, case, [ready])
    assert foreign.value.status_code == 404
    for ids in ([trashed], [ready, uuid4()]):
        with pytest.raises(HTTPException) as refused:
            _start(world.alice, case, ids)
        assert refused.value.status_code == 409
    assert world.state.prompts == []  # model hiç çağrılmadı


@needs_db
def test_only_one_job_per_user_runs_at_a_time(world):
    case = _case(world, world.alice)
    document = _indexed_document(world, world.alice, case, SOURCE)

    async def scenario():
        world.state.gate = asyncio.Event()
        await office_ai.start_case_summary(case, office_ai.CaseSummaryRequest(document_ids=[document]), world.alice)
        with pytest.raises(HTTPException) as busy:
            await office_ai.start_case_summary(case, office_ai.CaseSummaryRequest(document_ids=[document]), world.alice)
        job = summary.registry.latest_for(world.alice, case)
        assert busy.value.status_code == 409 and job.state == "running"
        world.state.gate.set()
        for _ in range(500):
            if job.state != "running":
                break
            await asyncio.sleep(0.01)
        return job

    assert asyncio.run(scenario()).state == "done"


@needs_db
def test_one_failing_document_does_not_stop_the_others(world):
    case = _case(world, world.alice)
    good = _indexed_document(world, world.alice, case, SOURCE, name="iyi.udf")
    bad = _indexed_document(world, world.alice, case, "ARIZALI belge metni burada yer alır.", name="arizali.udf")
    world.state.fail_for = {"ARIZALI"}

    _, job = _start(world.alice, case, [good, bad])

    assert job.state == "done"
    by_name = {r.file_name: r for r in job.results}
    assert by_name["iyi.udf"].bullets and by_name["arizali.udf"].error == "Model şu an yanıt vermiyor" and not by_name["arizali.udf"].bullets


@needs_db
def test_when_nothing_can_be_verified_the_job_fails_and_nothing_is_saved(world):
    case = _case(world, world.alice)
    document = _indexed_document(world, world.alice, case, SOURCE)
    world.state.reply = "- Davacıya 999.999 TL ödenmiştir."

    _, job = _start(world.alice, case, [document])

    assert job.state == "failed" and job.saved_id is None and job.results[0].dropped == 1
    assert office_ai.get_case_summary(case, world.alice)["latest"] is None


@needs_db
def test_facts_endpoint_returns_table_for_ready_documents_and_hides_foreign_cases(world):
    case = _case(world, world.alice)
    _indexed_document(world, world.alice, case, SOURCE, name="bilirkisi.udf")
    world.become(None)
    pending = uuid4()
    world.connection.execute(
        "INSERT INTO office_case_documents (id, owner_id, case_id, file_name, storage_path, size_bytes) VALUES (%s, %s, %s, 'bekleyen.pdf', 'x', 4)",
        (pending, world.alice, case),
    )

    facts = office.case_document_facts(case_id=case, user_id=world.alice)

    assert facts["total"] == 2 and facts["ready"] == 1
    [document] = facts["documents"]
    assert document["file_name"] == "bilirkisi.udf" and "340.000 TL" in document["amounts"] and document["esas"] == ["2025/412"]
    with pytest.raises(HTTPException) as foreign:
        office.case_document_facts(case_id=case, user_id=world.bob)
    assert foreign.value.status_code == 404


def test_a_validity_or_necessity_claim_absent_from_the_document_is_rejected():
    # Belgede yalnız tutar yazıyor; özet buna "geçerlilik koşulu" anlamı ekleyemez.
    from api.case_summary import adds_normative_term, bullet_supported

    source = "Aylık kira bedeli 18.500 TL olup her ayın 5'ine kadar ödenir. Depozito 37.000 TL'dir. Kiracı, kiralananı alt kiraya veremez."
    invented = "Kira sözleşmesinin geçerliliği için 37.000 TL tutarında depozito alınmıştır."
    assert adds_normative_term(invented, source) and not bullet_supported(invented, source)
    assert not bullet_supported("Depozitonun ödenmesi zorunludur ve tutarı 37.000 TL'dir.", source)
    assert not bullet_supported("Kiracı 18.500 TL kira bedelini ödemekle yükümlüdür; aksi halde sözleşme hükümsüzdür.", source)
    # Aynı bilgiyi niteleme eklemeden söyleyen madde geçer.
    assert bullet_supported("Depozito tutarı 37.000 TL olarak belirlenmiştir.", source)
    assert bullet_supported("Kiracı kiralananı alt kiraya veremez.", source)
    # Belge nitelemeyi kendisi yapıyorsa madde de yapabilir.
    conditional = "Sözleşme, depozitonun ödenmesi şartıyla geçerlidir. Depozito 37.000 TL'dir."
    assert bullet_supported("Sözleşmenin geçerliliği 37.000 TL depozitonun ödenmesi şartına bağlıdır.", conditional)
