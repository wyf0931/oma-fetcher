from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from .config import Settings

# argon2id with the library defaults (64 MiB, t=3, p=4) is the OWASP baseline
# for interactive password hashing.
_password_hasher = PasswordHasher()

_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
MIN_PASSWORD_LENGTH = 8


@dataclass(frozen=True)
class Principal:
    key_id: int | None
    scopes: frozenset[str]
    is_admin: bool = False
    user_id: int | None = None


def role_scopes(role: str) -> frozenset[str]:
    """Map a stored user role onto API scopes (admin implies every scope)."""
    if role == "admin":
        return frozenset({"admin", "fetch", "search"})
    return frozenset({"fetch", "search"})


def authenticate(authorization: str | None, settings: Settings, store: Any) -> Principal | None:
    """Authenticate a Bearer API key.

    Returns an anonymous admin when API authentication is disabled so local
    development keeps working. There is no fixed environment admin key: admin
    rights come exclusively from ``users.role``.
    """
    if not settings.api_auth_enabled:
        return Principal(key_id=None, scopes=role_scopes("admin"), is_admin=True)
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    try:
        key = store.authenticate_key(token, settings.api_key_pepper)
    except Exception:
        return None
    if key is None:
        return None
    return Principal(key_id=key["id"], user_id=key["user_id"], scopes=frozenset(json_scopes(key["scopes_json"])))


def authenticate_session(session_token: str | None, store: Any) -> Principal | None:
    """Build a Principal from a session cookie token, or None when invalid."""
    if not session_token:
        return None
    try:
        session = store.get_session(hash_session_token(session_token))
        if session is None:
            return None
        user = store.get_user(int(session["user_id"]))
    except Exception:
        return None
    if user is None or user.get("status") != "active":
        return None
    role = user.get("role") or "user"
    return Principal(key_id=None, user_id=int(user["id"]), scopes=role_scopes(role), is_admin=role == "admin")


def resolve_principal(request: Any, settings: Settings, store: Any) -> Principal | None:
    """Session cookie first, then Bearer API key."""
    principal = authenticate_session(request.cookies.get(settings.session_cookie_name), store)
    if principal is not None:
        return principal
    return authenticate(request.headers.get("authorization"), settings, store)


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return True when the password matches; never raises."""
    try:
        return _password_hasher.verify(password_hash, password)
    except (Argon2Error, ValueError, TypeError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Only the SHA-256 digest of a session token is persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry(settings: Settings) -> str:
    return (datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours)).isoformat()


def validate_email(email: str) -> str:
    normalized = email.strip().lower()
    if not normalized or len(normalized) > 255 or not _EMAIL_PATTERN.match(normalized):
        raise ValueError("a valid email address is required")
    return normalized


def validate_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        raise ValueError("password must contain both letters and digits")
    return password


def register_user(*, email: str, password: str, display_name: str | None, store: Any) -> dict[str, Any]:
    """Create a regular user after validating the email format and password strength."""
    normalized_email = validate_email(email)
    validate_password(password)
    if store.get_user_by_email(normalized_email) is not None:
        raise ValueError("email already registered")
    return store.create_user(
        email=normalized_email,
        password_hash=hash_password(password),
        display_name=(display_name or "").strip() or None,
    )


def login_user(*, email: str, password: str, store: Any) -> dict[str, Any] | None:
    """Verify credentials and return the user dict (without password_hash), else None."""
    normalized_email = email.strip().lower()
    password_hash = _stored_password_hash(store, normalized_email)
    if password_hash is None or not verify_password(password, password_hash):
        return None
    user = store.get_user_by_email(normalized_email)
    if user is None or user.get("status") != "active":
        return None
    store.touch_user_login(int(user["id"]))
    return user


def _stored_password_hash(store: Any, email: str) -> str | None:
    """Read the argon2 digest directly; the public user views omit it."""
    try:
        with store._connect() as connection:
            row = connection.execute("SELECT password_hash FROM users WHERE email = ?", (email,)).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    value = row[0] if not isinstance(row, sqlite3.Row) else row["password_hash"]
    return value if isinstance(value, str) else None


def json_scopes(value: str) -> list[str]:
    try:
        scopes = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [scope for scope in scopes if isinstance(scope, str)] if isinstance(scopes, list) else []


def key_digest(token: str, pepper: str) -> str:
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
