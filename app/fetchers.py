from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from time import monotonic
from collections.abc import Awaitable, Callable
from typing import Literal

import httpx

from .config import Settings
from .safety import validate_public_url


class FetchError(RuntimeError):
    pass


@dataclass
class FetchResult:
    html: str
    final_url: str
    status_code: int
    strategy: str
    content_type: str


BLOCK_PAGE_RE = re.compile(
    r"(captcha|cf-chl|cloudflare.*(challenge|attention)|verify you are human|access denied|just a moment)",
    re.IGNORECASE,
)


def is_usable(status_code: int, html: str) -> bool:
    if not 200 <= status_code < 300 or not html.strip():
        return False
    sample = html[:20_000]
    return not bool(BLOCK_PAGE_RE.search(sample))


class EscalatingFetcher:
    """Fetches once per strategy; extraction quality decides escalation later."""

    def __init__(self, config: Settings):
        self.config = config

    async def fetch(
        self,
        url: str,
        timeout_seconds: int,
        strategy: str = "auto",
        accept: Callable[[FetchResult], Awaitable[bool]] | None = None,
    ) -> tuple[FetchResult, list[dict[str, str]]]:
        validate_public_url(url, allow_private=self.config.allow_private_networks)
        attempts: list[dict[str, str]] = []
        names: list[Literal["httpx", "curl_cffi", "scrapling", "playwright"]] = [
            "httpx", "curl_cffi", "scrapling", "playwright"
        ]
        if strategy != "auto":
            names = [strategy]  # type: ignore[list-item]
        deadline = monotonic() + timeout_seconds
        for name in names:
            remaining = deadline - monotonic()
            if remaining <= 0:
                attempts.append({"strategy": name, "reason": "request deadline exhausted"})
                break
            try:
                result = await getattr(self, f"_{name}")(url, min(remaining, 60))
                validate_public_url(result.final_url, allow_private=self.config.allow_private_networks)
                if is_usable(result.status_code, result.html):
                    if accept is not None and not await accept(result):
                        attempts.append({"strategy": name, "reason": "no extractable main content"})
                        continue
                    attempts.append({"strategy": name, "reason": "success"})
                    return result, attempts
                attempts.append({"strategy": name, "reason": f"unusable response (HTTP {result.status_code})"})
            except Exception as exc:  # Libraries use unrelated exception classes.
                attempts.append({"strategy": name, "reason": self._safe_reason(exc)})
        raise FetchError("all configured fetch strategies failed: " + "; ".join(a["reason"] for a in attempts))

    @staticmethod
    def _safe_reason(error: Exception) -> str:
        message = str(error).replace("\n", " ")
        return (message[:220] or error.__class__.__name__)

    async def _httpx(self, url: str, timeout: float) -> FetchResult:
        headers = {"User-Agent": self.config.user_agent, "Accept": "text/html,application/xhtml+xml"}
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout) as client:
            response = await client.get(url)
            content = response.content[: self.config.max_response_bytes]
        return FetchResult(content.decode(response.encoding or "utf-8", errors="replace"), str(response.url), response.status_code, "httpx", response.headers.get("content-type", ""))

    async def _curl_cffi(self, url: str, timeout: float) -> FetchResult:
        def run() -> FetchResult:
            from curl_cffi import requests

            response = requests.get(url, impersonate="chrome", timeout=timeout, allow_redirects=True)
            return FetchResult(response.content[: self.config.max_response_bytes].decode("utf-8", errors="replace"), response.url, response.status_code, "curl_cffi", response.headers.get("content-type", ""))
        return await asyncio.to_thread(run)

    async def _scrapling(self, url: str, timeout: float) -> FetchResult:
        def run() -> FetchResult:
            from scrapling.fetchers import StealthyFetcher

            page = StealthyFetcher.fetch(url, headless=True, timeout=int(timeout * 1000), block_webrtc=True)
            return FetchResult(page.html[: self.config.max_response_bytes], str(page.url), int(page.status), "scrapling", page.headers.get("content-type", ""))
        return await asyncio.to_thread(run)

    async def _playwright(self, url: str, timeout: float) -> FetchResult:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
            try:
                page = await browser.new_page(user_agent=self.config.user_agent)
                response = await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
                await page.wait_for_timeout(300)
                html = (await page.content())[: self.config.max_response_bytes]
                return FetchResult(html, page.url, response.status if response else 200, "playwright", response.headers.get("content-type", "") if response else "")
            finally:
                await browser.close()
