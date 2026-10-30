"""The screenshot's broad rights question cannot collapse to notice pay alone.

These are synthetic evidence fixtures, not an entitlement table. Every returned
claim must still pass the existing exact evidence and independent checker gates.
"""
import json
from contextlib import contextmanager
from dataclasses import replace
from uuid import UUID

import pytest

from api import statute_hints
from api.ai import pipeline, synthesis
from api.ai.authority import answer_uses_primary_basis, primary_legislation_markers
from api.ai.discovery import select_answer_contexts
from tests.factories import legislation_context, document_context
from tests.test_synthesis import Provider, approved, draft


QUESTION = "işten çıkarıldım haklarım nelerdir"
RULES = (
    ("1475", "14", "İşveren tarafından kanunda belirtilen hallerde sona erdirilen hizmet akitlerinde her geçen tam yıl için işverence işçiye 30 günlük ücreti tutarında kıdem tazminatı ödenir."),
    ("4857", "17", "Bildirim şartına uymayan taraf, bildirim süresine ilişkin ücret tutarında tazminat ödemek zorundadır."),
    ("4857", "32", "İş sözleşmelerinin sona ermesinde, işçinin ücreti ile sözleşme ve Kanundan doğan para ile ölçülmesi mümkün menfaatlerinin tam olarak ödenmesi zorunludur."),
    ("4857", "59", "İş sözleşmesinin sona ermesi halinde işçinin hak kazanıp da kullanmadığı yıllık izin sürelerine ait ücreti ödenir."),
    ("4857", "18", "Otuz veya daha fazla işçi çalıştıran işyerinde altı aylık kıdemi olan işçinin belirsiz süreli sözleşmesini fesheden işveren geçerli bir sebebe dayanmak zorundadır."),
    ("4857", "20", "Fesih bildiriminde sebep gösterilmediği iddiasıyla işçi bir ay içinde işe iade talebiyle arabulucuya başvurmak zorundadır."),
)


def contexts():
    return [replace(legislation_context(content=text), law_no=law, article_no=article,
                    source_id=UUID(int=i), chunk_id=UUID(int=i))
            for i, (law, article, text) in enumerate(RULES, 1)]


@pytest.mark.parametrize("question", [QUESTION, "İşten çıkarıldım, haklarım neler?",
    "İş sözleşmem feshedildi hangi haklarım var?", "İşten atıldım neleri talep edebilirim?"])
def test_open_rights_request_gets_all_source_subjects(question):
    assert len(statute_hints.employment_rights_groups(question)) == 5
    assert {(h.law_no, h.article_no) for h in statute_hints.suggest(question)} == {
        (law, article) for law, article, _ in RULES}


@pytest.mark.parametrize("question", ["İşten çıkarıldım sadece ihbar haklarım nelerdir?",
    "2016 yılında işten çıkarıldım haklarım neler?", "İşten çıkarıldım haklarım için Yargıtay kararları nelerdir?",
    "4857 sayılı Kanunun 17. maddesindeki haklarım nelerdir?", "İşten çıkarıldım ne kadar tazminat alırım?",
    "Kiracı olarak haklarım nelerdir?"])
def test_narrow_historical_case_law_and_other_subjects_are_not_expanded(question):
    assert statute_hints.employment_rights_groups(question) == ()


def test_verified_available_subjects_cannot_be_answered_with_notice_pay_only():
    sources = contexts()
    assert primary_legislation_markers(QUESTION, sources) == set(range(1, 7))
    assert not answer_uses_primary_basis(QUESTION, sources[1:2], sources)
    # Either verified article in the dismissal-review family suffices.
    assert answer_uses_primary_basis(QUESTION, sources[:5], sources)
    assert answer_uses_primary_basis(QUESTION, [*sources[:4], sources[5]], sources)
    assert not answer_uses_primary_basis(QUESTION, sources[:4], sources)


def test_missing_or_unverified_subject_is_never_invented_as_evidence():
    sources = contexts()[:2]
    sources.append(replace(contexts()[2], verification="third_party"))
    assert primary_legislation_markers(QUESTION, sources) == {1, 2}
    assert answer_uses_primary_basis(QUESTION, sources[:2], sources)


def test_private_document_scope_does_not_require_a_public_rights_checklist():
    sources = [document_context(), *contexts()]
    assert primary_legislation_markers(QUESTION, sources) == set()
    assert synthesis._answer_focus(QUESTION, sources, []) == []


def test_topic_loader_reads_six_but_keeps_the_normal_two_article_limit_elsewhere(monkeypatch):
    sources = {(c.law_no, c.article_no): c for c in contexts()}
    calls = []

    @contextmanager
    def transaction_scope():
        yield

    class Connection:
        transaction = staticmethod(transaction_scope)

    def retrieve(connection, sql, params, **kwargs):
        ref = params["law_no"], params["article_no"]
        calls.append(ref)
        if ref == ("4857", "32"):
            base = sources[ref]
            return [replace(base, chunk_id=UUID(int=99), content="Genel anlamda ücret bir karşılıktır."), base]
        return [sources[ref]]

    monkeypatch.setattr("api.ai.retrieval._execute_retrieval", retrieve)
    rows = pipeline._case_statute_contexts(Connection(), QUESTION, [])
    selected = select_answer_contexts(rows, 6, question=QUESTION)
    assert len(calls) == 6 and len(selected) == 6
    assert selected[2].content == sources[("4857", "32")].content
    calls.clear()
    pipeline._case_statute_contexts(Connection(), "İşten çıkarıldım ihbar tazminatım nedir?", [])
    assert len(calls) == 2


def test_partial_draft_is_repaired_to_cover_actual_evidence_before_independent_check():
    sources = contexts()
    complete = {"claims": [{"text": c.content, "evidence": [{"source": i, "quote": c.content}]}
                            for i, c in enumerate(sources[:5], 1)], "question": None}
    writer = Provider(draft(sources[1].content, (2, sources[1].content)), complete)
    checker = Provider(approved(5))
    result = synthesis.synthesize_answer(writer, checker_provider=checker, question=QUESTION,
        contexts=sources, max_context_chars=16000)
    assert result and result.grounded and len(result.contexts) == 5
    repair = json.loads(writer.calls[1]["prompt"])
    assert repair["rejection"]["category"] == "answer_focus"
    assert len(repair["answer_focus"]) == 5
    assert len(checker.calls) == 1


def test_no_checker_call_can_publish_the_screenshot_partial_answer():
    sources = contexts()
    writer = Provider(draft(sources[1].content, (2, sources[1].content)))
    checker = Provider(approved())
    diagnostics = {}
    result = synthesis.synthesize_answer(writer, checker_provider=checker, question=QUESTION,
        contexts=sources, max_context_chars=16000, repair_attempts=0, diagnostics=diagnostics)
    assert result is None and diagnostics["reason"] == "answer_focus"
    assert checker.calls == []


def test_repair_receives_both_unsafe_followup_and_unsupported_threshold():
    source = replace(legislation_context(content="Başvuru süresi tebliğ tarihinden başlar."),
                     law_no="9999", article_no="1")
    bad = {"claims": [{"text": "Başvuru en az bir yıl sonra yapılır.",
                       "evidence": [{"source": 1, "quote": source.content}]}],
           "question": "Tebliğ hangi gün? Başvurunuz hangi gün?"}
    writer = Provider(bad, draft(source.content, (1, source.content)))
    checker = Provider(approved())
    result = synthesis.synthesize_answer(writer, checker_provider=checker, question="Başvuru süresi?", contexts=[source])
    assert result and result.grounded
    repair = json.loads(writer.calls[1]["prompt"])["rejection"]
    assert repair["checks"] == ["clarification_single_neutral_question"]
    assert "number_or_unit" in repair["previous_claim_failures"][0]["checks"]
    assert len(checker.calls) == 1


def test_missing_subjects_cannot_be_silently_presented_as_complete_overview():
    sources = contexts()[:2]
    value = {"claims": [{"text": c.content, "evidence": [{"source": i, "quote": c.content}]}
                        for i, c in enumerate(sources, 1)], "question": None}
    writer, checker = Provider(value), Provider(approved(2))
    result = synthesis.synthesize_answer(writer, checker_provider=checker, question=QUESTION, contexts=sources)
    assert result and result.grounded and "doğrulayamıyorum" in result.text
    coverage = json.loads(writer.calls[0]["prompt"])["source_coverage"]
    assert coverage["complete"] is False and len(coverage["unavailable_reference_groups"]) == 3
