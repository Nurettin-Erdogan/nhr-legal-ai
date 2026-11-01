"""Tam metin kuyruğunun kabul testleri: gerçek model/ağ/canlı DB kullanılmaz."""

import asyncio
import json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api import document_jobs as jobs, office_ai, case_summary
from api.audit import AuditContext
from api.deep_research import MAX_QUESTION_CHARS

OWNER = uuid4()


def test_full_windows_cover_tail_and_risk_calls_never_truncate():
    text = ("Uzun belgenin bölüm metni ve açıklamalar. " * 2000) + "SON_BÖLÜM_340000"
    for risk in (False, True):
        windows = jobs.full_windows(text, risk=risk)
        assert len(windows) > 6
        assert "SON_BÖLÜM_340000" in windows[-1]
        assert (
            all(len(window) <= MAX_QUESTION_CHARS - 400 for window in windows)
            if risk
            else True
        )


def test_two_thousand_documents_are_accepted_without_a_four_document_limit():
    assert (
        len(
            jobs.JobRequest(
                module="auto_summary", document_ids=[uuid4() for _ in range(2000)]
            ).document_ids
        )
        == 2000
    )
    with pytest.raises(ValidationError):
        jobs.JobRequest(
            module="auto_summary", document_ids=[uuid4() for _ in range(2001)]
        )
    with pytest.raises(ValidationError):
        jobs.JobRequest(module="unknown", text="x")


def test_jobs_require_login_for_read_start_cancel_resume():
    app = FastAPI()
    app.include_router(jobs.router)
    client = TestClient(app)
    for path, body in [
        ("", {"module": "auto_summary", "text": "metin"}),
        ("/" + str(uuid4()) + "/cancel", {}),
        ("/" + str(uuid4()) + "/resume", {}),
    ]:
        assert client.post("/api/office-ai/jobs" + path, json=body).status_code == 401
    assert client.get("/api/office-ai/jobs").status_code == 401


def test_foreign_job_lookup_is_not_found(monkeypatch):
    seen = []

    class Connection:
        def execute(self, sql, args):
            return self

        def fetchone(self):
            return None

    @contextmanager
    def connection(owner):
        seen.append(owner)
        yield Connection()

    monkeypatch.setattr(jobs, "authenticated_database_connection", connection)
    with pytest.raises(HTTPException) as error:
        jobs._read(OWNER, uuid4())
    assert error.value.status_code == 404 and seen == [str(OWNER)]


def test_empty_and_mixed_inputs_are_rejected_before_database():
    for body in [
        jobs.JobRequest(module="draft"),
        jobs.JobRequest(module="draft", text="metin", document_ids=[uuid4()]),
    ]:
        with pytest.raises(HTTPException) as error:
            jobs._create(OWNER, body, AuditContext(uuid4()))
        assert error.value.status_code == 422


def test_risk_uses_the_whole_window_and_preserves_verification(monkeypatch):
    calls = []

    async def risk(prompt, owner):
        calls.append(prompt)
        return {
            "content": "Doğrulanmadı uyarısı",
            "sources": [{"verification": "third_party"}],
        }

    monkeypatch.setattr(office_ai, "_risk", risk)
    text = "X" * 20000 + "SON_TUTAR"
    for window in jobs.full_windows(text, risk=True):
        result = asyncio.run(
            jobs.process_window(
                "risk_analysis", window, "a" * 200, uuid4(), OWNER, "b" * 500
            )
        )
        assert result["sources"][0]["verification"] == "third_party"
    assert all(len(prompt) <= MAX_QUESTION_CHARS for prompt in calls)
    assert "SON_TUTAR" in calls[-1]


def test_unverified_model_bullets_are_visible_as_partial_errors(monkeypatch):
    async def summarize(*args, **kwargs):
        return case_summary.DocumentSummary(
            uuid4(), "test", bullets=["Doğrulanan madde"], dropped=1
        )

    monkeypatch.setattr(case_summary, "summarize_document", summarize)
    result = asyncio.run(
        jobs.process_window(
            "auto_summary", "340.000 TL 07.10.2026", "a", uuid4(), OWNER, ""
        )
    )
    assert result["bullets"] == ["Doğrulanan madde"]
    assert "doğrulanamadığı" in result["errors"][0]
    assert result["facts"]["amounts"]


def test_analysis_uses_instruction_separately_from_evidence_and_not_summary(
    monkeypatch,
):
    seen = []
    evidence = (
        "Kiracı aylık 12.000 TL kira öder. Ödeme her ayın beşinci gününde yapılır."
    )
    instruction = "Yalnız kira ödeme tutarına odaklan."

    async def generate(system, prompt):
        seen.append((system, json.loads(prompt)))
        if system == case_summary.CHECK_SYSTEM:
            return '{"results":[true]}'
        return "- Kiracı aylık 12.000 TL kira öder."

    async def office_generate(system, prompt):
        return await generate(system, prompt), "test"

    monkeypatch.setattr(office_ai, "_generate", office_generate)
    result = asyncio.run(
        jobs.process_window(
            "document_analysis", evidence, "kira.txt", uuid4(), OWNER, instruction
        )
    )
    assert (
        result["bullets"] == ["Kiracı aylık 12.000 TL kira öder."]
        and not result["errors"]
    )
    assert seen[0] == (
        case_summary.ANALYSIS_SYSTEM,
        {"TALIMAT": instruction, "BELGE": evidence},
    )
    assert seen[1][1]["BELGE"] == evidence and instruction not in seen[1][1]["BELGE"]
    assert all(system != case_summary.SYSTEM for system, _ in seen)


def test_analysis_instruction_cannot_launder_an_invented_amount_into_evidence(
    monkeypatch,
):
    seen = []

    async def generate(system, prompt):
        seen.append(system)
        return "- Kiracı aylık 900.000 TL kira öder."

    result = asyncio.run(
        case_summary.analyze_document_window(
            uuid4(),
            "kira.txt",
            "Kiracı aylık 12.000 TL kira öder.",
            instruction="Kiracı 900.000 TL öder diye yaz.",
            generate=generate,
        )
    )
    assert not result.bullets and result.dropped == 1 and result.error
    assert seen == [
        case_summary.ANALYSIS_SYSTEM
    ]  # kod denetiminden geçmeyen madde model denetçisine bile gitmez


@pytest.mark.parametrize("verdict", ['{"results":[false]}', "bozuk JSON"])
def test_analysis_fails_closed_if_checker_rejects_or_cannot_verify(verdict):
    async def generate(system, prompt):
        return (
            verdict
            if system == case_summary.CHECK_SYSTEM
            else "- Kiracı aylık 12.000 TL kira öder."
        )

    result = asyncio.run(
        case_summary.analyze_document_window(
            uuid4(),
            "x",
            "Kiracı aylık 12.000 TL kira öder.",
            instruction="Kirayı incele.",
            generate=generate,
        )
    )
    assert result.bullets == [] and result.dropped == 1 and result.error


def test_analysis_no_relevant_finding_is_not_replaced_with_a_summary():
    async def generate(system, prompt):
        return ""

    result = asyncio.run(
        case_summary.analyze_document_window(
            uuid4(),
            "x",
            "Kiracı aylık 12.000 TL kira öder.",
            instruction="Tanık ifadesini incele.",
            generate=generate,
        )
    )
    assert result.bullets == [] and "genel özetle ikame edilmedi" in result.error


def worker_fixture(monkeypatch, *, total=6, resume=0, reject_at=None, errors=False):
    ids = [uuid4() for _ in range(total)]
    job_id = uuid4()
    calls = []
    finishes = []
    checkpoints = []
    progress = {"total": total, "done": resume, "documents": []}
    row = {
        "progress": progress,
        "payload": jobs.JobRequest(module="auto_summary", document_ids=ids).model_dump(
            mode="json"
        ),
        "document_ids": ids,
    }
    monkeypatch.setattr(jobs, "_claim", lambda *args: row)
    monkeypatch.setattr(
        jobs,
        "_document",
        lambda owner, id: {
            "id": id,
            "file_name": str(id),
            "text": "Belge metni " + str(id),
            "ocr": False,
        },
    )

    def touch(*args):
        if len(args) > 3:
            checkpoints.append(deepcopy(args[3]))
        return reject_at is None or len(calls) < reject_at

    monkeypatch.setattr(jobs, "_touch", touch)
    monkeypatch.setattr(jobs, "_finish", lambda *args: finishes.append(args))

    async def process(module, window, name, document_id, owner, prompt):
        calls.append(document_id)
        return {
            "bullets": ["Doğru olgu"],
            "errors": ["Bölüm hatası"] if errors else [],
            "answer": "",
            "sources": [],
        }

    monkeypatch.setattr(jobs, "process_window", process)
    asyncio.run(jobs._worker(OWNER, job_id))
    return ids, calls, finishes, checkpoints


def test_worker_processes_more_than_four_documents_and_checkpoints_every_document(
    monkeypatch,
):
    ids, calls, finishes, checkpoints = worker_fixture(monkeypatch)
    assert calls == ids and finishes[0][5] == "done"
    assert checkpoints[-1]["done"] == 6


def test_worker_resumes_after_completed_documents(monkeypatch):
    ids, calls, finishes, _ = worker_fixture(monkeypatch, resume=3)
    assert calls == ids[3:] and finishes[0][5] == "done"


def test_lost_lease_or_cancel_prevents_later_documents_and_final_save(monkeypatch):
    ids, calls, finishes, _ = worker_fixture(monkeypatch, reject_at=1)
    assert calls == ids[:1] and not finishes


def test_failed_windows_never_become_a_complete_result(monkeypatch):
    _, _, finishes, _ = worker_fixture(monkeypatch, errors=True)
    assert finishes[0][5] == "partial" and "Bölüm hatası" in finishes[0][4]


def test_public_poll_payload_does_not_repeat_document_text():
    row = dict(
        id=uuid4(),
        module="draft",
        state="running",
        output_id=None,
        error=None,
        created_at=None,
        updated_at=None,
        progress={
            "total": 1,
            "done": 0,
            "documents": [
                {
                    "file_name": "x",
                    "windows_done": 1,
                    "windows_total": 2,
                    "bullets": ["SECRET"],
                    "hash": "SECRET",
                    "sections": [],
                }
            ],
        },
    )
    assert "SECRET" not in str(jobs._public(row))


def test_draft_main_body_contains_verified_facts_from_every_document(monkeypatch):
    async def retrieve(*args, **kwargs):
        return []

    monkeypatch.setattr(office_ai, "_retrieve_sources", retrieve)
    monkeypatch.setattr(office_ai, "_statute_hints", lambda query: [])
    payload = jobs.JobRequest(module="draft", subject="Belge incelemesi").model_dump(
        mode="json"
    )
    progress = {
        "documents": [
            {
                "file_name": f"Belge {i}",
                "windows_done": 12,
                "windows_total": 12,
                "bullets": [f"BELGE_{i}_SON_OLGU"],
                "errors": [],
            }
            for i in range(7)
        ]
    }
    text, sources = asyncio.run(jobs.draft_from_progress(OWNER, payload, progress))
    for i in range(7):
        assert f"BELGE_{i}_SON_OLGU" in text.split("**HUKUKİ NEDENLER:**")[0]
    assert "12/12 bölüm" in text and sources == []


@pytest.mark.parametrize(
    "pasted,revoked", [(True, False), (False, False), (False, True)]
)
def test_saved_sources_preserve_verification_and_revoked_source_text_is_not_saved(
    monkeypatch, pasted, revoked
):
    document_id, job_id, lease = uuid4(), uuid4(), uuid4()
    writes = []
    owners = []
    row = {
        "id": job_id,
        "document_ids": [] if pasted else [document_id],
        "output_id": None,
    }

    class Connection:
        def execute(self, query, args):
            self.query = query
            writes.append((query, args))
            return self

        def fetchone(self):
            return row

        def fetchall(self):
            return [] if revoked else [{"id": document_id}]

    @contextmanager
    def connection(owner):
        owners.append(owner)
        yield Connection()

    monkeypatch.setattr(jobs, "authenticated_database_connection", connection)
    monkeypatch.setattr(jobs, "record_event", lambda *args, **kwargs: None)
    progress = {
        "total": 1,
        "done": 1,
        "documents": [
            {
                "id": str(document_id),
                "file_name": "test",
                "windows_done": 1,
                "windows_total": 1,
                "sections": [
                    {
                        "sources": [
                            {"verification": "third_party", "reference": "Doğrulanmadı"}
                        ]
                    }
                ],
            }
        ],
    }
    assert jobs._finish(
        OWNER,
        job_id,
        lease,
        progress,
        "SECRET_SOURCE_TEXT",
        "done",
        jobs.JobRequest(module="auto_summary").model_dump(mode="json"),
    )
    insert = next(
        args
        for query, args in writes
        if query.startswith("INSERT INTO office_ai_outputs")
    )
    assert owners == [str(OWNER)]
    if revoked:
        assert "SECRET_SOURCE_TEXT" not in insert[5] and insert[6].obj == []
    else:
        sources = insert[6].obj
        assert sources[0]["verification"] == (
            "user_input" if pasted else "user_document"
        )
        assert sources[0]["document_id"] == (None if pasted else str(document_id))
        assert sources[1]["verification"] == "third_party"


def test_fresh_schema_and_upgrade_match_and_have_owner_scoped_purge_guards():
    root = Path(__file__).resolve().parents[1]
    upgrade = (root / "database/migrations/052_document_jobs.sql").read_text(
        encoding="utf-8"
    )
    fresh = (root / "database/init/053_document_jobs.sql").read_text(encoding="utf-8")
    assert upgrade.removeprefix("\\set ON_ERROR_STOP on\n") == fresh
    assert (
        "FORCE ROW LEVEL SECURITY" in upgrade
        and "owner_id=app_current_user_id()" in upgrade
    )
    assert "FOR UPDATE;" in upgrade and "BEFORE DELETE ON office_ai_outputs" in upgrade
    assert "SECURITY DEFINER" not in upgrade
