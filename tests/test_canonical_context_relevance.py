"""A governing provision need not repeat the user's everyday legal label."""
from dataclasses import replace

from api.ai.relevance import context_relevant
from tests.factories import legislation_context


QUESTION = 'İşe iade davasının şartları nelerdir?'
BODY = ('İşveren, belirsiz süreli iş sözleşmesini feshederken işçinin yeterliliğinden '
        'veya davranışlarından kaynaklanan geçerli bir sebebe dayanmak zorundadır.')


def test_actual_governing_article_remains_relevant_without_the_colloquial_label():
    source = replace(legislation_context(content=BODY), article_no='18')
    assert 'işe iade' not in BODY
    assert context_relevant(QUESTION, source)


def test_metadata_alone_cannot_promote_a_wrong_body_or_other_law():
    source = replace(legislation_context(content=BODY), article_no='18')
    assert not context_relevant(QUESTION, replace(source, content='Dernek genel kurulu yönetim kurulunu seçer.'))
    assert not context_relevant(QUESTION, replace(source, law_no='5362'))
    assert not context_relevant(QUESTION, replace(source, verification='third_party'))
