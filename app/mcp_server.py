"""MCP server exposing Fetchly's user-facing capabilities.

Transport: Streamable HTTP is mounted at ``/mcp`` by :mod:`app.main`, so the
normal ``bin/ops.sh start`` instance is immediately usable as an MCP server.
The module also runs over stdio (``python -m app.mcp_server``) for clients that
only support command-based servers.

Every tool returns the same envelope shape as the REST API::

    {"ok": true, "code": 0, "message": "ok", ...tool fields}

``code`` mirrors the REST envelope, and ``ok`` is simply ``code == 0``. Service
failures are values, not exceptions, so the agent can read ``message`` and
recover. Invalid arguments are rejected by the tool schema.
"""

from __future__ import annotations

import json
import os
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from . import service
from .auth import Principal, authenticate
from .config import settings

OutputFormat = Literal["markdown", "txt", "json", "xml"]
Strategy = Literal["auto", "httpx", "curl_cffi", "scrapling", "playwright"]

mcp = MCPServer(
    name="fetchly",
    title="Fetchly",
    instructions=(
        "Fetchly reads one URL at a time and can save the result to a local "
        "Results library. Use fetchly_web_fetch when you need the readable "
        "content of a web page; it returns Markdown by default and persists "
        "the page. Use fetchly_search_results or fetchly_list_results to find "
        "saved results, then fetchly_get_result to read the full stored "
        "document. Use fetchly_robots and fetchly_sitemap for discovery before "
        "crawling a site."
    ),
)


def _envelope(result: service.ServiceResult) -> dict[str, Any]:
    return {"ok": result.code == 0, "code": result.code, "message": result.message}


def _authorization(ctx: Context | None) -> str | None:
    if ctx is not None and ctx.headers:
        header = ctx.headers.get("authorization")
        if header:
            return header
    token = os.getenv("FETCHLY_MCP_TOKEN", "").strip()
    return f"Bearer {token}" if token else None


def _scope_denial(ctx: Context | None, scope: str) -> dict[str, Any] | None:
    """Mirror the REST scope rules for MCP tool calls.

    The HTTP transport already rejects unauthenticated requests when
    ``API_AUTH_ENABLED=on``; this check additionally enforces the per-tool
    scope and covers stdio clients via ``FETCHLY_MCP_TOKEN``. Denials are
    returned as an envelope so the agent sees the reason.
    """
    if not settings.api_auth_enabled:
        return None
    principal: Principal | None = authenticate(_authorization(ctx), settings, service.store)
    if principal is None:
        return {"ok": False, "code": 401, "message": "authentication required: send Authorization: Bearer <token> (or set FETCHLY_MCP_TOKEN)"}
    if not principal.is_admin and scope not in principal.scopes:
        return {"ok": False, "code": 403, "message": f"insufficient scope: {scope} required"}
    return None


@mcp.tool(
    name="fetchly_web_fetch",
    title="Fetch a web page",
    description=(
        "Fetch one URL with Fetchly and return clean extracted content "
        "(Markdown by default) plus title, site name, publication date, "
        "language, the winning fetch strategy, and fallback attempts. "
        "The page is saved to the local Results library by default; the "
        "returned document_id can be used with fetchly_get_result. "
        "Use this whenever you need the readable text of a web page."
    ),
)
async def fetchly_web_fetch(
    url: Annotated[str, Field(description="Absolute http(s) URL to read.")],
    output_format: Annotated[OutputFormat, Field(description="Extraction format: markdown (default), txt, json, or xml.")] = "markdown",
    timeout_seconds: Annotated[int, Field(ge=3, le=180, description="Shared timeout budget for the whole fallback chain.")] = 90,
    persist: Annotated[bool, Field(description="Save the result to the Results library.")] = True,
    strategy: Annotated[Strategy, Field(description="Pin one fetch strategy; keep auto unless diagnosing.")] = "auto",
    ctx: Context | None = None,
) -> dict[str, Any]:
    denied = _scope_denial(ctx, "fetch")
    if denied:
        return denied
    result = await service.fetch_page(
        url=url,
        output_format=output_format,
        timeout_seconds=timeout_seconds,
        strategy=strategy,
        persist=persist,
        persistence_source="mcp",
    )
    payload = {**_envelope(result), "requested_url": url}
    if result.data is not None:
        payload["content"] = result.data
    if result.code != 0:
        payload["attempts"] = result.meta.get("attempts", [])
        return payload
    page = result.meta.get("page") or {}
    storage = result.meta.get("storage") or {}
    failback = result.meta.get("failback") or {}
    payload.update(
        {
            "final_url": result.meta.get("final_url"),
            "strategy": result.meta.get("strategy"),
            "status_code": result.meta.get("status_code"),
            "content_type": result.meta.get("content_type"),
            "content_kind": result.meta.get("content_kind"),
            "extraction_method": result.meta.get("extraction_method"),
            "title": page.get("title"),
            "site_name": page.get("sitename"),
            "published_at": page.get("date"),
            "language": page.get("language"),
            "saved": storage.get("saved", False),
            "document_id": storage.get("document_id"),
            "deduplicated": storage.get("deduplicated"),
            "attempts": result.meta.get("attempts", []),
            "signals": failback.get("signals", []),
        }
    )
    return payload


@mcp.tool(
    name="fetchly_robots",
    title="Read robots.txt",
    description=(
        "Read an origin's robots.txt through Fetchly's resilient discovery "
        "chain. Returns the raw directives, whether the file was found, and "
        "the HTTP status. Use it before crawling or bulk fetching a site. "
        "A missing robots.txt is reported as found=false, not an error."
    ),
)
async def fetchly_robots(
    url: Annotated[str, Field(description="Any URL on the target origin.")],
    ctx: Context | None = None,
) -> dict[str, Any]:
    denied = _scope_denial(ctx, "fetch")
    if denied:
        return denied
    result = await service.get_robots(url)
    meta = result.meta
    return {
        **_envelope(result),
        "url": meta.get("url") or url,
        "found": bool(meta.get("found")),
        "status_code": meta.get("status_code"),
        "content": result.data or "",
        "attempts": meta.get("attempts", []),
    }


@mcp.tool(
    name="fetchly_sitemap",
    title="Discover sitemap URLs",
    description=(
        "Expand a domain, page URL, or direct sitemap URL into page URLs "
        "using sitemap discovery, robots.txt declarations, and nested sitemap "
        "indexes. Returns a bounded list of URLs plus the sitemap documents "
        "used. Use it to plan crawling; raise max_urls only when needed."
    ),
)
async def fetchly_sitemap(
    url: Annotated[str, Field(description="Domain, page URL, or sitemap URL.")],
    max_urls: Annotated[int, Field(ge=1, le=10000, description="Maximum URLs to return to the caller.")] = 200,
    ctx: Context | None = None,
) -> dict[str, Any]:
    denied = _scope_denial(ctx, "fetch")
    if denied:
        return denied
    result = await service.get_sitemap(url)
    if result.code != 0:
        return {**_envelope(result), "urls": [], "total": 0, "returned": 0, "truncated": False}
    try:
        decoded = json.loads(result.data or "[]")
    except (TypeError, ValueError):
        decoded = []
    urls: list[str] = [item for item in decoded if isinstance(item, str)] if isinstance(decoded, list) else []
    returned = urls[:max_urls]
    return {
        **_envelope(result),
        "origin": result.meta.get("origin"),
        "total": len(urls),
        "returned": len(returned),
        "truncated": bool(result.meta.get("truncated")) or len(returned) < len(urls),
        "urls": returned,
        "sitemaps": result.meta.get("sitemaps", []),
    }


@mcp.tool(
    name="fetchly_search_results",
    title="Search saved results",
    description=(
        "Search the local Results library with jieba tokenization and SQLite "
        "FTS5. Matches title, description, tags, and content, optionally "
        "filtered by exact hostname and publication date range. Returns "
        "compact rows with a highlighted snippet; use fetchly_get_result for "
        "the full document content."
    ),
)
async def fetchly_search_results(
    query: Annotated[str, Field(min_length=1, max_length=500, description="Search terms.")],
    hostname: Annotated[str | None, Field(description="Exact hostname filter, e.g. example.com.")] = None,
    published_after: Annotated[str | None, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Inclusive publication date, YYYY-MM-DD.")] = None,
    published_before: Annotated[str | None, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Inclusive publication date, YYYY-MM-DD.")] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="Maximum rows to return.")] = 20,
    ctx: Context | None = None,
) -> dict[str, Any]:
    denied = _scope_denial(ctx, "search")
    if denied:
        return denied
    result = await service.search_documents(
        query=query,
        hostname=hostname,
        published_after=published_after,
        published_before=published_before,
        limit=limit,
    )
    rows = result.data or []
    return {**_envelope(result), "count": len(rows), "results": rows}


@mcp.tool(
    name="fetchly_list_results",
    title="List saved results",
    description=(
        "Browse the local Results library with pagination and optional "
        "substring filters on title, site name, tags, or content. Returns "
        "compact rows ordered by most recently fetched; use "
        "fetchly_get_result for the full document content."
    ),
)
async def fetchly_list_results(
    page: Annotated[int, Field(ge=1, description="1-based page number.")] = 1,
    page_size: Annotated[int, Field(ge=1, le=100, description="Rows per page.")] = 20,
    title: Annotated[str | None, Field(max_length=200, description="Substring filter on the title.")] = None,
    sitename: Annotated[str | None, Field(max_length=200, description="Substring filter on the site name.")] = None,
    tags: Annotated[str | None, Field(max_length=200, description="Substring filter on stored tags.")] = None,
    content: Annotated[str | None, Field(max_length=500, description="Substring filter on title or content.")] = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    denied = _scope_denial(ctx, "search")
    if denied:
        return denied
    result = await service.list_documents(
        page=page,
        page_size=page_size,
        title=title,
        sitename=sitename,
        tags=tags,
        content=content,
    )
    meta = result.meta
    return {
        **_envelope(result),
        "page": meta.get("page", page),
        "page_size": meta.get("page_size", page_size),
        "total": meta.get("total", 0),
        "pages": meta.get("pages", 0),
        "results": result.data or [],
    }


@mcp.tool(
    name="fetchly_get_result",
    title="Read a saved result",
    description=(
        "Read one document from the Results library, including its full "
        "extracted content, tags, semantic page metadata, and fetch history. "
        "Use the document_id returned by fetchly_web_fetch, "
        "fetchly_search_results, or fetchly_list_results."
    ),
)
async def fetchly_get_result(
    document_id: Annotated[int, Field(gt=0, description="Document ID from the Results library.")],
    ctx: Context | None = None,
) -> dict[str, Any]:
    denied = _scope_denial(ctx, "search")
    if denied:
        return denied
    result = await service.get_document(document_id)
    return {**_envelope(result), "document": result.data}


def main() -> None:
    """Run the MCP server over stdio for clients without HTTP support."""
    service.store.initialize()
    if service.store.available:
        settings.apply_proxy_override(service.store.get_app_setting("proxy"))
    mcp.run(transport="stdio")


MCP_HTTP_PATH = "/"


def transport_security() -> TransportSecuritySettings:
    """Allow localhost by default and let deployments extend the allowlists."""

    def entries(variable: str, defaults: list[str]) -> list[str]:
        extra = [item.strip() for item in os.getenv(variable, "").split(",") if item.strip()]
        return defaults + extra

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=entries("FETCHLY_MCP_ALLOWED_HOSTS", ["127.0.0.1:*", "localhost:*", "[::1]:*"]),
        allowed_origins=entries("FETCHLY_MCP_ALLOWED_ORIGINS", ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]),
    )


if __name__ == "__main__":
    main()
