from dataclasses import replace
from uuid import uuid4

from api.ai.cache import restore_verified_natural_answer, answer_cache_key, source_fingerprint
from api.ai.verification import VerifiedAnswer
from tests.factories import legislation_context


def test_only_verified_server_object_is_cacheable_and_only_against_current_evidence():
    source = legislation_context()
    answer = VerifiedAnswer("Kaynaklı doğal açıklama.", (source,), ())
    payload = {"_verified_natural_answer": answer}
    assert restore_verified_natural_answer(payload, [source]) == answer
    assert restore_verified_natural_answer({"answer": answer.text}, [source]) is None
    assert restore_verified_natural_answer(payload, []) is None
    for changed in (
        replace(source, content="Metin değişti."),
        replace(source, revision=42),
        replace(source, article_no="99"),
        replace(source, verification="third_party"),
    ):
        assert restore_verified_natural_answer(payload, [changed]) is None


def test_plain_unverified_or_insufficient_answer_is_not_proof():
    source = legislation_context()
    unverified = VerifiedAnswer("Cevap.", (source,), ("K99",))
    assert restore_verified_natural_answer({"_verified_natural_answer": unverified}, [source]) is None
    empty = VerifiedAnswer("Doğrulayamadım.", (), (), answer_kind="insufficient_sources")
    assert restore_verified_natural_answer({"_verified_natural_answer": empty}, [source]) is None


def test_natural_cache_keys_isolate_users_even_with_the_same_public_sources():
    params = dict(question="TÜFE nedir?", project_id=None, as_of=None, model="test", fingerprint="sources")
    assert answer_cache_key(**params, user_id=uuid4()) != answer_cache_key(**params, user_id=uuid4())
    source = legislation_context()
    assert source_fingerprint([source]) != source_fingerprint([replace(source, article_no="99")])
