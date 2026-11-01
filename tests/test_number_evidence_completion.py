"""A number the sentence states is in its own cited source, but the writer bound another unit: the code binds the right unit.

Measured 2026-10-31: 3-5 of 11 sentences of a plain statute answer were refused (`number_or_unit`) for this, then a repair round
that bound the same units cost ~20 s. An invented number must still be refused, and a unit of a source the sentence did not cite
must never be used.
"""

from api.ai import synthesis
from api.ai.synthesis import _complete_number_evidence, _support_failures

LEAD = "Bildirim süreleri iş sözleşmesinin devam ettiği süreye göre belirlenir."
SIX = "Altı aydan az süren işçi için bildirim süresi iki hafta sonra sona erer."
OTHER = "Üç yıldan fazla çalışmış işçi için bildirim süresi sekiz haftadır."
CLAIM = "İşi altı aydan kısa süren işçi için bildirim süresi iki haftadır."


def test_the_unit_that_carries_the_number_is_added_to_the_evidence():
    views = [{"units": [LEAD, SIX, OTHER]}]
    quotes = [(1, LEAD)]
    assert "number_or_unit" in _support_failures(CLAIM, LEAD, "", "")
    completed = _complete_number_evidence(CLAIM, quotes, [1], views, "", "")
    assert completed is not None and (1, SIX) in completed and completed[0] == (1, LEAD)
    assert "number_or_unit" not in _support_failures(CLAIM, "\n".join(span for _, span in completed), "", "")


def test_an_invented_number_is_still_refused():
    views = [{"units": [LEAD, SIX, OTHER]}]
    assert _complete_number_evidence("İşçi için bildirim süresi on dört haftadır.", [(1, LEAD)], [1], views, "", "") is None


def test_only_the_cited_sources_are_searched():
    views = [{"units": [LEAD]}, {"units": [SIX]}]
    assert _complete_number_evidence(CLAIM, [(1, LEAD)], [1], views, "", "") is None  # source 2 was not cited by the claim


def test_the_checked_claim_gate_uses_the_completion(monkeypatch):
    calls = []
    original = synthesis._complete_number_evidence

    def spy(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(synthesis, "_complete_number_evidence", spy)
    from datetime import date
    from uuid import uuid4
    from api.ai.rag import RAGContext
    context = RAGContext(chunk_id=uuid4(), source_id=uuid4(), source_type="legislation", title="İŞ KANUNU", source_url=None,
                         authority=None, court_name=None, chamber=None, docket_no=None, decision_no=None, decision_date=None,
                         law_name="İŞ KANUNU", law_no="4857", article_no="17", article_title=None,
                         content="\n".join([LEAD, SIX, OTHER]), rank=1.0)
    views = [{"units": [LEAD, SIX, OTHER]}]
    claim = synthesis._checked_claim(1, CLAIM, [{"source": 1, "unit": 1}], [context], views, lenient=True)
    assert calls and any(span == SIX for _, span in claim.evidence)
