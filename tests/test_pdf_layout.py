from ingestion.mevzuat.pdf_layout import _eligible_caption, exact_suffix_for_caption, extract_layout_captions


def test_letter_enumerator_is_a_heading_but_a_sentence_is_not():
    assert _eligible_caption('b. Yeni malikin gereksinimi')
    assert _eligible_caption('II. Hükümleri')
    assert not _eligible_caption('Borç ödenir. Ancak bu koşul devam eder')


def test_caption_suffix_preserves_every_non_whitespace_character():
    assert exact_suffix_for_caption('Hüküm.\nII. Başlık\n1. Alt başlık', 'II. Başlık 1. Alt başlık') == 'II. Başlık\n1. Alt başlık'
    assert exact_suffix_for_caption('Hüküm.\nII. Başlık2', 'II. Başlık') is None


def test_multilevel_caption_keeps_top_to_bottom_order(monkeypatch):
    import ingestion.mevzuat.pdf_layout as layout

    class Page:
        def extract_text(self):
            return 'MADDE 117- Hüküm.\nII. Hükümleri\n1. Genel olarak\na. Gecikme tazminatı\nMADDE 118- Diğer hüküm.'

    class Reader:
        pages = [Page()]

    monkeypatch.setattr(layout, 'PdfReader', lambda stream: Reader())
    monkeypatch.setattr(layout, '_bold_lines', lambda page: [
        (600, 100, 12, 'II. Hükümleri'),
        (582, 100, 12, '1. Genel olarak'),
        (564, 100, 12, 'a. Gecikme tazminatı'),
        (546, 100, 12, 'MADDE 118-'),
    ])
    _, captions = extract_layout_captions(b'fixture')
    assert any(c.article_no == '118' and c.caption == 'II. Hükümleri 1. Genel olarak a. Gecikme tazminatı' for c in captions)
