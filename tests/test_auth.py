from pathlib import Path

from app.auth import authenticate
from app.config import Settings
from app.storage import DocumentStore


def test_client_key_is_authenticated_without_storing_plaintext(tmp_path: Path) -> None:
    store = DocumentStore(str(tmp_path / "keys.db"), str(tmp_path / "custom.txt"))
    store.initialize()
    settings = Settings(api_auth_enabled=True, api_admin_key="a" * 32, api_key_pepper="p" * 32)
    token, metadata = store.create_api_key(name="reader", scopes=["fetch"], expires_at=None, pepper=settings.api_key_pepper)

    principal = authenticate(f"Bearer {token}", settings, store)
    assert principal is not None
    assert principal.key_id == metadata["id"]
    assert principal.scopes == {"fetch"}
    assert authenticate("Bearer wrong", settings, store) is None
    with store._connect() as connection:
        assert connection.execute("SELECT secret_hmac FROM api_keys").fetchone()[0] != token


def test_admin_key_is_environment_only(tmp_path: Path) -> None:
    store = DocumentStore(str(tmp_path / "keys.db"), str(tmp_path / "custom.txt"))
    store.initialize()
    settings = Settings(api_auth_enabled=True, api_admin_key="a" * 32, api_key_pepper="p" * 32)
    principal = authenticate("Bearer " + settings.api_admin_key, settings, store)
    assert principal is not None and principal.is_admin
