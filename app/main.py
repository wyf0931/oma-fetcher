from __future__ import annotations

import asyncio
import urllib.robotparser
from contextlib import asynccontextmanager

import trafilatura
import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import settings
from .discovery import DiscoveryError, DiscoveryFetchError, origin_for, robots, sitemap
from .fetchers import EscalatingFetcher, FetchError
from .metadata import extract_page_metadata
from .models import ApiEnvelope, FetchRequest
from .safety import UnsafeUrlError


def envelope(code: int, message: str, data: str | None = None, meta: dict | None = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=ApiEnvelope(code=code, message=message, data=data, meta=meta or {}).model_dump())


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="OMA Fetcher", version="0.1.0", lifespan=lifespan)
fetcher = EscalatingFetcher(settings)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    return envelope(1001, "invalid request", meta={"errors": exc.errors()}, status_code=422)


@app.get("/healthz", response_model=ApiEnvelope)
async def healthz() -> ApiEnvelope:
    return ApiEnvelope(code=0, message="ok", data="healthy")


@app.post("/api/fetch", response_model=ApiEnvelope)
async def fetch_page(payload: FetchRequest):
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
        return envelope(0, "ok", extracted, {"final_url": result.final_url, "strategy": result.strategy, "status_code": result.status_code, "content_type": result.content_type, "attempts": attempts, "page_metadata": page_metadata or {}})
    except UnsafeUrlError as exc:
        return envelope(1002, str(exc), status_code=400)
    except (FetchError, DiscoveryError, httpx.HTTPError) as exc:
        return envelope(2003, str(exc), meta={"attempts": getattr(exc, "attempts", [])}, status_code=502)


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
