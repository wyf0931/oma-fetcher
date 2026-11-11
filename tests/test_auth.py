from pathlib import Path

from app.auth import authenticate, authenticate_session, hash_session_token, new_session_token
from app.config import Settings
from app.storage import DocumentStore

_PEPPER = "p" * 32


def make_store(tmp_path: Path) -> DocumentStore:
    store = DocumentStore(str(tmp_path / "keys.db"), str(tmp_path / "custom.txt"))
    store.initialize()
    assert store.available
    return store


def make_settings() -> Settings:
    # There is no environment admin key anymore; admin capability is role-based.
    return Settings(api_auth_enabled=True, api_key_pepper=_PEPPER)


def test_client_key_is_authenticated_without_storing_plaintext(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    settings = make_settings()
    user = store.create_user(email="Reader@Example.com", password_hash="h" * 60, display_name="Reader")
    token, metadata = store.create_api_key(
        user_id=user["id"], name="reader", scopes=["fetch"], expires_at=None, pepper=settings.api_key_pepper
    )

    principal = authenticate(f"Bearer {token}", settings, store)
    assert principal is not None
    assert principal.key_id == metadata["id"]
    assert principal.user_id == user["id"]
    assert principal.scopes == {"fetch"}
    assert authenticate("Bearer wrong", settings, store) is None
    with store._connect() as connection:
        assert connection.execute("SELECT secret_hmac FROM api_keys").fetchone()[0] != token


def test_admin_capability_is_role_based(tmp_path: Path) -> None:
    """Admin rights come from ``users.role`` via the session path, never a fixed env key."""
    store = make_store(tmp_path)
    admin = store.create_user(email="admin@example.com", password_hash="h" * 60, display_name="Admin", role="admin")
    member = store.create_user(email="member@example.com", password_hash="h" * 60, display_name="Member", role="user")

    def session_for(user_id: int) -> str:
        token = new_session_token()
        store.create_session(
            user_id=user_id,
            token_hash=hash_session_token(token),
            expires_at="2099-01-01T00:00:00+00:00",
            user_agent=None,
            ip_address=None,
        )
        return token

    admin_principal = authenticate_session(session_for(admin["id"]), store)
    assert admin_principal is not None and admin_principal.is_admin
    assert admin_principal.user_id == admin["id"]

    member_principal = authenticate_session(session_for(member["id"]), store)
    assert member_principal is not None and not member_principal.is_admin
    assert member_principal.user_id == member["id"]
