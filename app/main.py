from __future__ import annotations

import asyncio
import urllib.robotparser
from contextlib import asynccontextmanager
from typing import Any

import trafilatura
import httpx
from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import settings
from .discovery import DiscoveryError, DiscoveryFetchError, origin_for, robots, sitemap
from .fetchers import EscalatingFetcher, FetchError
from .metadata import extract_page_metadata
from .models import ApiEnvelope, FetchRequest, SearchRequest
from .safety import UnsafeUrlError
from .storage import DocumentStore, StorageError


def envelope(code: int, message: str, data: Any = None, meta: dict | None = None, status_code: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, headers=headers, content=ApiEnvelope(code=code, message=message, data=data, meta=meta or {}).model_dump())


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.initialize()
    yield


app = FastAPI(title="OMA Fetcher", version="0.1.0", lifespan=lifespan)
fetcher = EscalatingFetcher(settings)
store = DocumentStore(settings.storage_path, settings.storage_user_dict_path)


def persistence_preference(query_value: bool | None, prefer: str | None, default: bool | None = None) -> tuple[bool, str]:
    if query_value is not None:
        return query_value, "query"
    if prefer:
        for preference in prefer.split(","):
            if preference.strip().split(";", 1)[0].strip().lower() == "persist":
                return True, "prefer"
    return settings.storage_save_default if default is None else default, "default"


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    return envelope(1001, "invalid request", meta={"errors": exc.errors()}, status_code=422)


@app.get("/healthz", response_model=ApiEnvelope)
async def healthz() -> ApiEnvelope:
    return ApiEnvelope(code=0, message="ok", data="healthy")


@app.post("/api/fetch", response_model=ApiEnvelope)
async def fetch_page(payload: FetchRequest, persist: bool | None = Query(default=None), prefer: str | None = Header(default=None)):
    url = str(payload.url)
    try:
        if settings.enforce_robots:
            robots_text, _ = await robots(url, settings)
            if robots_text:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(robots_text.splitlines())
                if not parser.can_fetch(settings.user_agent, url):
                    return envelope(2001, "blocked by robots.txt", meta={"url": url}, status_code=403)
        extracted: str | None = None
        page_metadata: dict | None = None

        async def has_extractable_content(result):
            nonlocal extracted, page_metadata
            extracted = await asyncio.to_thread(
                trafilatura.extract,
                result.html,
                url=result.final_url,
                output_format=payload.output_format,
                with_metadata=payload.output_format in {"json", "xml"},
            )
            if extracted:
                page_metadata = await asyncio.to_thread(extract_page_metadata, result.html, result.final_url)
            return bool(extracted)

        result, attempts = await fetcher.fetch(url, payload.timeout_seconds, payload.strategy, accept=has_extractable_content)
        if not extracted:  # Defensive: `accept` guarantees this branch is unreachable.
            return envelope(2002, "page fetched but no main content could be extracted", meta={"attempts": attempts}, status_code=422)
        metadata = {
            "final_url": result.final_url,
            "strategy": result.strategy,
            "status_code": result.status_code,
            "content_type": result.content_type,
            "attempts": attempts,
            "proxy_enabled": settings.proxy_enabled,
            "page": page_metadata or {},
        }
        should_persist, persistence_source = persistence_preference(persist, prefer)
        storage_metadata: dict[str, Any] = {"requested": should_persist, "saved": False, "source": persistence_source}
        response_headers: dict[str, str] | None = None
        if should_persist:
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
                return envelope(4001, "fetch succeeded but document storage failed", extracted, metadata, status_code=500)
        metadata["storage"] = storage_metadata
        return envelope(0, "ok", extracted, metadata, headers=response_headers)
    except UnsafeUrlError as exc:
        return envelope(1002, str(exc), status_code=400)
    except (FetchError, DiscoveryError, httpx.HTTPError) as exc:
        return envelope(2003, str(exc), meta={"attempts": getattr(exc, "attempts", [])}, status_code=502)


@app.post("/api/search", response_model=ApiEnvelope)
async def search_documents(payload: SearchRequest):
    try:
        results = await asyncio.to_thread(
            store.search,
            query=payload.query,
            hostname=payload.hostname,
            published_after=payload.published_after,
            published_before=payload.published_before,
            limit=payload.limit,
        )
        return envelope(0, "ok", results, {"count": len(results)})
    except StorageError as exc:
        return envelope(4002, str(exc), meta={"storage_available": store.available}, status_code=503)


@app.get("/api/robots", response_model=ApiEnvelope)
async def get_robots(url: str):
    try:
        body, meta = await robots(url, settings)
        return envelope(0, "ok", body, meta)
    except UnsafeUrlError as exc:
        return envelope(1002, str(exc), status_code=400)
    except (DiscoveryError, httpx.HTTPError) as exc:
        return envelope(3001, str(exc), meta={"attempts": getattr(exc, "attempts", [])}, status_code=502)


@app.get("/api/sitemap", response_model=ApiEnvelope)
async def get_sitemap(url: str):
    try:
        body, meta = await sitemap(url, settings)
        return envelope(0, "ok", body, meta)
    except UnsafeUrlError as exc:
        return envelope(1002, str(exc), status_code=400)
    except DiscoveryError as exc:
        return envelope(3002, str(exc), status_code=404)
