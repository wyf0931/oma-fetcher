"""Service layer shared by the HTTP API and the MCP server.

Endpoints stay responsible for authentication, request parsing, and the
response envelope. Everything that actually fetches, discovers, extracts, or
queries the document store lives here so `/api/*` and `/mcp` cannot drift.
"""

from __future__ import annotations

import asyncio
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx
import trafilatura

from .config import settings
from .discovery import DiscoveryError, robots, sitemap
from .fetchers import EscalatingFetcher, FetchError
from .metadata import extract_page_metadata
from .quality import ContentAssessment, assess_page_content
from .safety import UnsafeUrlError
from .storage import DocumentStore, StorageError


@dataclass
class ServiceResult:
    """Transport-neutral result mirroring the public JSON envelope."""

    code: int
    message: str
    data: Any = None
    meta: dict[str, Any] = field(default_factory=dict)
    status_code: int = 200
    headers: dict[str, str] | None = None


fetcher = EscalatingFetcher(settings)
store = DocumentStore(settings.storage_path, settings.storage_user_dict_path)


async def fetch_page(
    *,
    url: str,
    output_format: str = "markdown",
    timeout_seconds: int = 45,
    strategy: str = "auto",
    persist: bool = False,
    persistence_source: str = "default",
) -> ServiceResult:
    try:
        if settings.enforce_robots:
            robots_text, _ = await robots(url, settings, store)
            if robots_text:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(robots_text.splitlines())
                if not parser.can_fetch(settings.user_agent, url):
                    return ServiceResult(2001, "blocked by robots.txt", meta={"url": url}, status_code=403)
        extracted: str | None = None
        page_metadata: dict | None = None
        assessment: ContentAssessment | None = None
        route = None
        hostname = urlsplit(url).hostname or ""
        if store.available and hostname:
            try:
                route = store.get_route(hostname, "page")
            except StorageError:
                route = None

        async def has_extractable_content(result):
            nonlocal extracted, page_metadata, assessment
            quality_text = await asyncio.to_thread(
                trafilatura.extract,
                result.html,
                url=result.final_url,
                output_format="txt",
            )
            assessment = await asyncio.to_thread(
                assess_page_content,
                html=result.html,
                url=result.final_url,
                trafilatura_content=quality_text or "",
                output_format=output_format,
            )
            if assessment.usable:
                extracted = assessment.content if assessment.extraction_method == "article_cards" else await asyncio.to_thread(
                    trafilatura.extract,
                    result.html,
                    url=result.final_url,
                    output_format=output_format,
                    with_metadata=output_format in {"json", "xml"},
                )
                page_metadata = await asyncio.to_thread(extract_page_metadata, result.html, result.final_url)
            return bool(extracted)

        result, attempts = await fetcher.fetch(
            url,
            timeout_seconds,
            strategy,
            accept=has_extractable_content,
            preferred_strategy=route.strategy if route else None,
        )
        if not extracted:  # Defensive: `accept` guarantees this branch is unreachable.
            return ServiceResult(2002, "page fetched but no main content could be extracted", meta={"attempts": attempts}, status_code=422)
        metadata = {
            "final_url": result.final_url,
            "strategy": result.strategy,
            "status_code": result.status_code,
            "content_type": result.content_type,
            "attempts": attempts,
            "proxy_enabled": settings.proxy_enabled,
            "page": page_metadata or {},
            "content_kind": assessment.kind if assessment else None,
            "extraction_method": assessment.extraction_method if assessment else None,
            "failback": {
                "route_hit": bool(route),
                "preferred_strategy": route.strategy if route else None,
                "accepted_strategy": result.strategy,
                "signals": assessment.signals if assessment else [],
            },
        }
        route_hostname = (page_metadata or {}).get("hostname") or urlsplit(result.final_url).hostname
        if store.available and route_hostname:
            try:
                if route and route.strategy != result.strategy:
                    store.record_route_failure(hostname=route_hostname, target_kind="page", strategy=route.strategy)
                store.record_route_success(
                    hostname=route_hostname,
                    target_kind="page",
                    strategy=result.strategy,
                    extraction_method=assessment.extraction_method if assessment and assessment.extraction_method else "trafilatura",
                    ttl_hours=settings.fetch_route_ttl_hours,
                )
            except StorageError:
                pass
        storage_metadata: dict[str, Any] = {"requested": persist, "saved": False, "source": persistence_source}
        response_headers: dict[str, str] | None = None
        if persist:
            try:
                saved = await asyncio.to_thread(
                    store.persist,
                    requested_url=url,
                    final_url=result.final_url,
                    content=extracted,
                    page=page_metadata or {},
                    strategy=result.strategy,
                    status_code=result.status_code,
                    content_type=result.content_type,
                    attempts=attempts,
                    raw_response={"code": 0, "message": "ok", "data": extracted, "meta": metadata},
                )
                storage_metadata.update({"saved": True, "document_id": saved.document_id, "deduplicated": saved.deduplicated})
                if persistence_source == "prefer":
                    response_headers = {"Preference-Applied": "persist"}
            except StorageError as exc:
                storage_metadata["error"] = str(exc)
                metadata["storage"] = storage_metadata
                return ServiceResult(4001, "fetch succeeded but document storage failed", extracted, metadata, status_code=500)
        metadata["storage"] = storage_metadata
        return ServiceResult(0, "ok", extracted, metadata, headers=response_headers)
    except UnsafeUrlError as exc:
        return ServiceResult(1002, str(exc), status_code=400)
    except (FetchError, DiscoveryError, httpx.HTTPError) as exc:
        return ServiceResult(2003, str(exc), meta={"attempts": getattr(exc, "attempts", [])}, status_code=502)


async def get_robots(url: str) -> ServiceResult:
    try:
        body, meta = await robots(url, settings, store)
        return ServiceResult(0, "ok", body, meta)
    except UnsafeUrlError as exc:
        return ServiceResult(1002, str(exc), status_code=400)
    except (DiscoveryError, httpx.HTTPError) as exc:
        return ServiceResult(3001, str(exc), meta={"attempts": getattr(exc, "attempts", [])}, status_code=502)


async def get_sitemap(url: str) -> ServiceResult:
    try:
        body, meta = await sitemap(url, settings, store)
        return ServiceResult(0, "ok", body, meta)
    except UnsafeUrlError as exc:
        return ServiceResult(1002, str(exc), status_code=400)
    except DiscoveryError as exc:
        return ServiceResult(3002, str(exc), status_code=404)


async def search_documents(
    *,
    query: str,
    hostname: str | None = None,
    published_after: str | None = None,
    published_before: str | None = None,
    limit: int = 20,
) -> ServiceResult:
    try:
        results = await asyncio.to_thread(
            store.search,
            query=query,
            hostname=hostname,
            published_after=published_after,
            published_before=published_before,
            limit=limit,
        )
        return ServiceResult(0, "ok", results, {"count": len(results)})
    except StorageError as exc:
        return ServiceResult(4002, str(exc), meta={"storage_available": store.available}, status_code=503)


async def list_documents(
    *,
    page: int = 1,
    page_size: int = 20,
    title: str | None = None,
    sitename: str | None = None,
    tags: str | None = None,
    content: str | None = None,
) -> ServiceResult:
    try:
        rows, total = await asyncio.to_thread(
            store.list_documents,
            page=page,
            page_size=page_size,
            title=title,
            sitename=sitename,
            tags=tags,
            content=content,
        )
        return ServiceResult(
            0,
            "ok",
            rows,
            {"page": page, "page_size": page_size, "total": total, "pages": (total + page_size - 1) // page_size},
        )
    except StorageError as exc:
        return ServiceResult(4002, str(exc), meta={"storage_available": store.available}, status_code=503)


async def get_document(document_id: int) -> ServiceResult:
    try:
        document = await asyncio.to_thread(store.get_document, document_id)
        if document is None:
            return ServiceResult(4041, "document not found", status_code=404)
        return ServiceResult(0, "ok", document)
    except StorageError as exc:
        return ServiceResult(4002, str(exc), status_code=503)
