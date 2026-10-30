from dataclasses import replace

from api.ai.provision_context import complete_provision
from tests.factories import legislation_context

FULL = 'MADDE 18/B- Kiracıya yazılı bildirim yapılır.\nAncak ödeme yapılırsa sözleşme devam eder.'


def test_cut_condition_is_restored_from_the_same_complete_canonical_article():
    context = replace(legislation_context(content=FULL[:64]), article_no='18/B')
    restored = complete_provision(context, FULL)
    assert restored and restored.content == FULL
    assert restored.chunk_id == context.chunk_id and restored.source_id == context.source_id


def test_formal_next_chapter_heading_is_not_a_fragment_of_this_article():
    context = replace(legislation_context(content=FULL[:64]), article_no='18/B')
    restored = complete_provision(context, FULL + '\nALTINCI BÖLÜM\nArabulucular Sicili')
    assert restored and restored.content == FULL


def test_wrong_revision_text_without_the_actual_fragment_is_never_substituted():
    context = replace(legislation_context(content='Eski hükme göre bildirim yapılmaz.'), article_no='18/B')
    assert complete_provision(context, FULL) is None


def test_incomplete_canonical_text_is_not_repaired_by_dropping_the_exception():
    context = replace(legislation_context(content='MADDE 18/B- Kiracıya yazılı bildirim yapılır.'), article_no='18/B')
    assert complete_provision(context, FULL[:-8]) is None


def test_wrong_article_or_unverified_or_private_text_is_never_recovered():
    context = legislation_context(content=FULL[:64])
    assert complete_provision(context, FULL) is None
    for changes in ({'verification': 'third_party'}, {'source_type': 'document'}):
        assert complete_provision(replace(context, article_no='18/B', **changes), FULL) is None


def test_whole_law_cannot_replace_one_provision():
    context = replace(legislation_context(content=FULL[:64]), article_no='18/B')
    assert complete_provision(context, FULL + '\nMADDE 19- Başka hüküm uygulanır.') is None


def test_loader_binds_exact_source_revision_and_trust_and_never_queries_private_text():
    from contextlib import nullcontext
    from api.ai.provision_context import restore_provisions
    context = replace(legislation_context(content=FULL[:64]), article_no='18/B',
                      source_version='canonical-v1', revision=7)
    queries = []
    class Connection:
        def transaction(self):
            return nullcontext()
        def execute(self, sql, params=None):
            queries.append((sql, params))
            return self
        def fetchone(self):
            return {'raw_text': FULL}
    restored = restore_provisions([context], Connection())
    assert restored[0].content == FULL
    sql, params = queries[-1]
    assert params['id'] == context.source_id and params['version'] == 'canonical-v1' and params['revision'] == 7
    assert 'source_version IS NOT DISTINCT FROM' in sql and 'revision IS NOT DISTINCT FROM' in sql
    assert "'^[0-9]{1,5}$'" in sql
    assert "'document_text_hash'" in sql and "'article_hash' = ls.content_hash" in sql
    assert 'next_detail.legislation_type = legislation.legislation_type' in sql
    assert "ls.ingest_status = 'ready'" in sql and 'ls.is_current' in sql and 'ls.deleted_at IS NULL' in sql
    queries.clear()
    private = replace(context, source_type='document', verification='user_document')
    assert restore_provisions([private], Connection()) == [private] and not queries


def test_identity_backed_next_caption_is_presentation_not_a_condition_of_this_article():
    text = 'MADDE 336- Velâyet ana ve babaya aittir.\n\nIII. Ana ve baba evli değilse'
    context = replace(legislation_context(content=text), article_no='336')
    # Without an independently resolved same-document caption, preserve fail-closed behavior.
    assert complete_provision(context, text) is None
    restored = complete_provision(context, text, following_title='III. Ana ve baba evli değilse')
    assert restored is not None and restored.content == text
    from api.ai.synthesis import _source_views
    views = _source_views([restored], 16000)
    assert views[0]['text'] == text
    assert all('evli değilse' not in unit for unit in views[0]['units'])


def test_a_guessed_caption_not_at_the_end_cannot_remove_an_exception():
    text = 'MADDE 336- Velâyet ana ve babaya aittir.\nAncak bu durumda hak kullanılamaz ve'
    context = replace(legislation_context(content=text), article_no='336')
    assert complete_provision(context, text, following_title='Geçersiz feshin sonuçları') is None


def test_pdf_layout_caption_requires_exact_hash_article_document_and_suffix_binding():
    from api.ai.provision_context import _verified_layout_caption
    import hashlib

    text = 'MADDE 345- Kiracı bedelini öder.\n\nIV. Kiracı aleyhine düzenleme yasağı2'
    context = replace(legislation_context(content=text), article_no='345')
    article_hash = hashlib.sha256(b'article').hexdigest()
    document_hash = hashlib.sha256(b'document').hexdigest()
    url = 'https://www.mevzuat.gov.tr/MevzuatMetin/1.5.6098.pdf'
    proof = {
        'verified': True,
        'method': 'pypdf_bold_caption_exact_suffix_v1',
        'url': url,
        'article_no': '345',
        'following_article_no': '346',
        'caption': 'IV. Kiracı aleyhine düzenleme yasağı2',
        'article_hash': article_hash,
        'document_text_hash': document_hash,
    }
    row = {
        'layout_proof': proof,
        'text_proof': {'article_hash': article_hash, 'document_text_hash': document_hash},
        'raw_text': text,
        'content_hash': article_hash,
        'source_url': url,
    }

    assert _verified_layout_caption(row, context) == proof['caption']
    for field, value in (
        ('article_hash', '0' * 64),
        ('document_text_hash', '1' * 64),
        ('following_article_no', '347'),
        ('url', 'https://example.test/law.pdf'),
        ('caption', 'başka bir başlık'),
    ):
        changed = dict(row)
        changed['layout_proof'] = {**proof, field: value}
        assert _verified_layout_caption(changed, context) is None


def test_pdf_layout_caption_does_not_apply_to_a_different_article():
    from api.ai.provision_context import _verified_layout_caption

    context = replace(legislation_context(content='body'), article_no='344')
    proof = {
        'verified': True,
        'method': 'pypdf_bold_caption_exact_suffix_v1',
        'url': 'https://www.mevzuat.gov.tr/MevzuatMetin/1.5.6098.pdf',
        'article_no': '345',
        'following_article_no': '346',
        'caption': 'IV. Kiracı aleyhine düzenleme yasağı2',
        'article_hash': 'a' * 64,
        'document_text_hash': 'b' * 64,
    }
    row = {
        'layout_proof': proof,
        'text_proof': {'article_hash': 'a' * 64, 'document_text_hash': 'b' * 64},
        'raw_text': 'body\nIV. Kiracı aleyhine düzenleme yasağı2',
        'content_hash': 'a' * 64,
        'source_url': proof['url'],
    }
    assert _verified_layout_caption(row, context) is None
