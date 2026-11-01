import json

import pytest

from api.ai.free_answer import _usable, plan_question, _uncovered_note
from api.ai.synthesis import _source_views
from api.ai.source_support import _sentences
from tests.factories import legislation_context
from tests.test_free_answer import Provider


@pytest.mark.parametrize('caption', [
    'Feshin geçerli sebebe dayandırılması',
    'Sözleşmenin feshinde usul',
    'Geçersiz sebeple yapılan feshin sonuçları',
    'b) İtirazın kesin olarak kaldırılması:28',
    'c) İtirazın geçici olarak kaldırılması:30',
    '2 – İtiraz sebepleri:',
    'III. TATİLLER VE TALİKLER\nTatiller:\n1 – Bütün borçlular hakkında:',
])
def test_complete_rule_is_not_lost_because_of_next_article_caption(caption):
    rule = 'Madde 67 - Başvuru tebliğ tarihinden itibaren yapılır.'
    original = legislation_context(content=rule + '\n\n' + caption)
    usable = _usable(original, 36000)
    assert usable is not None
    views = _source_views([usable], 36000)
    assert views
    assert ' '.join(views[0]['units']) == rule
    assert original.content.endswith(caption)
    # The entire original text remains in model context, including the caption.
    assert views[0]['text'] == original.content


@pytest.mark.parametrize('tail', [
    'Ancak başvuru süresi', 'Bu hak kullanılamaz', 'Başvuru ancak tebliğ halinde',
    'Ödeme en az otuz gün', 'Başvuru yapılır ve işçinin hakkı',
    'Başvuru zorunlu', 'Başvuru yapılması', 'Aksi halde başvuru hakkı',
])
def test_real_unfinished_rules_conditions_numbers_and_negations_are_not_captions(tail):
    source = legislation_context(content='Başvuru yapılır.\n\n' + tail)
    assert _usable(source, 36000) is None


def test_caption_after_formal_amendment_note_does_not_hide_the_article():
    source = legislation_context(content='Madde 20 - Başvuru tebliğden başlar.\n'
        '(İptal dördüncü fıkra: 19/10/2005 tarihli ve E.:2003/66, K.:2005/72 sayılı Kararı ile.)'
        '\n\nGeçersiz sebeple yapılan feshin sonuçları')
    assert _usable(source, 36000) is not None


def test_footnote_markers_preserve_sentence_and_decimal_boundaries():
    assert _sentences('Başvuru yapılır.29 Yeni cümle başlar.', include_tail=False) == [
        'Başvuru yapılır.29', 'Yeni cümle başlar.']
    assert _sentences('Tutar 12.50 TL olarak belirlenmiştir.', include_tail=False) == [
        'Tutar 12.50 TL olarak belirlenmiştir.']
    assert _sentences('Karar 19.10.2005 tarihinde verilmiştir.', include_tail=False) == [
        'Karar 19.10.2005 tarihinde verilmiştir.']


def test_planner_authority_hints_are_bounded_queries_not_legal_evidence():
    raw = {'legal': True, 'parts': [{'question': 'İtiraz sonrasında ne yapılabilir?',
        'queries': ['itirazın iptali', 'itirazın kaldırılması'],
        'references': [{'law_no': '2004', 'article_no': '67'}, {'law_no': '2004', 'article_no': '68'}]}]}
    result = plan_question(Provider(json.dumps(raw)), 'Borçlu itiraz ederse ne yapmalıyım?')
    assert result[0][1] == ('2004 sayılı Kanun m. 67', '2004 sayılı Kanun m. 68',
                           'itirazın iptali', 'itirazın kaldırılması')
    raw['parts'][0]['references'] = [{'law_no': '2004;DROP', 'article_no': '67'}]
    result = plan_question(Provider(json.dumps(raw)), 'Borçlu itiraz ederse ne yapmalıyım?')
    assert len(result[0][1]) == 2


def test_failed_research_does_not_claim_the_whole_corpus_lacks_a_rule():
    message = _uncovered_note(['İtiraz sonrasında ne yapılabilir?'], 'Borçlu itiraz ederse ne yapmalıyım?')
    assert 'bu araştırmada' in message
    assert 'bir hüküm bulamadığım' not in message
