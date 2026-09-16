from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .config import Settings


@dataclass(frozen=True)
class Principal:
    key_id: int | None
    scopes: frozenset[str]
    is_admin: bool = False


def authenticate(authorization: str | None, settings: Settings, store: Any) -> Principal | None:
    if not settings.api_auth_enabled:
        return Principal(key_id=None, scopes=frozenset({"admin", "fetch", "search"}), is_admin=True)
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    if hmac.compare_digest(token, settings.api_admin_key):
        return Principal(key_id=None, scopes=frozenset({"admin", "fetch", "search"}), is_admin=True)
    try:
        key = store.authenticate_key(token, settings.api_key_pepper)
    except Exception:
        return None
    if key is None:
        return None
    return Principal(key_id=key["id"], scopes=frozenset(json_scopes(key["scopes_json"])))


def json_scopes(value: str) -> list[str]:
    import json

    try:
        scopes = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [scope for scope in scopes if isinstance(scope, str)] if isinstance(scopes, list) else []


def key_digest(token: str, pepper: str) -> str:
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()

