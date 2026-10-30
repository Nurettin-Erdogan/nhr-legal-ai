"""A removed premise must not leave an orphan exception in the final answer."""
from api.ai.synthesis import _Claim, _independent_survivors


def claim(text, source=1):
    return _Claim(text, ((source, 'Original evidence.'),))


def test_rejected_branch_also_removes_its_exception_and_temporal_continuation():
    claims = [claim('Yabancı para sözleşmesinin özel şartı vardır.'),
              claim('Ancak istisna hükmü saklıdır.'),
              claim('Beş yıl geçtikten sonra farklı yöntem uygulanır.'),
              claim('Başvuru yazılı yapılır.')]
    assert _independent_survivors(claims, {2, 3, 4}) == {4}


def test_independent_same_source_clause_survives_and_resets_dependency():
    claims = [claim('İlk iddia reddedilmiştir.'), claim('Başvuru yazılı yapılır.'),
              claim('Ancak ek belge de gerekir.')]
    assert _independent_survivors(claims, {2, 3}) == {2, 3}


def test_transition_in_another_source_is_not_automatically_discarded():
    claims = [claim('Reddedilen iddia.', 1), claim('Ancak başvuru yazılı yapılır.', 2)]
    assert _independent_survivors(claims, {2}) == {2}


def test_approved_antecedent_and_exception_are_both_preserved():
    claims = [claim('Başvuru zorunludur.'), claim('Ancak istisna saklıdır.')]
    assert _independent_survivors(claims, {1, 2}) == {1, 2}
