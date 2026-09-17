import asyncio

import pytest

from app.fetchers import EscalatingFetcher, FetchError, FetchResult
from app.config import Settings


def test_fetch_error_preserves_attempts() -> None:
    attempts = [{"strategy": "httpx", "reason": "no extractable main content"}]
    error = FetchError("failed", attempts)
    assert error.attempts == attempts


def test_scrapling_response_body_is_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePage:
        body = "<article>正文</article>".encode("utf-8")
        encoding = "utf-8"
        url = "https://example.test/"
        status = 200
        headers = {"content-type": "text/html"}

    class FakeStealth:
        @classmethod
        def fetch(cls, url, **kwargs):
            return FakePage()

    import scrapling.fetchers

    monkeypatch.setattr(scrapling.fetchers, "StealthyFetcher", FakeStealth)
    result = asyncio.run(EscalatingFetcher(Settings())._scrapling("https://example.test/", 5))
    assert result.html == "<article>正文</article>"

