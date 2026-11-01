"""Soru kalıbı sözcükleri ("neyi düzenler") pasaj alakasını belirlememeli; konu sözcükleri belirlemeye devam eder."""
from api.ai.relevance import passage_relevant

ARTICLE_18 = "Feshin geçerli sebebe dayandırılması: Otuz veya daha fazla işçi çalıştıran işyerlerinde en az altı aylık kıdemi olan işçinin belirsiz süreli iş sözleşmesini fesheden işveren, geçerli bir sebebe dayanmak zorundadır."


def test_an_explicit_statute_question_accepts_the_named_article():
    assert passage_relevant("4857 sayılı İş Kanunu madde 18 neyi düzenler?", ARTICLE_18)
    assert passage_relevant("4857 sayılı Kanunun 18. maddesi nedir?", ARTICLE_18)


def test_topic_words_still_reject_unrelated_passages():
    assert not passage_relevant("zeytinyağı ihracatı gecikmesi cezası nelerdir", ARTICLE_18)
    assert passage_relevant("işçinin kıdemi ve geçerli sebep nedir", ARTICLE_18)
