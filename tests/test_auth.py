"""Token verification.

Authorisation proper lives in Postgres row-level security (schema.sql) — an
engineer cannot insert an approval however they call the API. This layer only
establishes *who* is asking, so a decision can be attributed and a bad token
rejected before any work is done.
"""

from __future__ import annotations

import time

import jwt
import pytest

from src.store.auth import AuthError, bearer, verify

# 32+ bytes: shorter keys are valid but PyJWT warns, and the warning is right.
SECRET = "test-secret-not-a-real-one-padded-to-32b"


def make_token(**over) -> str:
    claims = {
        "sub": "user-123", "email": "head@example.com",
        "aud": "authenticated", "exp": int(time.time()) + 3600,
    }
    claims.update(over)
    return jwt.encode(claims, SECRET, algorithm="HS256")


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    """Legacy HS256 path. SUPABASE_URL is cleared so the asymmetric path is
    skipped and these tests exercise the shared-secret fallback."""
    from src.store import auth

    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    auth.reset()
    yield
    auth.reset()


@pytest.mark.parametrize(
    "header,expected",
    [("Bearer abc", "abc"), ("bearer abc", "abc"), ("Basic abc", None),
     ("", None), (None, None), ("Bearer", None)],
)
def test_bearer_parsing(header, expected):
    assert bearer(header) == expected


def test_valid_token_identifies_the_caller():
    caller = verify(make_token())
    assert caller.user_id == "user-123"
    assert caller.email == "head@example.com"
    assert caller.label == "head@example.com"


def test_missing_token_is_refused():
    with pytest.raises(AuthError, match="sign in"):
        verify(None)


def test_expired_token_is_refused():
    with pytest.raises(AuthError, match="expired"):
        verify(make_token(exp=int(time.time()) - 10))


def test_token_signed_with_another_key_is_refused():
    forged = jwt.encode(
        {"sub": "x", "aud": "authenticated", "exp": int(time.time()) + 60},
        "a-different-secret", algorithm="HS256",
    )
    with pytest.raises(AuthError, match="invalid"):
        verify(forged)


def test_token_without_a_subject_is_refused():
    """PyJWT rejects a null subject before we get to it; either way the
    caller cannot be identified, so the request must fail."""
    with pytest.raises(AuthError):
        verify(make_token(sub=None))


def test_unsigned_token_is_refused():
    """alg=none must never be accepted."""
    unsigned = jwt.encode(
        {"sub": "x", "aud": "authenticated"}, key="", algorithm="none")
    with pytest.raises(AuthError):
        verify(unsigned)


def test_no_way_to_verify_is_reported_clearly(monkeypatch):
    """Neither a JWKS endpoint nor a shared secret: say so, do not guess."""
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    with pytest.raises(AuthError, match="cannot verify"):
        verify(make_token())


def test_asymmetric_projects_need_no_shared_secret(monkeypatch):
    """Current Supabase projects sign with ES256 and expose public keys, so
    verification must work with SUPABASE_JWT_SECRET absent entirely.

    Regression: the verifier originally hardcoded algorithms=["HS256"] and
    rejected every real token with "The specified alg value is not allowed".
    """
    from cryptography.hazmat.primitives.asymmetric import ec

    from src.store import auth

    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    key = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode(
        {"sub": "u1", "email": "e@x.com", "aud": "authenticated",
         "exp": int(time.time()) + 60},
        key, algorithm="ES256",
    )

    class FakeSigningKey:
        def __init__(self, k):
            self.key = k

    monkeypatch.setattr(
        auth, "_client",
        lambda: type("C", (), {
            "get_signing_key_from_jwt": lambda self, t: FakeSigningKey(key.public_key())
        })(),
    )
    caller = verify(token)
    assert caller.user_id == "u1"
    assert caller.email == "e@x.com"
