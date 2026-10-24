"""A genuine historical quotation must not displace the retrieved provision."""
from dataclasses import replace
from datetime import date

from api.ai.authority import primary_legislation_markers
from api.ai.evidence_selection import evidence_candidates, preserve_statutory_scope
from api.ai.explanation import explain_verified_answer, with_coverage_notice
from api.ai.verification import verify_answer
from tests.factories import court_decision_context, legislation_context

QUESTION = 'Kira sözleşmesinde TÜFE üzerinde artış istenirse ne yapılır?'
# Synthetic text, not legal advice or a copy of the statute.
RULE = 'Kira artışı bu sentetik örnekte tüketici fiyat endeksine bağlıdır.'
SCOPE = 'Bu kural yalnız belirtilen örnekte uygulanır. Ancak yabancı para istisnası saklıdır.'
OLD = 'Kira sözleşmesinde kira artışı üretici fiyat endeksine bağlıdır.'


def statute(content=RULE+' '+SCOPE):
    return replace(legislation_context(content=content), law_no='6098', article_no='344')


def old_case():
    return replace(court_decision_context(content=OLD), decision_date=date(2017,1,24))


def test_long_case_quotes_cannot_spend_the_primary_evidence_budget():
    contexts = [old_case(), statute()] + [old_case() for _ in range(10)]
    evidence = evidence_candidates(QUESTION, contexts, total_chars=160)
    assert evidence and all(e.marker == 2 for e in evidence)
    assert all('üretici' not in e.text for e in evidence)


def test_primary_clause_keeps_adjacent_conditions_without_query_keywords():
    contexts = [old_case(), statute()]
    text = preserve_statutory_scope(RULE+' [K2]', contexts, QUESTION)
    assert SCOPE.split('. ')[0] in text and 'istisnası saklıdır' in text
    checked = verify_answer(text, contexts, question=QUESTION)
    assert checked.grounded and checked.contexts == (contexts[1],)
    assert '[K1]' in checked.text  # citation renumbering still resolves correctly


def test_exact_old_quote_fails_even_though_its_citation_is_authentic():
    assert not verify_answer(OLD+' [K1]', [old_case(),statute()], question=QUESTION).grounded


def test_mixing_old_rule_with_primary_provision_does_not_pass():
    text = OLD+' [K1]\n'+RULE+' [K2]'
    assert not verify_answer(text,[old_case(),statute()],question=QUESTION).grounded


def test_cache_cannot_hide_the_available_primary_source_by_passing_only_cited_contexts():
    context = old_case()
    assert not verify_answer(OLD+' [K1]', [context], question=QUESTION,
                             available_contexts=[statute(),context]).grounded


def test_an_unverified_statute_is_not_an_authoritative_anchor():
    assert primary_legislation_markers(QUESTION,[replace(statute(),verification='third_party')]) == set()


def test_unrelated_article_is_not_promoted_merely_because_it_is_legislation():
    assert primary_legislation_markers(QUESTION,[replace(statute(),article_no='345')]) == set()


def test_explicit_case_research_remains_available():
    question = 'Sayıştay kararında kira artışı nasıl değerlendirilmiş?'
    assert primary_legislation_markers(question,[statute(),old_case()]) == set()
    assert evidence_candidates(question,[old_case()])


def test_retrieved_historical_provision_is_not_silently_replaced_by_current_text():
    historical = replace(statute(), version_date=date(2017,1,1), effective_to=date(2018,12,31))
    text = preserve_statutory_scope(RULE+' [K1]',[historical],QUESTION)
    answer = verify_answer(text,[historical],question=QUESTION)
    assert answer.grounded and answer.contexts[0].version_date == date(2017,1,1)


def test_qualification_exception_does_not_bypass_source_support():
    text = RULE+' [K1]\nAncak tüm kiracılar her zaman muaf tutulur. [K1]'
    assert not verify_answer(text,[statute()],question=QUESTION).grounded


def test_oversized_article_abstains_instead_of_clipping_conditions():
    content = RULE+' '+ ' '.join(f'Ancak sentetik koşul {i} ayrıca saklıdır.' for i in range(250))
    assert preserve_statutory_scope(RULE+' [K1]',[statute(content)],QUESTION) == ''


def test_qualified_statute_cannot_be_squeezed_into_a_lossy_four_claim_summary():
    text = preserve_statutory_scope(RULE+' [K1]',[statute()],QUESTION)
    answer = verify_answer(text,[statute()],question=QUESTION)
    class Provider:
        def generate(self, **kwargs):
            raise AssertionError('Keep qualified provision verbatim')
    assert explain_verified_answer(Provider(),question=QUESTION,answer=answer) == answer


def test_rule_only_answer_discloses_missing_procedural_steps():
    answer = verify_answer(RULE+' [K1]',[statute()],question=QUESTION)
    result = with_coverage_notice(answer,QUESTION)
    assert 'başvuru adımlarını bu kaynaklarla doğrulayamadım' in result.text
    assert result.contexts == answer.contexts and result.grounded


def test_actual_written_notice_step_is_not_mislabelled_as_missing_in_a_general_rent_answer():
    from dataclasses import replace
    from tests.factories import legislation_context
    content = "Kiraya veren kiracıya yazılı bir süre verip ödenmezse sözleşmeyi feshedeceğini bildirebilir."
    context = replace(legislation_context(content=content), law_no="6098", article_no="315")
    question = "Kiracı kirayı ödemezse ev sahibi ne yapabilir?"
    answer = verify_answer(content + " [K1]", [context], question=question)
    assert answer.grounded
    assert with_coverage_notice(answer, question).text == answer.text


def test_notice_step_does_not_claim_to_cover_an_explicit_court_procedure_request():
    from dataclasses import replace
    from tests.factories import legislation_context
    content = "Kiraya veren kiracıya yazılı bir süre verip ödenmezse sözleşmeyi feshedeceğini bildirebilir."
    context = replace(legislation_context(content=content), law_no="6098", article_no="315")
    answer = verify_answer(content + " [K1]", [context])
    result = with_coverage_notice(answer, "Kiracı kirayı ödemiyorsa mahkemede ne yapabilirim?")
    assert "başvuru adımlarını bu kaynaklarla doğrulayamadım" in result.text


def test_model_source_counter_reflects_primary_selection_not_discovery_pool():
    from api.ai.discovery import select_answer_contexts, search_summary
    pool = [old_case(), statute()]
    selected = select_answer_contexts(pool, 6, question=QUESTION)
    assert selected == [pool[1]]
    summary = search_summary(pool, pool, selected, {}, {})
    assert summary['candidate_documents'] == summary['verified_documents'] == 2
    assert summary['selected_documents'] == 1
