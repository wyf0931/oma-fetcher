from __future__ import annotations

import gzip
import json
import asyncio
import logging
import random
from collections import deque
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

from .config import Settings
from .safety import validate_public_url


class DiscoveryError(RuntimeError):
    pass


class DiscoveryFetchError(DiscoveryError):
    def __init__(self, message: str, attempts: list[dict[str, object]]):
        super().__init__(message)
        self.attempts = attempts


logger = logging.getLogger(__name__)


def origin_for(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


async def _get(url: str, config: Settings, timeout: float = 15) -> httpx.Response:
    validate_public_url(url, allow_private=config.allow_private_networks)
    attempts: list[dict[str, object]] = []

    def record(strategy: str, round_number: int, *, status: int | None = None, error: Exception | None = None) -> None:
        attempt: dict[str, object] = {"strategy": strategy, "round": round_number}
        if status is not None:
            attempt["status_code"] = status
        if error is not None:
            attempt["error"] = str(error).replace("\n", " ")[:180] or error.__class__.__name__
        attempts.append(attempt)
        logger.info("discovery.fetch url=%s strategy=%s round=%s status=%s error=%s", url, strategy, round_number, status, attempt.get("error", ""))

    def success(response: httpx.Response) -> httpx.Response:
        validate_public_url(str(response.url), allow_private=config.allow_private_networks)
        if len(response.content) > config.max_response_bytes:
            raise DiscoveryError("response exceeds configured size limit")
        response.extensions["fetch_attempts"] = attempts
        return response

    def curl_cffi_get() -> httpx.Response:
        from curl_cffi import requests

        # Some WAF error pages advertise gzip but send an undecodable body.
        # Identity encoding avoids losing a valid robots/sitemap response to
        # that protocol mismatch while retaining curl-cffi's TLS fingerprint.
        fetched = requests.get(
            url,
            impersonate="chrome",
            timeout=timeout,
            allow_redirects=True,
            headers={"Accept-Encoding": "identity"},
        )
        return httpx.Response(
            fetched.status_code,
            content=fetched.content,
            headers=fetched.headers,
            request=httpx.Request("GET", fetched.url),
        )

    def scrapling_get() -> httpx.Response:
        from scrapling.fetchers import Fetcher

        fetched = Fetcher.get(url, impersonate="chrome", stealthy_headers=True, timeout=int(timeout))
        return httpx.Response(
            fetched.status,
            content=fetched.body,
            headers={"content-type": fetched.headers.get("content-type", "")},
            request=httpx.Request("GET", str(fetched.url)),
        )

    for round_number in range(1, config.discovery_retries + 2):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": config.user_agent}) as client:
                response = await client.get(url)
            record("httpx", round_number, status=response.status_code)
            if response.status_code not in {403, 429} and response.status_code < 500:
                return success(response)
        except httpx.HTTPError as exc:
            record("httpx", round_number, error=exc)

        try:
            response = await asyncio.to_thread(curl_cffi_get)
            record("curl_cffi", round_number, status=response.status_code)
            if response.status_code not in {403, 429} and response.status_code < 500:
                return success(response)
        except Exception as exc:
            record("curl_cffi", round_number, error=exc)

        try:
            response = await asyncio.to_thread(scrapling_get)
            record("scrapling", round_number, status=response.status_code)
            if response.status_code not in {403, 429} and response.status_code < 500:
                return success(response)
        except Exception as exc:
            record("scrapling", round_number, error=exc)

        if round_number <= config.discovery_retries:
            delay = config.discovery_retry_delay * round_number + random.uniform(0, config.discovery_retry_delay)
            logger.info("discovery.fetch retrying url=%s after_seconds=%.2f", url, delay)
            await asyncio.sleep(delay)
    raise DiscoveryFetchError("all discovery fetch strategies were rejected or failed", attempts)


async def robots(url: str, config: Settings) -> tuple[str, dict[str, object]]:
    robots_url = urljoin(origin_for(url) + "/", "robots.txt")
    response = await _get(robots_url, config)
    if response.status_code == 404:
        return "", {"url": str(response.url), "status_code": 404, "found": False, "attempts": response.extensions.get("fetch_attempts", [])}
    if not response.is_success:
        raise DiscoveryFetchError(f"robots.txt returned HTTP {response.status_code}", response.extensions.get("fetch_attempts", []))
    return response.text, {"url": str(response.url), "status_code": response.status_code, "found": True, "attempts": response.extensions.get("fetch_attempts", [])}


def sitemap_declarations(robots_text: str) -> list[str]:
    return [line.split(":", 1)[1].strip() for line in robots_text.splitlines() if line.lower().startswith("sitemap:") and ":" in line]


def _parse_sitemap(body: bytes) -> tuple[list[str], list[str]]:
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise DiscoveryError("sitemap is not valid XML") from exc
    kind = root.tag.rsplit("}", 1)[-1].lower()
    locations = [(node.text or "").strip() for node in root.iter() if node.tag.rsplit("}", 1)[-1].lower() == "loc"]
    locations = [location for location in locations if location.startswith(("http://", "https://"))]
    return (locations, []) if kind == "urlset" else ([], locations) if kind == "sitemapindex" else ([], [])


async def sitemap(url: str, config: Settings) -> tuple[str, dict[str, object]]:
    origin = origin_for(url)
    explicit = url.lower().endswith((".xml", ".xml.gz"))
    robots_text = ""
    robots_meta: dict[str, object] = {}
    if not explicit:
        try:
            robots_text, robots_meta = await robots(origin, config)
        except DiscoveryError:
            robots_meta = {"found": False}
    candidates = [url] if explicit else sitemap_declarations(robots_text) + [urljoin(origin + "/", path) for path in ("sitemap.xml", "sitemap_index.xml")]
    pending = deque((candidate, 0) for candidate in dict.fromkeys(candidates))
    seen_maps: set[str] = set()
    urls: set[str] = set()
    while pending and len(urls) < config.sitemap_max_urls:
        sitemap_url, depth = pending.popleft()
        if sitemap_url in seen_maps or depth > config.sitemap_max_depth:
            continue
        seen_maps.add(sitemap_url)
        try:
            response = await _get(sitemap_url, config)
            if not response.is_success:
                continue
            leaves, children = _parse_sitemap(response.content)
        except (DiscoveryError, httpx.HTTPError):
            continue
        for leaf in leaves:
            if len(urls) >= config.sitemap_max_urls:
                break
            urls.add(leaf)
        pending.extend((child, depth + 1) for child in children)
    # Trafilatura also knows site-specific sitemap conventions. It is a fallback
    # because the explicit parser above gives us strict limits and provenance.
    if not urls and not explicit:
        try:
            from trafilatura.sitemaps import sitemap_search

            discovered = await asyncio.to_thread(
                sitemap_search, origin, None, False, 0.0, config.sitemap_max_urls
            )
            urls.update(item for item in discovered if item.startswith(("http://", "https://")))
        except Exception:
            # A missing/non-standard sitemap remains a normal discovery miss.
            pass
    if not urls:
        raise DiscoveryError("no sitemap URLs were discovered")
    return json.dumps(sorted(urls), ensure_ascii=False), {
        "origin": origin,
        "robots": robots_meta,
        "sitemaps": sorted(seen_maps),
        "count": len(urls),
        "truncated": len(urls) >= config.sitemap_max_urls,
    }
