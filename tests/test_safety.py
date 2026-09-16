import pytest

from app.safety import UnsafeUrlError, validate_public_url


def test_rejects_url_credentials() -> None:
    with pytest.raises(UnsafeUrlError, match="credentials"):
        validate_public_url("https://user:pass@example.com/", allow_private=False)


def test_private_override_skips_dns_resolution() -> None:
    validate_public_url("http://127.0.0.1:8000/", allow_private=True)
