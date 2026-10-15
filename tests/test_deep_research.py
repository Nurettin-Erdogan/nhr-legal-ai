"""Derin araştırma: belirleyici plan, adım hataları, rapor ve uç noktalar (gerçek RLS'li veritabanında)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from api import deep_research as research
from api import office_ai
from tests.test_case_document_rag import db, needs_db  # noqa: F401  (fixture)

QUESTION = "Kıdem tazminatına hak kazanma şartları nelerdir ve zamanaşımı ne zaman başlar"


def _citation(marker="K1", verification="official"):
    return SimpleNamespace(marker=marker, reference="İŞ KANUNU m. 14", source_url=None, verification=verification, source_type="legislation")


def _response(answer="Kıdem tazminatı bir yıl çalışma ile doğar [K1].", grounded=True, citations=None, conversation_id=None):
    return SimpleNamespace(answer=answer, grounded=grounded, citations=[_citation()] if citations is None else citations, conversation_id=conversation_id)


def test_citation_payload_preserves_source_identity_for_the_internal_reader():
    citation = _citation()
    citation.source_id = uuid4()
    citation.excerpt = "Kayıtlı alıntı"
    payload = research._citation_payload(citation)
    assert payload["source_id"] == str(citation.source_id)
    assert payload["excerpt"] == citation.excerpt
    assert payload["verification"] == "official"
    assert json.loads(json.dumps(payload))["source_id"] == str(citation.source_id)
    legacy = research._citation_payload(_citation())
    assert legacy["source_id"] is None and legacy["excerpt"] is None


# --- Plan ---------------------------------------------------------------------------------------------------------------------


def test_the_plan_is_deterministic_and_keeps_the_users_question():
    steps = research.plan(QUESTION + "?")
    assert [axis.key for axis, _ in steps] == ["mevzuat", "ictihat", "usul"]
    assert steps == research.plan(QUESTION + "?")
    for axis, question in steps:
        assert question.startswith(QUESTION) and question.endswith(axis.suffix)
        assert "?" not in question and len(question) <= 2000


def test_a_very_long_question_still_fits_the_answer_limit():
    long_question = "kıdem tazminatı " * 200
    assert all(len(question) <= 2000 for _, question in research.plan(long_question))


# --- İş akışı -----------------------------------------------------------------------------------------------------------------


def _job():
    return research.ResearchJob(id=uuid4(), owner_id=uuid4(), question=QUESTION)


def test_all_steps_run_in_order_and_share_one_conversation():
    seen: list = []
    conversation = uuid4()

    async def answer(question, conversation_id):
        seen.append((question, conversation_id))
        return _response(answer=f"Cevap: {question} [K1]", conversation_id=conversation)

    job = _job()
    asyncio.run(research.run_job(job, answer))
    assert job.state == "done" and [step.key for step in job.steps] == ["mevzuat", "ictihat", "usul"]
    assert seen[0][1] is None and seen[1][1] == conversation and seen[2][1] == conversation  # adımlar tek sohbette toplanır
    assert job.stage == "Tamamlandı." and all(step.grounded and step.citations[0]["marker"] == "K1" for step in job.steps)


def test_an_identical_answer_is_not_repeated_under_every_heading():
    async def answer(question, conversation_id):
        return _response(answer="Kıdem tazminatı: Madde 14 ... [K1]")

    job = _job()
    asyncio.run(research.run_job(job, answer))
    first, second, third = job.steps
    assert first.answer and not first.note
    assert second.answer == third.answer == "" and "önceki başlıkta" in second.note and second.error is None and not second.citations
    assert job.state == "done"
    markdown = research.render_markdown(QUESTION, job.steps)
    assert markdown.count("Madde 14") == 1 and "aynı kaynaklar önceki başlıkta sunuldu" in markdown


def test_one_failing_step_does_not_stop_the_others():
    async def answer(question, conversation_id):
        if question.endswith("Yargıtay kararı"):
            raise HTTPException(status_code=503, detail="Model şu an yanıt vermiyor")
        return _response(answer=f"Cevap: {question} [K1]")

    job = _job()
    asyncio.run(research.run_job(job, answer))
    assert job.state == "done"
    errors = {step.key: step.error for step in job.steps}
    assert errors == {"mevzuat": None, "ictihat": "Model şu an yanıt vermiyor", "usul": None}


def test_when_every_step_fails_the_job_fails_and_nothing_is_saved():
    saved: list = []

    async def answer(question, conversation_id):
        raise HTTPException(status_code=503, detail="Model kapalı")

    async def on_done(job):
        saved.append(job.id)

    job = _job()
    asyncio.run(research.run_job(job, answer, on_done))
    assert job.state == "failed" and job.error and saved == []


def test_a_save_failure_keeps_the_report_visible():
    async def answer(question, conversation_id):
        return _response()

    async def on_done(job):
        raise RuntimeError("disk dolu")

    job = _job()
    asyncio.run(research.run_job(job, answer, on_done))
    assert job.state == "done" and len(job.steps) == 3 and job.saved_id is None


# --- Rapor --------------------------------------------------------------------------------------------------------------------


def test_the_report_states_gaps_unverified_sources_and_limits():
    steps = [
        research.StepResult("mevzuat", "İlgili mevzuat", "q1", answer="Bir yıl çalışma gerekir [K1].", grounded=True, citations=[research._citation_payload(_citation())]),
        research.StepResult("ictihat", "Yargı kararları", "q2", answer="Yargıtay şöyle demiştir [K1].", grounded=False,
                            citations=[research._citation_payload(_citation(verification="third_party"))]),
        research.StepResult("usul", "Süre, ispat ve usul", "q3", error="Model şu an yanıt vermiyor"),
    ]
    markdown = research.render_markdown(QUESTION, steps)
    assert "# Derin araştırma raporu" in markdown and QUESTION in markdown
    assert "Doktrin ve karşılaştırmalı hukuk kaynakları korpusta yoktur" in markdown
    assert "- [K1] İŞ KANUNU m. 14 (Resmî metin ✓)\n" in markdown  # resmî kaynak işaretli
    assert "- [K1] İŞ KANUNU m. 14\n" in markdown  # karşılaştırılmamış kayıt: olumsuz ibare de ✓ de yok (AGENTS.md, 2026-10-15)
    assert "doğrulanmadı" not in markdown
    assert "yeterince desteklenemedi" in markdown  # desteklenmeyen bölüm uyarılı
    assert "Bu başlık tamamlanamadı: Model şu an yanıt vermiyor" in markdown


# --- Uç noktalar (gerçek RLS'li veritabanı) -------------------------------------------------------------------------------------


@pytest.fixture
def world(db, monkeypatch):  # noqa: F811
    @contextlib.contextmanager
    def as_user(user_id: str):
        db.become(UUID(user_id))
        yield db.connection

    monkeypatch.setattr(office_ai, "authenticated_database_connection", as_user)
    research.registry.clear()
    state = SimpleNamespace(questions=[], gate=None, fail=False)

    async def fake_answer(user_id, question, conversation_id):
        state.questions.append(question)
        if state.gate is not None:
            await state.gate.wait()
        if state.fail:
            raise HTTPException(status_code=503, detail="Model kapalı")
        return _response(answer=f"Cevap: {question} [K1]", conversation_id=uuid4())

    monkeypatch.setattr(office_ai, "_deep_answer", fake_answer)
    db.state = state
    yield db
    research.registry.clear()


async def _run(user, question=QUESTION):
    response = await office_ai.start_deep_research(office_ai.DeepResearchRequest(question=question), user)
    job = research.registry.latest_for(user)
    for _ in range(500):
        if job.state != "running":
            break
        await asyncio.sleep(0.01)
    return response, job


@needs_db
def test_a_research_job_saves_the_report_and_audits_counts_only(world):
    response, job = asyncio.run(_run(world.alice))

    assert response["steps"] == ["İlgili mevzuat", "Yargı kararları", "Süre, ispat ve usul"]
    assert job.state == "done" and job.saved_id is not None and len(world.state.questions) == 3
    world.become(None)
    [row] = world.connection.execute("SELECT module, title, prompt, output, sources FROM office_ai_outputs WHERE id = %s", (job.saved_id,)).fetchall()
    assert row["module"] == "deep_research" and row["prompt"] == QUESTION and "# Derin araştırma raporu" in row["output"]
    assert [step["key"] for step in row["sources"]["steps"]] == ["mevzuat", "ictihat", "usul"]
    [event] = world.connection.execute("SELECT metadata FROM activity_logs WHERE action = 'office.deep_research' AND entity_id = %s", (job.saved_id,)).fetchall()
    assert event["metadata"] == {"steps": 3, "grounded": 3} and "Kıdem" not in json.dumps(event["metadata"])


@needs_db
def test_the_saved_report_is_read_by_its_owner_only_and_survives_a_restart(world):
    asyncio.run(_run(world.alice))
    research.registry.clear()

    mine = office_ai.get_deep_research(world.alice)
    assert mine["job"] is None and mine["latest"]["question"] == QUESTION and len(mine["latest"]["steps"]) == 3
    assert "# Derin araştırma raporu" in mine["latest"]["markdown"]
    assert office_ai.get_deep_research(world.bob) == {"job": None, "latest": None}


@needs_db
def test_one_research_per_user_at_a_time_and_short_questions_are_refused(world):
    async def scenario():
        world.state.gate = asyncio.Event()
        await office_ai.start_deep_research(office_ai.DeepResearchRequest(question=QUESTION), world.alice)
        with pytest.raises(HTTPException) as busy:
            await office_ai.start_deep_research(office_ai.DeepResearchRequest(question=QUESTION), world.alice)
        job = research.registry.latest_for(world.alice)
        # başka kullanıcının işi engellenmez
        other = await office_ai.start_deep_research(office_ai.DeepResearchRequest(question=QUESTION), world.bob)
        world.state.gate.set()
        for _ in range(500):
            if all(item.state != "running" for item in (job, research.registry.latest_for(world.bob))):
                break
            await asyncio.sleep(0.01)
        return busy.value.status_code, job.state, other

    status, state, other = asyncio.run(scenario())
    assert status == 409 and state == "done" and other["job_id"]
    with pytest.raises(Exception):
        office_ai.DeepResearchRequest(question="kısa soru")


@needs_db
def test_when_the_model_is_down_nothing_is_saved(world):
    world.state.fail = True
    _, job = asyncio.run(_run(world.alice))
    assert job.state == "failed" and job.saved_id is None
    assert office_ai.get_deep_research(world.alice)["latest"] is None
