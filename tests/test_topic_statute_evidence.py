"""Sorunun konusunu düzenleyen resmî madde cümlesi, soru sözcüklerini taşımasa da aday olur ve alakalı sayılır.

Ölçülen sorun (2026-10-08): "İş sözleşmesinin haksız feshinde işçi hangi tazminatları talep edebilir?" sorusunda İş Kanunu
m. 17 getiriliyor ama cevap cümlesi ("Bildirim şartına uymayan taraf … tazminat ödemek zorundadır") sorudaki sözcükleri
taşımadığı için eleniyor, cevap yalnız mahkeme kararlarına dayanıyordu.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from uuid import UUID

import psycopg
import pytest

from api.ai import pipeline
from api.ai.authority import on_statute_topic, topic_statute_terms
from api.ai.evidence_selection import evidence_candidates
from api.ai.verification import verify_answer
from api.schemas import AIAnswerRequest
from tests.factories import court_decision_context, legislation_context

QUESTION = "İş sözleşmesinin haksız feshinde işçi hangi tazminatları talep edebilir?"
NOTICE_PAY = "Bildirim şartına uymayan taraf, bildirim süresine ilişkin ücret tutarında tazminat ödemek zorundadır."
OTHER_PARAGRAPH = "Bu süreler asgari olup sözleşmeler ile artırılabilir."
DECISION = "İş sözleşmesinin haksız feshinde işçi kıdem tazminatı ile ihbar tazminatını talep edebilir."


def _article(law_no="4857", article_no="17", content=f"{NOTICE_PAY} {OTHER_PARAGRAPH}", **changes):
    return replace(
        legislation_context(content=content), law_no=law_no, article_no=article_no,
        title=f"İş Kanunu m. {article_no}", article_title="Süreli fesih", **changes,
    )


def _decision(content=DECISION):
    return replace(court_decision_context(), content=content)


def test_the_topic_statute_sentence_is_a_candidate_and_comes_before_decisions():
    evidence = evidence_candidates(QUESTION, [_decision(), _article()])

    assert [(item.marker, item.text) for item in evidence] == [(2, NOTICE_PAY), (1, DECISION)]


def test_topic_statute_sentences_are_offered_in_the_order_of_the_article():
    # Soru sözcüklerini taşıyan ayrıntı fıkrası (hesap) maddenin sonundadır; asıl kural ondan önce gelir ve önce sunulur.
    detail = "Bu maddeye göre ödenecek tazminatların ve bildirim ücretinin hesabında işçi lehine sözleşmesinden doğan menfaatler gözetilir."
    article = _article(content=f"{NOTICE_PAY} {OTHER_PARAGRAPH} {detail}")

    evidence = evidence_candidates(QUESTION, [_decision(), article])

    assert [item.text for item in evidence] == [NOTICE_PAY, detail, DECISION]


def test_a_paragraph_of_the_article_on_another_subject_is_still_not_a_candidate():
    evidence = evidence_candidates(QUESTION, [_article()])

    assert OTHER_PARAGRAPH not in [item.text for item in evidence]


@pytest.mark.parametrize(
    "context",
    [
        _article(article_no="41"),  # konunun maddesi değil
        _article(law_no="6098"),  # başka kanunun aynı numaralı maddesi
        _article(verification="third_party"),  # doğrulanmamış metin bu kolaylıktan yararlanmaz
    ],
)
def test_only_the_verified_article_of_the_topic_gets_this_treatment(context):
    assert topic_statute_terms(QUESTION, [context]) == {}
    assert evidence_candidates(QUESTION, [context]) == []


def test_a_question_asking_for_case_law_does_not_push_the_statute_forward():
    question = "Haksız fesihte işçinin tazminatı hakkında Yargıtay kararları nelerdir?"

    assert topic_statute_terms(question, [_article()]) == {}


def test_a_question_without_a_known_topic_changes_nothing():
    assert topic_statute_terms("Ortak velayet şartları nelerdir?", [_article()]) == {}


def test_topic_terms_are_matched_per_sentence():
    terms = topic_statute_terms(QUESTION, [_article()])[1]

    assert on_statute_topic(NOTICE_PAY, terms) is True
    assert on_statute_topic(OTHER_PARAGRAPH, terms) is False


def test_topic_sentences_do_not_take_the_whole_budget():
    def chunk(part):
        return _article(chunk_id=UUID(int=part), content=" ".join(
            f"Bildirim süresine ilişkin {part}/{index} sayılı kural uyarınca işveren işçiye ücretini öder ve bu ödeme tazminat sayılır."
            for index in range(1, 40)
        ))

    evidence = evidence_candidates(
        QUESTION, [chunk(1), chunk(2), chunk(3), _decision()], per_source_chars=1200, total_chars=2000,
    )

    statute_chars = sum(len(item.text) for item in evidence if item.marker != 4)
    assert DECISION in [item.text for item in evidence]
    assert 0 < statute_chars <= 2000 * 0.55


def test_an_answer_quoting_the_topic_statute_passes_the_relevance_gate():
    verified = verify_answer(f"{NOTICE_PAY} [K1]", [_article()], question=QUESTION)

    assert verified.unsupported_claims == ()
    assert [context.article_no for context in verified.contexts] == ["17"]


def test_the_same_sentence_from_an_article_outside_the_topic_is_still_rejected():
    verified = verify_answer(f"{NOTICE_PAY} [K1]", [_article(article_no="41")], question=QUESTION)

    assert verified.unsupported_claims != ()


def test_a_sentence_the_article_does_not_contain_is_rejected_even_for_the_topic_statute():
    invented = "Bildirim şartına uymayan işveren işçiye on iki aylık ücret tutarında tazminat öder."

    verified = verify_answer(f"{invented} [K1]", [_article()], question=QUESTION)

    assert verified.unsupported_claims != ()


# --- Karar araması zaman aşımına uğrarsa konunun maddesiyle cevap -------------------------------------------------------


@contextmanager
def _plain():
    yield object()


def _timeout(*args, **kwargs):
    raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")


def _retrieve(monkeypatch, *, statutes, as_of=None, statutes_on_timeout=True):
    monkeypatch.setattr(pipeline, "database_connection", lambda: _plain())
    monkeypatch.setattr(pipeline, "retrieve_contexts", _timeout)
    monkeypatch.setattr(pipeline, "_case_statute_contexts", lambda connection, text, named: list(statutes))
    diagnostics: dict = {}
    result = pipeline._retrieve(
        AIAnswerRequest(question=QUESTION, as_of=as_of), user_id=None, query_embedding=None, top_k=5,
        embedding_model="m", diagnostics=diagnostics, statutes_on_timeout=statutes_on_timeout,
    )
    return result, diagnostics


def test_when_decision_search_times_out_the_topic_statute_still_answers_and_the_gap_is_reported(monkeypatch):
    result, diagnostics = _retrieve(monkeypatch, statutes=[_article()])

    assert [context.article_no for context in result] == ["17"]
    assert diagnostics["partial"] is True
    assert diagnostics["decision_search"] == "timeout"


def test_a_timeout_without_a_topic_statute_is_still_a_failure(monkeypatch):
    with pytest.raises(psycopg.errors.QueryCanceled):
        _retrieve(monkeypatch, statutes=[])


def test_the_first_attempt_is_retried_instead_of_falling_back(monkeypatch):
    with pytest.raises(psycopg.errors.QueryCanceled):
        _retrieve(monkeypatch, statutes=[_article()], statutes_on_timeout=False)


def test_a_dated_question_never_falls_back_to_the_current_statute(monkeypatch):
    from datetime import date

    with pytest.raises(psycopg.errors.QueryCanceled):
        _retrieve(monkeypatch, statutes=[_article()], as_of=date(2015, 1, 1))


def test_only_the_last_attempt_may_fall_back(monkeypatch):
    import asyncio

    flags = []

    def retrieve(request, *, statutes_on_timeout, **kwargs):
        flags.append(statutes_on_timeout)
        if len(flags) == 1:
            raise psycopg.errors.QueryCanceled("zaman aşımı")
        return ["madde"]

    monkeypatch.setattr(pipeline, "_retrieve", retrieve)

    assert asyncio.run(pipeline._retrieve_with_warm_retry(object(), top_k=3)) == ["madde"]
    assert flags == [False, True]


# --- Asıl kural cümlesi: model maddeden başka cümle seçip kuralı atlarsa eklenir --------------------------------------------

from api.ai.evidence_selection import Evidence, include_rule_sentences  # noqa: E402
from api.ai.rag import generate_grounded_answer  # noqa: E402

PERIODS = "İş sözleşmeleri; işi altı aydan az sürmüş olan işçi için, bildirimin diğer tarafa yapılmasından başlayarak iki hafta sonra feshedilmiş sayılır."
SEVERANCE = (
    "Bu Kanuna tabi işçilerin hizmet akitlerinin feshedilmesi hallerinde işçinin işe başladığı tarihten itibaren her geçen tam yıl "
    "için işverence işçiye 30 günlük ücreti tutarında kıdem tazminatı ödenir."
)


def _answering(*selected):
    """Soru, kaynaklar ve aday listesi: m. 17 (süreler + ihbar kuralı), 1475 m. 14 ve bir karar."""
    contexts = [_article(content=f"{PERIODS} {NOTICE_PAY}"), _article(law_no="1475", article_no="14", content=SEVERANCE), _decision()]
    evidence = [Evidence("E1", 1, PERIODS), Evidence("E2", 1, NOTICE_PAY), Evidence("E3", 2, SEVERANCE), Evidence("E4", 3, DECISION)]
    by_id = {item.id: item for item in evidence}
    answer = "\n\n".join(f"{by_id[i].text} [K{by_id[i].marker}]" for i in selected)
    return answer, contexts, evidence


def test_the_rule_sentence_is_added_before_the_detail_the_model_picked_from_the_same_article():
    answer, contexts, evidence = _answering("E1", "E3")

    result = include_rule_sentences(answer, QUESTION, contexts, evidence)

    assert result.split("\n\n") == [f"{NOTICE_PAY} [K1]", f"{PERIODS} [K1]", f"{SEVERANCE} [K2]"]  # kural önce, ayrıntı sonra
    assert verify_answer(result, contexts, question=QUESTION).unsupported_claims == ()  # eklenen cümle kaynaktan aynen


def test_nothing_is_added_when_the_model_took_nothing_from_that_article():
    answer, contexts, evidence = _answering("E4")  # yalnız karar: soru maddeyi ilgilendirmiyor olabilir, kural zorla sokulmaz

    assert include_rule_sentences(answer, QUESTION, contexts, evidence) == answer


def test_an_answer_that_already_has_the_rule_sentence_is_left_alone():
    answer, contexts, evidence = _answering("E2", "E3")

    assert include_rule_sentences(answer, QUESTION, contexts, evidence) == answer


def test_the_rule_sentence_must_be_among_the_candidates_and_from_the_verified_article():
    answer, contexts, evidence = _answering("E1")
    without_candidate = [item for item in evidence if item.id != "E2"]
    assert include_rule_sentences(answer, QUESTION, contexts, without_candidate) == answer  # aday olmayan cümle eklenmez

    unverified = [replace(contexts[0], verification="third_party"), *contexts[1:]]
    assert include_rule_sentences(answer, QUESTION, unverified, evidence) == answer  # doğrulanmamış metinden kural eklenmez


def test_case_law_and_explicit_article_questions_are_not_touched():
    answer, contexts, evidence = _answering("E1")

    assert include_rule_sentences(answer, "Haksız fesihte işçinin tazminatı hakkında Yargıtay kararları nelerdir?", contexts, evidence) == answer
    assert include_rule_sentences(answer, "4857 sayılı İş Kanunu madde 17 neyi düzenler?", contexts, evidence) == answer
    assert include_rule_sentences(answer, "Ortak velayet şartları nelerdir?", contexts, evidence) == answer  # konusu tabloda olmayan soru
    assert include_rule_sentences("", QUESTION, contexts, evidence) == ""


def test_generation_adds_the_rule_sentence_the_model_skipped():
    class _Provider:
        def generate(self, *, system_instruction, prompt):
            # Model m. 17'den yalnız süreleri ve kıdem cümlesini seçer; ihbar kuralını atlar (ölçülen davranış).
            ids = [line.split(" ", 1)[0] for line in prompt.split("\n") if line.startswith("E")]
            texts = {line.split(" ", 1)[0]: prompt.split("\n")[index + 1] for index, line in enumerate(prompt.split("\n")) if line.startswith("E")}
            chosen = [i for i in ids if texts[i] in (PERIODS, SEVERANCE)]
            return '{"evidence_ids": ' + str(chosen).replace("'", '"') + "}"

    _, contexts, _ = _answering("E1")

    answer = generate_grounded_answer(_Provider(), question=QUESTION, contexts=contexts)

    lines = answer.split("\n\n")
    assert lines[0].startswith(NOTICE_PAY) and any(line.startswith(PERIODS) for line in lines) and any(line.startswith(SEVERANCE) for line in lines)
    assert verify_answer(answer, contexts, question=QUESTION).unsupported_claims == ()


def test_every_anchor_is_long_enough_to_point_at_one_sentence_and_articles_do_not_disagree():
    from api import statute_hints

    seen: dict[tuple[str, str], str] = {}
    for topic in statute_hints.TOPICS:
        for hint in topic.hints:
            if not hint.anchor:
                continue
            assert len(hint.anchor) >= 14, (topic.name, hint.anchor)
            key = (hint.law_no, hint.article_no)
            assert seen.setdefault(key, hint.anchor) == hint.anchor, (topic.name, key)  # aynı maddeye iki farklı çapa verilmez
    assert seen[("4857", "17")] == "Bildirim şartına uymayan taraf"
