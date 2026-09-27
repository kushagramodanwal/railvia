"""Supabase JWT verification.

The UI hides the Approve button from engineers, but that is a courtesy, not a
control — anyone can call the API directly. Authorisation is therefore
enforced in two places that both have to agree:

  1. Here, so the API knows who is calling and can reject an unsigned,
     expired or forged token before doing any work.
  2. In Postgres, by the row-level-security policies in schema.sql, which is
     what actually stops an engineer inserting an approval.

The second is the real control. This layer exists so a decision can be
attributed to a named user and a bad token fails early.

Two signing schemes
-------------------
Supabase projects come in two flavours and this handles both:

  * **Asymmetric (ES256/RS256)** — current default. Tokens are verified
    against the project's PUBLIC keys, fetched from its JWKS endpoint. No
    shared secret exists, and none is needed: there is nothing to leak.
  * **HS256 with a shared secret** — legacy. Verified with
    SUPABASE_JWT_SECRET.

Asymmetric is tried first and the secret is only a fallback, so a project
that has moved on needs no configuration beyond its URL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

JWT_SECRET_VAR = "SUPABASE_JWT_SECRET"
URL_VAR = "SUPABASE_URL"

ASYMMETRIC_ALGS = ["ES256", "RS256"]

_jwks_client: PyJWKClient | None = None


class AuthError(Exception):
    """Token missing, malformed, expired, or wrongly signed."""


@dataclass(frozen=True)
class Caller:
    """The authenticated user behind one request."""

    user_id: str
    email: str
    token: str

    @property
    def label(self) -> str:
        return self.email or self.user_id


def jwks_url() -> str | None:
    # Same fallback as the store: the browser's copy of the project URL is
    # the same URL, and requiring it under two names is a needless trap.
    base = os.environ.get(URL_VAR) or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    return f"{base.rstrip('/')}/auth/v1/.well-known/jwks.json" if base else None


def _client() -> PyJWKClient | None:
    """Cached JWKS client. Caches keys and refetches on an unknown kid, so
    key rotation does not need a restart."""
    global _jwks_client
    if _jwks_client is None:
        url = jwks_url()
        if not url:
            return None
        _jwks_client = PyJWKClient(url, cache_keys=True, lifespan=600)
    return _jwks_client


def reset() -> None:
    """Testing hook: drop the cached JWKS client."""
    global _jwks_client
    _jwks_client = None


def _decode_asymmetric(token: str) -> dict | None:
    """Verify against the project's public keys. None if unavailable."""
    client = _client()
    if client is None:
        return None
    try:
        key = client.get_signing_key_from_jwt(token).key
    except Exception:  # noqa: BLE001 - no JWKS, offline, or no matching kid
        return None
    return jwt.decode(
        token, key, algorithms=ASYMMETRIC_ALGS, audience="authenticated",
    )


def _decode_hs256(token: str) -> dict:
    secret = os.environ.get(JWT_SECRET_VAR)
    if not secret:
        raise AuthError(
            "cannot verify this session. The project signs tokens with an "
            "asymmetric key, so SUPABASE_URL must be set and its JWKS "
            "endpoint reachable; for a legacy project, set "
            f"{JWT_SECRET_VAR} instead."
        )
    return jwt.decode(
        token, secret, algorithms=["HS256"], audience="authenticated",
    )


def verify(token: str | None) -> Caller:
    """Decode and verify a Supabase access token."""
    if not token:
        raise AuthError("sign in to record a decision")

    try:
        claims = _decode_asymmetric(token)
        if claims is None:
            claims = _decode_hs256(token)
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("session expired — sign in again") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"invalid session token: {exc}") from exc

    user_id = claims.get("sub")
    if not user_id:
        raise AuthError("token carries no subject")
    return Caller(user_id=user_id, email=claims.get("email", ""), token=token)


def bearer(header: str | None) -> str | None:
    """Pull the token out of an Authorization header."""
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None
