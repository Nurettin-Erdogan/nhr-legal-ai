from ingestion.altai_yargitay import html_content_to_text, prepare_altai_row


SAMPLE_HTML = (
    '<html><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"></head>'
    '<body><b>21. Hukuk Dairesi 2014/24839 E. , 2015/9497 K.</b>'
    '<b>"İçtihat Metni"</b><p>MAHKEMESİ :İş Mahkemesi<br>Karar metni burada.</p></body></html>'
)


def test_html_parser_strips_markup_and_ictihat_heading():
    text = html_content_to_text(SAMPLE_HTML)
    assert "Karar metni burada." in text
    assert "<html>" not in text
    assert "İçtihat Metni" not in text


def test_prepare_altai_uses_columns_and_html_body():
    row = prepare_altai_row(
        {
            "id": "210988800",
            "daire": "21. Hukuk Dairesi",
            "esasNo": "2014/24839",
            "kararNo": "2015/9497",
            "kararTarihi": "30.04.2015",
            "siraNo": 1,
            "content": SAMPLE_HTML,
        }
    )
    assert row.quarantine_code is None
    assert row.external_id == "yargitay:210988800"
    assert row.docket_no == "2014/24839"
    assert row.chamber == "21. Hukuk Dairesi"
    assert row.metadata["official_verified"] is False
    assert row.metadata["html_parsed"] is True
    assert "<html>" not in row.raw_text


def test_prepare_altai_quarantines_empty_html():
    row = prepare_altai_row(
        {
            "id": "1",
            "daire": "9. Hukuk Dairesi",
            "esasNo": "2015/1",
            "kararNo": "2015/2",
            "kararTarihi": "01.01.2015",
            "content": "<html><body></body></html>",
        }
    )
    assert row.quarantine_code == "empty_text"
