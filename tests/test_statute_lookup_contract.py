from api import legal, statute_hints
from api.ai.retrieval import STATUTE_RETRIEVAL_SQL
from api.ai.search_plan import normalize


def test_all_exact_law_article_paths_bind_document_type_not_just_number():
    for sql in (STATUTE_RETRIEVAL_SQL, statute_hints._SQL, legal._ARTICLE_HIT_SQL):
        assert "legislation.legislation_type IN ('law', 'constitution', 'decree')" in sql
        assert '%(law_no)s' in sql and '%(article_no)s' in sql


def test_pdf_whitespace_is_not_a_phrase_boundary_and_numbers_are_preserved():
    assert normalize('ayrım\nyapılamaz') == 'ayrım yapılamaz'
    assert normalize('en\t az\u00a0otuz\r\ngün') == 'en az otuz gün'
    assert normalize('1 0 gün') != normalize('10 gün')
    assert normalize('ödenmez') != normalize('ödenir')


def test_hints_match_body_without_depending_on_missing_pdf_section_title():
    def hint(topic, article):
        return next(h for t in statute_hints.TOPICS if t.name == topic
                    for h in t.hints if h.article_no == article)
    assert statute_hints.text_matches(hint('yillik_izin', '59'),
        'işçinin hak kazanıp da kullanmadığı yıllık\nizin sürelerine ait ücreti')
    assert statute_hints.text_matches(hint('hakli_fesih_isci', '24'),
        'işçi, aşağıda yazılı hallerde iş\nsözleşmesini sürenin bitiminden önce')
    assert not statute_hints.text_matches(hint('hakli_fesih_isci', '24'),
        'işveren, aşağıda yazılı hallerde iş sözleşmesini sürenin bitiminden önce')
    assert statute_hints.text_matches(hint('hakli_fesih_isveren', '25'),
        'işveren, aşağıda yazılı hallerde iş\nsözleşmesini sürenin bitiminden önce')
