from __future__ import annotations

from uuid import uuid4

import pytest

from api.auth.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


SECRET = "test-secret-that-is-longer-than-thirty-two-characters"


def test_password_hash_is_not_plaintext_and_verifies():
    password = "Guclu-bir-test-parolasi-42"
    digest = hash_password(password)

    assert digest != password
    assert verify_password(password, digest)
    assert not verify_password("yanlis-parola", digest)


def test_access_token_round_trip():
    user_id = uuid4()
    token, expires_in = create_access_token(
        user_id=user_id,
        secret=SECRET,
        expires_minutes=30,
    )

    assert expires_in == 1800
    assert decode_access_token(token, secret=SECRET) == user_id


def test_access_token_rejects_wrong_secret():
    token, _ = create_access_token(
        user_id=uuid4(),
        secret=SECRET,
        expires_minutes=30,
    )

    with pytest.raises(TokenError):
        decode_access_token(token, secret="another-secret-that-is-also-long-enough")
