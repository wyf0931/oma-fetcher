import pytest

from app.safety import UnsafeUrlError, validate_public_url
from app.config import Settings


def test_rejects_url_credentials() -> None:
    with pytest.raises(UnsafeUrlError, match="credentials"):
        validate_public_url("https://user:pass@example.com/", allow_private=False)


def test_private_override_skips_dns_resolution() -> None:
    validate_public_url("http://127.0.0.1:8000/", allow_private=True)


def test_authenticated_proxy_mapping_redacts_credentials() -> None:
    config = Settings(proxy_enabled=True, proxy_url="http://proxy-user:proxy-password@proxy.example.test:80/")
    assert config.proxy_mapping == {
        "http": "http://proxy-user:proxy-password@proxy.example.test:80/",
        "https": "http://proxy-user:proxy-password@proxy.example.test:80/",
    }
    assert config.proxy_label == "http://proxy.example.test:80"
    assert config.browser_proxy == {
        "server": "http://proxy.example.test:80",
        "username": "proxy-user",
        "password": "proxy-password",
    }
    assert "proxy-password" not in config.redact("failed through http://proxy-user:proxy-password@proxy.example.test:80/")
