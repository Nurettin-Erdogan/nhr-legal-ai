from datetime import date

import pytest

from ingestion.fulltext_queue import PortalError, prepare_http_fulltext

HTML = """
<html><body>
<div>9. Hukuk Dairesi 2019/1234 E. , 2021/5678 K.</div>
<p>Davacı vekili kıdem tazminatı talep etmiştir. Mahkemece toplanan deliller değerlendirilmiş ve hükmün bozulmasına karar verilmiştir. Bu metin seksen karakteri geçmek için uzatılmıştır.</p>
</body></html>
"""


def test_prepare_http_fulltext_uses_inventory_and_html():
    row = prepare_http_fulltext(
        document_id="1194194700",
        html=HTML,
        chamber="9. Hukuk Dairesi",
        docket_no="2019/1234",
        decision_no="2021/5678",
        decision_date=date(2021, 5, 12),
    )
    assert row["external_id"] == "yargitay:1194194700"
    assert row["docket_no"] == "2019/1234"
    assert row["decision_no"] == "2021/5678"
    assert row["decision_date"] == date(2021, 5, 12)
    assert "kıdem tazminatı" in row["raw_text"]
    assert len(row["raw_text"]) >= 80


def test_prepare_http_fulltext_rejects_empty_html():
    with pytest.raises(PortalError):
        prepare_http_fulltext(document_id="1", html="<html></html>")
