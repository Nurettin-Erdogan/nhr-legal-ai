"""Var olmayan madde numarası: model çağrılmaz, madde uydurulmaz ve kullanıcıya o madde hakkında konuşulur (ağ/DB gerektirmez).

Ölçüldü (2026-10-30): "4857 sayılı İş Kanunu'nun 999. maddesi neyi düzenliyor? Böyle bir madde yoksa açıkça belirt" sorusu genel
"yeterli bilgi bulamadım, konuyu daraltın veya belge seçin" cevabını aldı: hiçbir kaynak eşleşmeyince maddeye özgü cevaptan önceki
genel dal çalışıyordu. "Böyle bir madde yok" ancak resmî metin okunup tanındığında söylenebilir; aksi hâlde yalnız korpus için konuşulur.
"""

from types import SimpleNamespace

import pytest

from api.ai import official_research, pipeline


def test_an_absent_article_in_a_read_official_text_is_a_finding_not_a_failure(monkeypatch):
    # Bağdaştırıcılar aşağıda enjekte edilir (ağ yok); çevrimdışı denetim kipi araştırmayı baştan "offline" yapar.
    monkeypatch.delenv("NHR_OFFLINE_AUDIT", raising=False)
    document = SimpleNamespace(law_no="4857", law_name="İŞ KANUNU", pdf_url="https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4857.pdf")

    def store(document, full, article):
        official_research.extract_article(full, article)

    monkeypatch.setattr(official_research, "extract_article", lambda full, article: (_ for _ in ()).throw(
        official_research.OfficialArticleAbsent("absent")))
    result = official_research.research_official(["4857 sayılı Kanun madde 999"], [], public_scope=True,
                                                 fetch_law=lambda law: (document, "metin"), store_article=store,
                                                 court_search=lambda topic: ([], 0), load_contexts=lambda ids: [])
    assert {"source": "mevzuat", "status": "article_absent", "law_no": "4857", "article_no": "999"} in result.statuses


def test_extract_article_separates_absent_from_unreadable(monkeypatch):
    from ingestion.mevzuat import identity
    heading = SimpleNamespace(identity=identity.canonical_article("1"), start=0)
    monkeypatch.setattr(identity, "article_headings", lambda full: [heading])
    with pytest.raises(official_research.OfficialArticleAbsent):
        official_research.extract_article("Madde 1 - Metin", "999")
    monkeypatch.setattr(identity, "article_headings", lambda full: [])
    with pytest.raises(ValueError) as error:
        official_research.extract_article("okunamayan metin", "999")
    assert not isinstance(error.value, official_research.OfficialArticleAbsent)


def test_the_user_is_told_there_is_no_such_article_only_after_the_official_text_was_read():
    statuses = [{"source": "mevzuat", "status": "article_absent", "law_no": "4857", "article_no": "999"}]
    text = pipeline._missing_article_text("4857", "999", statuses)
    assert "resmî metninde 999. madde bulunmuyor" in text and "mevzuat.gov.tr" in text
    for other in ([], None, [{"source": "mevzuat", "status": "unavailable_or_unverified"}],
                  [{"source": "mevzuat", "status": "article_absent", "law_no": "4857", "article_no": "998"}]):
        text = pipeline._missing_article_text("4857", "999", other)
        assert "doğrulanmış mevzuat kaynaklarımızda bulamadım" in text and "bulunmuyor" not in text
