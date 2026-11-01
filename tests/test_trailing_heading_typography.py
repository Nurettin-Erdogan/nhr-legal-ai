"""A statute chunk that ends with the NEXT section's heading stays usable evidence; one that ends with a rule does not.

Measured 2026-10-31: TBK m. 342 ("güvence en çok üç aylık kira bedelini aşamaz") ended with "E. Kira bedeli" / "I. Genel olarak2"
(letter numbering and a footnote digit glued to the last word) and was refused as a cut-off text, so a deposit question was
answered from unrelated decisions. Only typography is recognised; a rule at the end of an article is never treated as a heading.
"""

from uuid import uuid4

from api.ai import free_answer
from api.ai.rag import RAGContext

RULE = ("MADDE 342- Konut ve çatılı işyeri kiralarında sözleşmeyle kiracıya güvence verme\n"
        "borcu getirilmişse, bu güvence üç aylık kira bedelini aşamaz.\n"
        "Kiraya veren, güvenceyi sözleşme sona erdikten sonra geri vermekle yükümlüdür.")


def _statute(content: str) -> RAGContext:
    return RAGContext(chunk_id=uuid4(), source_id=uuid4(), source_type="legislation", title="TÜRK BORÇLAR KANUNU",
                      source_url=None, authority=None, court_name=None, chamber=None, docket_no=None, decision_no=None,
                      decision_date=None, law_name="TÜRK BORÇLAR KANUNU", law_no="6098", article_no="342", article_title=None,
                      content=content, rank=1.0)


def test_letter_numbered_heading_with_a_glued_footnote_digit_is_typography():
    context = _statute(RULE + "\n\nE. Kira bedeli\nI. Genel olarak2")
    assert free_answer._usable(context, free_answer._POOL_CHARS) is not None


def test_a_plain_numbered_heading_still_works():
    assert free_answer._usable(_statute(RULE + "\n\nIII. Dava açma süresi"), free_answer._POOL_CHARS) is not None


def test_a_rule_at_the_end_of_the_article_is_never_removed_as_a_heading():
    from api.ai import synthesis
    # a verb, a number, a condition: this is part of the rule, not a caption
    for tail in ("\n\nE. Kira bedeli\nI. Kiraya veren üç ay içinde bildirmezse güvenceyi iade etmek zorundadır2",
                 "\n\nE. Süre\nI. En geç 15 gün içinde ödenir"):
        context = _statute(RULE + tail)
        assert synthesis._legislation_body_without_trailing_heading(context) == context.content
