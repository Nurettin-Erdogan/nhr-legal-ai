"""Source support does not imply that every requested topic was answered."""
from types import SimpleNamespace

import pytest

from api.ai.pipeline import PipelineTimings, _response_from_verified
from api.ai.verification import VerifiedAnswer
from api.schemas import AIAnswerRequest


@pytest.mark.parametrize("path", ["free_answer", "synthesis"])
@pytest.mark.parametrize("info,expected", [
    ({"partial_answer": True}, False),
    ({"uncovered_parts": ["İspat"]}, False),
    ({"coverage_preserved": False}, False),
    ({"status": "accepted", "coverage_preserved": True}, True),
    ({"status": "fallback", "reason": "checker"}, None),
    ({}, None),
])
def test_response_exports_coverage_independently_of_grounding(path, info, expected):
    timings = PipelineTimings()
    timings.extra[path] = info
    response = _response_from_verified(
        AIAnswerRequest(question="Sentetik test sorusu"),
        VerifiedAnswer(text="Sentetik cevap", contexts=(), unverified_markers=()),
        provider=SimpleNamespace(name="test", model="test"),
        conversation_id=None, message_id=None, from_cache=True, timings=timings,
    )
    assert response.coverage_complete is expected
    assert response.grounded is False
