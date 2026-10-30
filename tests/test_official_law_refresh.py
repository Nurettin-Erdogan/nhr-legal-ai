import pytest

from ingestion.text import content_hash
from scripts.refresh_official_law import official_article, preview
from scripts.refresh_official_law import valid_document_url, resolve_document_url

FIRST = 'MADDE 1- Bu Kanun kapsamındaki uyuşmazlıklarda aşağıdaki hükümler uygulanır.'
SECOND = 'MADDE 2- Süre otuz gündür. Ancak başvuru süresinde yapılmalıdır.'
FULL = FIRST + '\n\n' + SECOND


def row(article='1', text=FIRST):
    return dict(source=dict(id='id', raw_text=text, content_hash=content_hash(text), revision=1),
                details=dict(article_no=article))


def test_exact_extraction_does_not_include_next_article_or_borrow_its_identity():
    assert official_article(FULL, '1') == FIRST
    assert official_article(FULL, '2') == SECOND
    with pytest.raises(ValueError):
        official_article(FULL, '1/A')


def test_ambiguous_pdf_heading_is_not_auto_replaced():
    with pytest.raises(ValueError):
        official_article(FULL + '\n' + FIRST, '1')


def test_changed_condition_requires_new_revision_not_similarity_verification():
    payload, digest = preview('123', ['2'], FULL, [row('2', SECOND.replace('otuz', 'on'))])
    assert payload['entries'][0]['operation'] == 'new_official_revision'
    assert payload['entries'][0]['official_text'] == SECOND
    assert len(digest) == 64


def test_exact_existing_text_is_not_rewritten_and_changed_input_changes_digest():
    payload, digest = preview('123', ['1'], FULL, [row()])
    assert payload['entries'][0]['operation'] == 'verify_exact'
    _, different = preview('123', ['1'], FULL, [row(text=FIRST + ' Yeni cümle.')])
    assert digest != different


def test_wrong_stored_identity_or_duplicate_current_source_aborts_before_apply():
    with pytest.raises(ValueError):
        preview('123', ['1'], FULL, [row(text=SECOND)])
    with pytest.raises(ValueError):
        preview('123', ['1'], FULL, [row(), row()])


def test_explicit_identity_repair_uses_official_target_and_marks_old_label_error():
    payload, _ = preview('123', ['1'], FULL, [row(text=SECOND)], repair_identities=True)
    entry = payload['entries'][0]
    assert entry['identity_correction'] is True
    assert entry['official_text'] == FIRST
    assert entry['operation'] == 'new_official_revision'


def test_old_statute_series_uses_observed_official_link_not_a_guessed_fifth_series():
    url = 'https://www.mevzuat.gov.tr/MevzuatMetin/1.3.1219.pdf'
    assert valid_document_url(url, '1219')
    assert resolve_document_url('1219', [dict(source=dict(metadata=dict(mbs_verification=dict(pdf_url=url))))]) == url


@pytest.mark.parametrize('url', [
    'https://evil.test/MevzuatMetin/1.3.1219.pdf',
    'https://www.mevzuat.gov.tr/MevzuatMetin/1.3.1220.pdf',
    'http://www.mevzuat.gov.tr/MevzuatMetin/1.3.1219.pdf',
])
def test_official_link_binding_rejects_other_host_law_or_plain_http(url):
    assert not valid_document_url(url, '1219')
