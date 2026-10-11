"""Safety and relevance regressions, synthetic fixtures only; no network/DB."""
from dataclasses import replace
import pytest

from api.ai.evidence_selection import evidence_candidates, render_selection, Evidence, selection_prompt
from api.ai.passages import sentence_score
from api.ai.rag import generate_grounded_answer
from api.ai.verification import verify_answer
from tests.factories import court_decision_context


@pytest.mark.parametrize('text', [
    '6. Bölge Adliye Mahkemesi bu koşulun bulunmadığını belirtmiştir.',
    'İzmir 12. Aile Mahkemesi raporu değerlendirmiştir.',
    'Başvuru İİK m. 67/2 kapsamında değerlendirilmiştir.',
    'Bir koşul mevcut değildir. İkinci koşul ayrıca aranır.',
])
def test_verbatim_sentences_survive_numbered_paragraphs_and_abbreviations(text):
    context = court_decision_context(content=text)
    from api.ai.source_support import _sentences
    for sentence in _sentences(text, include_tail=False):
        assert verify_answer(f'{sentence} [K1]', [context]).grounded


def test_citation_does_not_validate_an_invented_or_negated_claim():
    context = court_decision_context(content='Ortak velayet koşulu mevcut değildir.')
    assert not verify_answer('Ortak velayet koşulu mevcuttur. [K1]', [context]).grounded
    assert not verify_answer('6. Mahkeme bu iddiayı kabul etmiştir. [K1]', [context]).grounded


@pytest.mark.parametrize('raw', [
    '{"evidence_ids":["E99"]}', '{"evidence_ids":[1]}', '{"evidence_ids":"E1"}',
    'uydurma hüküm [K1]', '{"evidence_ids":[{}]}', '[]',
])
def test_untrusted_model_output_cannot_supply_evidence(raw):
    assert render_selection(raw, [Evidence('E1', 1, 'Tam kaynak cümlesi.')]) == ''


def test_selection_resolves_only_server_owned_text_and_deduplicates():
    evidence = [Evidence('E1', 3, 'Kaynakta koşul mevcut değildir.')]
    assert render_selection('{"evidence_ids":["E1","E1"]}', evidence) == 'Kaynakta koşul mevcut değildir. [K3]'


def test_duration_rank_prefers_start_and_duration_to_procedural_boilerplate():
    q = 'İtirazın iptali davası süresi nedir?'
    rule = 'İtirazın iptali davası tebliğden itibaren iki hafta içinde açılır.'  # synthetic
    boilerplate = 'İtirazın iptali davası süresinde açılmıştır.'
    assert sentence_score(rule, q) > sentence_score(boilerplate, q)


def test_candidates_keep_third_party_warning_and_drop_allegation():
    context = replace(court_decision_context(content='Ortak velayet verilmesini talep ve dava etmiştir. Ortak velayet bakımından çocuğun yararına ilişkin rapor değerlendirilmelidir.'), verification='third_party')
    evidence = evidence_candidates('Ortak velayet şartları?', [context])
    assert all('talep ve dava' not in e.text for e in evidence)
    assert 'doğrulanmadı' in selection_prompt('Ortak velayet?', [context], evidence)


def test_generate_uses_one_short_selection_not_legal_prose_repair():
    context = court_decision_context()
    class Provider:
        calls = 0
        def generate(self, **kwargs):
            self.calls += 1
            return '{"evidence_ids":["E1"]}'
    provider = Provider()
    text = generate_grounded_answer(provider, question='Kıdem tazminatı?', contexts=[context])
    assert provider.calls == 1
    assert verify_answer(text, [context]).grounded


def test_empty_or_cut_evidence_never_falls_back_to_an_invented_answer():
    class Provider:
        def generate(self, **kwargs):
            raise AssertionError('No evidence: no model call')
    text = generate_grounded_answer(Provider(), question='Ortak velayet?', contexts=[court_decision_context(content='Ortak velayet ' * 100)])
    assert text == 'Kaynaklarda yeterli bilgi bulunmuyor.'


def test_matching_statute_survives_independent_lexical_timeout(monkeypatch):
    from api.ai import retrieval
    import psycopg
    calls = []
    context = court_decision_context(content='İtirazın iptali davası iki hafta içinde açılır.')
    def execute(connection, sql, params, **kwargs):
        calls.append((sql, params, kwargs))
        # Sözcük aramasının katmanlı yeniden denemesi de zaman aşımına uğrar (soğuk disk).
        if len(calls) >= 2:
            raise psycopg.errors.QueryCanceled('optional intent lookup timed out')
        return [context]
    monkeypatch.setattr(retrieval, '_execute_retrieval', execute)
    result = retrieval.retrieve_contexts(object(), question='İtirazın iptali davası süresi nedir?', top_k=6)
    assert result == [context]  # successful primary retrieval survives
    assert len(calls) == 4  # ilişkili madde + sözcük + katmanlı yeniden deneme + yalnız resmî katman denemesi
    assert calls[1][2]['timeout'] == '8s'
    assert '_tiered(' in calls[2][0]
    assert calls[0][2]['timeout'] == '3s'
    assert calls[0][1]['law_no'] == '2004'
    assert calls[0][1]['article_no'] == '67'
