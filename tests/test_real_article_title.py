"""The portal stores "Madde No: 342" where an article has no caption; a reader must never see that placeholder as a title."""

from uuid import uuid4

import pytest

from api.ai.rag import RAGContext, real_article_title


@pytest.mark.parametrize("stored, shown", [
    (None, None), ("", None), ("   ", None),
    ("Madde No: 342", None), ("madde no: 12/A", None),
    ("Madde No: 139 - 1. Genel olarak", "1. Genel olarak"),
    ("Süreli fesih", "Süreli fesih"),
    ("Feshin geçerli sebebe dayandırılması", "Feshin geçerli sebebe dayandırılması"),
])
def test_only_a_real_caption_is_shown(stored, shown):
    assert real_article_title(stored) == shown


def _statute(title):
    return RAGContext(chunk_id=uuid4(), source_id=uuid4(), source_type="legislation", title="t", source_url=None, authority=None,
                      court_name=None, chamber=None, docket_no=None, decision_no=None, decision_date=None,
                      law_name="TÜRK BORÇLAR KANUNU", law_no="6098", article_no="342", article_title=title, content="x", rank=1.0)


def test_the_reference_line_drops_the_placeholder_and_keeps_a_real_caption():
    assert _statute("Madde No: 342").reference_line == "TÜRK BORÇLAR KANUNU (6098) m. 342"
    assert _statute("Kira bedeli").reference_line == "TÜRK BORÇLAR KANUNU (6098) m. 342 — Kira bedeli"
