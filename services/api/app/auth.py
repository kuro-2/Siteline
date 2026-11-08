"""Supabase JWT verification and roles.

Supports both the current asymmetric signing keys (JWKS, ES256/RS256) and the legacy
HS256 JWT secret. The role is always read from `profiles`, never from the token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header

from app.errors import ApiError
from engine.db import connect
from engine.settings import get_settings

ROLE_ORDER = ["public", "resident", "surveyor", "analyst", "admin"]


@dataclass(frozen=True)
class User:
    id: str
    role: str
    email: str | None
    display_name: str | None
    home_h3: str | None
    consent_version: str | None
    verified: bool

    @property
    def is_staff(self) -> bool:
        return self.role in ("analyst", "admin")


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def jwks_url() -> str | None:
    s = get_settings()
    if s.supabase_jwks_url:
        return s.supabase_jwks_url
    if s.supabase_url:
        return s.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
    return None


def decode_token(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise ApiError(401, "bad_token", "Your login has expired. Log in again.") from e
    alg = header.get("alg", "")
    try:
        if alg == "HS256":
            if not s.supabase_jwt_secret:
                raise ApiError(
                    500,
                    "auth_not_configured",
                    "Login isn't set up on this server yet.",
                    "Set SUPABASE_JWT_SECRET or use JWKS signing keys.",
                )
            claims = jwt.decode(
                token, s.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated"
            )
        else:
            url = jwks_url()
            if not url:
                raise ApiError(500, "auth_not_configured", "Login isn't set up on this server yet.")
            key = _jwks_client(url).get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, key.key, algorithms=["ES256", "RS256", "EdDSA"], audience="authenticated"
            )
    except jwt.ExpiredSignatureError as e:
        raise ApiError(401, "token_expired", "Your login has expired. Log in again.") from e
    except jwt.PyJWTError as e:
        raise ApiError(401, "bad_token", "We couldn't check your login. Log in again.") from e
    return dict(claims)


def load_user(claims: dict[str, Any]) -> User:
    uid = str(claims.get("sub", ""))
    if not uid:
        raise ApiError(401, "bad_token", "We couldn't check your login. Log in again.")
    with connect() as conn:
        row = conn.execute(
            """insert into profiles (id, verified_at) values (%s, now())
               on conflict (id) do update set verified_at = coalesce(profiles.verified_at, now())
               returning id, role::text as role, display_name, home_h3, consent_version, verified_at""",
            (uid,),
        ).fetchone()
    assert row is not None
    return User(
        id=uid,
        role=row["role"],
        email=claims.get("email"),
        display_name=row["display_name"],
        home_h3=row["home_h3"],
        consent_version=row["consent_version"],
        verified=row["verified_at"] is not None,
    )


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token else None


def optional_user(authorization: Annotated[str | None, Header()] = None) -> User | None:
    token = _bearer(authorization)
    return load_user(decode_token(token)) if token else None


def current_user(authorization: Annotated[str | None, Header()] = None) -> User:
    token = _bearer(authorization)
    if not token:
        raise ApiError(401, "login_required", "Log in to do this.")
    return load_user(decode_token(token))


def require_role(*roles: str) -> Any:
    def dep(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in roles and user.role != "admin":
            raise ApiError(
                403,
                "forbidden",
                "You don't have access to this.",
                "Ask an admin if you think you should.",
            )
        return user

    return dep


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]
Analyst = Annotated[User, Depends(require_role("analyst"))]
Admin = Annotated[User, Depends(require_role("admin"))]
Resident = Annotated[User, Depends(require_role("resident", "surveyor", "analyst"))]


def now() -> datetime:
    return datetime.now(UTC)
