import pytest

from api.ai.pipeline import _wants_source_text


@pytest.mark.parametrize("question", [
    "İşten çıkarıldım haklarım nelerdir?",
    "Boşanmada ortak velayet hangi şartlarda mümkündür?",
    "TBK 315'i kısa ve anlaşılır açıkla.",
])
def test_natural_questions_do_not_request_a_source_dump(question):
    assert not _wants_source_text(question)


@pytest.mark.parametrize("question", [
    "TBK 315 madde metnini göster.",
    "Kararın tam metnini getir.",
    "Bu hükmü aynen aktar.",
])
def test_explicit_verbatim_request_keeps_the_quote_route(question):
    assert _wants_source_text(question)
