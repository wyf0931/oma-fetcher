from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import service
from .auth import Principal, authenticate
from .config import settings
from .mcp_server import MCP_HTTP_PATH, transport_security
from .mcp_server import mcp as mcp_server
from .models import (
    ApiEnvelope,
    ApiKeyCreateRequest,
    DocumentListRequest,
    FetchRequest,
    ProxySettingsRequest,
    SearchRequest,
)
from .storage import StorageError


def envelope(code: int, message: str, data: Any = None, meta: dict | None = None, status_code: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, headers=headers, content=ApiEnvelope(code=code, message=message, data=data, meta=meta or {}).model_dump())


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.initialize()
    if store.available:
        settings.apply_proxy_override(await asyncio.to_thread(store.get_app_setting, "proxy"))
    # A fresh Streamable HTTP app (and session manager) per lifespan keeps the
    # endpoint restartable, while the manager itself only supports one run().
    mcp_http.app = mcp_server.streamable_http_app(streamable_http_path=MCP_HTTP_PATH, transport_security=transport_security())
    try:
        async with mcp_server.session_manager.run():
            yield
    finally:
        mcp_http.app = None


app = FastAPI(title="OMA Fetcher", version="1.5.0", lifespan=lifespan, docs_url="/docs" if settings.api_docs_enabled else None, redoc_url="/redoc" if settings.api_docs_enabled else None)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.web_cors_origins), allow_credentials=False, allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "Prefer"])
store = service.store


@app.middleware("http")
async def static_cache_control(request: Request, call_next):
    """Make browsers revalidate the static UI instead of using heuristic caching."""
    response = await call_next(request)
    if request.method in {"GET", "HEAD"} and (request.url.path == "/" or request.url.path.endswith((".html", ".js", ".css", ".svg"))):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


class MCPServerApp:
    """Mount point delegating to the Streamable HTTP app built per lifespan."""

    def __init__(self) -> None:
        self.app: ASGIApp | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.app is None:
            response = envelope(4003, "MCP server is not ready", status_code=503)
            await response(scope, receive, send)
            return
        if scope["type"] in {"http", "websocket"}:
            # This gateway only serves the MCP endpoint, while the wrapped
            # Streamable HTTP app registers its route at "/".
            scope = dict(scope)
            scope["path"] = "/"
            scope["root_path"] = ""
        await self.app(scope, receive, send)


mcp_http = MCPServerApp()


class MCPAuthMiddleware:
    """Require a valid bearer token for `/mcp` when API authentication is on."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and settings.api_auth_enabled:
            headers = scope.get("headers") or []
            authorization = next((value.decode("latin-1") for key, value in headers if key == b"authorization"), None)
            if authenticate(authorization, settings, store) is None:
                response = envelope(
                    401,
                    "authentication required",
                    meta={"scheme": "Bearer"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


mcp_gateway = MCPAuthMiddleware(mcp_http)
app.router.routes.append(Route("/mcp", endpoint=mcp_gateway))
app.router.routes.append(Route("/mcp/", endpoint=mcp_gateway))


def proxy_settings_view(source: str = "active") -> dict[str, Any]:
    if source == "environment":
        enabled = settings.proxy_environment_enabled
        proxy_url = settings.proxy_environment_url
    else:
        enabled = settings.proxy_enabled
        proxy_url = settings.proxy_url
    parsed = urlsplit(proxy_url) if proxy_url else None
    return {
        "enabled": enabled,
        "scheme": parsed.scheme if parsed else "http",
        "server": parsed.hostname or "" if parsed else "",
        "port": parsed.port if parsed else None,
        "username_configured": bool(parsed and parsed.username),
        "password_configured": bool(parsed and parsed.password),
        "source": "override" if settings.proxy_override else "environment",
    }


@app.get("/api/settings/proxy", response_model=ApiEnvelope)
async def get_proxy_settings(request: Request, source: str = Query(default="active", pattern="^(active|environment)$")):
    denied = require_admin(request)
    if denied:
        return denied
    return envelope(0, "ok", proxy_settings_view(source))


@app.put("/api/settings/proxy", response_model=ApiEnvelope)
async def update_proxy_settings(request: Request, payload: ProxySettingsRequest):
    denied = require_admin(request)
    if denied:
        return denied
    if not payload.enabled:
        value = {"enabled": False, "url": ""}
    else:
        if not payload.server or payload.port is None:
            return envelope(1002, "proxy server and port are required", status_code=422)
        old = urlsplit(settings.proxy_url) if settings.proxy_url else None
        username = payload.username
        password = payload.password
        if not payload.clear_credentials and old:
            username = username if username is not None else unquote(old.username or "")
            password = password if password is not None else unquote(old.password or "")
        credentials = ""
        if username:
            credentials = quote(username, safe="")
            if password:
                credentials += f":{quote(password, safe='')}"
            credentials += "@"
        server = payload.server
        authority = f"[{server}]" if ":" in server and not server.startswith("[") else server
        proxy_url = f"{payload.scheme}://{credentials}{authority}:{payload.port}"
        try:
            parsed = urlsplit(proxy_url)
            valid_address = bool(parsed.hostname) and parsed.port == payload.port
        except ValueError:
            valid_address = False
        if not valid_address:
            return envelope(1002, "invalid proxy server or port", status_code=422)
        value = {"enabled": True, "url": proxy_url}
    try:
        await asyncio.to_thread(store.set_app_setting, "proxy", value)
    except StorageError as exc:
        return envelope(4004, str(exc), status_code=503)
    settings.apply_proxy_override(value)
    return envelope(0, "ok", proxy_settings_view())


@app.delete("/api/settings/proxy", response_model=ApiEnvelope)
async def reset_proxy_settings(request: Request):
    denied = require_admin(request)
    if denied:
        return denied
    try:
        await asyncio.to_thread(store.delete_app_setting, "proxy")
    except StorageError as exc:
        return envelope(4004, str(exc), status_code=503)
    settings.apply_proxy_override(None)
    return envelope(0, "ok", proxy_settings_view())


@app.middleware("http")
async def api_authentication(request: Request, call_next):
    if settings.api_auth_enabled and request.url.path.startswith("/api/"):
        principal = authenticate(request.headers.get("authorization"), settings, store)
        if principal is None:
            return envelope(401, "authentication required", meta={"scheme": "Bearer"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
        request.state.principal = principal
    return await call_next(request)


def require_scope(request: Request, scope: str) -> JSONResponse | None:
    if not settings.api_auth_enabled:
        return None
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is None or (not principal.is_admin and scope not in principal.scopes):
        return envelope(403, "insufficient scope", meta={"required_scope": scope}, status_code=403)
    return None


def require_admin(request: Request) -> JSONResponse | None:
    if not settings.api_auth_enabled:
        return None
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is None or not principal.is_admin:
        return envelope(403, "administrator key required", status_code=403)
    return None


@app.post("/api/keys", response_model=ApiEnvelope)
async def create_api_key(request: Request, payload: ApiKeyCreateRequest):
    denied = require_admin(request)
    if denied:
        return denied
    try:
        token, metadata = await asyncio.to_thread(
            store.create_api_key,
            name=payload.name,
            scopes=list(payload.scopes),
            expires_at=payload.expires_at.isoformat() if payload.expires_at else None,
            pepper=settings.api_key_pepper,
        )
        metadata["token"] = token
        return envelope(0, "ok", metadata)
    except StorageError as exc:
        return envelope(4004, str(exc), status_code=503)


@app.get("/api/keys", response_model=ApiEnvelope)
async def list_api_keys(request: Request):
    denied = require_admin(request)
    if denied:
        return denied
    try:
        return envelope(0, "ok", await asyncio.to_thread(store.list_api_keys))
    except StorageError as exc:
        return envelope(4004, str(exc), status_code=503)


@app.delete("/api/keys/{key_id}", response_model=ApiEnvelope)
async def delete_api_key(request: Request, key_id: int):
    denied = require_admin(request)
    if denied:
        return denied
    try:
        deleted = await asyncio.to_thread(store.delete_api_key, key_id)
        if not deleted:
            return envelope(4040, "API key not found", status_code=404)
        return envelope(0, "ok", {"id": key_id, "deleted": True})
    except StorageError as exc:
        return envelope(4004, str(exc), status_code=503)


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
async def healthz() -> JSONResponse:
    return readiness_response()


@app.get("/health", response_model=ApiEnvelope)
async def health() -> JSONResponse:
    """Compatibility alias for callers using the common /health path."""
    return readiness_response()


@app.get("/livez", response_model=ApiEnvelope)
async def livez() -> JSONResponse:
    """Low-cost liveness probe: no database or external dependency checks."""
    return envelope(0, "ok", {"status": "live"})


@app.get("/readyz", response_model=ApiEnvelope)
async def readyz() -> JSONResponse:
    """Readiness probe: the document store must be initialized before serving traffic."""
    return readiness_response()


def readiness_response() -> JSONResponse:
    if store.available:
        return envelope(0, "ok", {"status": "ready", "storage_ready": True})
    return envelope(
        4003,
        "service is not ready",
        {"status": "not_ready", "storage_ready": False},
        meta={"storage_error": store.initialization_error},
        status_code=503,
    )


@app.post("/api/fetch", response_model=ApiEnvelope)
async def fetch_page(request: Request, payload: FetchRequest, persist: bool | None = Query(default=None), prefer: str | None = Header(default=None)):
    denied = require_scope(request, "fetch")
    if denied:
        return denied
    should_persist, persistence_source = persistence_preference(persist, prefer)
    result = await service.fetch_page(
        url=str(payload.url),
        output_format=payload.output_format,
        timeout_seconds=payload.timeout_seconds,
        strategy=payload.strategy,
        persist=should_persist,
        persistence_source=persistence_source,
    )
    return envelope(result.code, result.message, result.data, result.meta, status_code=result.status_code, headers=result.headers)


@app.post("/api/search", response_model=ApiEnvelope)
async def search_documents(request: Request, payload: SearchRequest):
    denied = require_scope(request, "search")
    if denied:
        return denied
    result = await service.search_documents(
        query=payload.query,
        hostname=payload.hostname,
        published_after=payload.published_after,
        published_before=payload.published_before,
        limit=payload.limit,
    )
    return envelope(result.code, result.message, result.data, result.meta, status_code=result.status_code)


@app.get("/api/documents", response_model=ApiEnvelope)
async def list_documents(request: Request, filters: DocumentListRequest = Depends()):
    denied = require_scope(request, "search")
    if denied:
        return denied
    result = await service.list_documents(
        page=filters.page,
        page_size=filters.page_size,
        title=filters.title,
        sitename=filters.sitename,
        tags=filters.tags,
        content=filters.content,
    )
    return envelope(result.code, result.message, result.data, result.meta, status_code=result.status_code)


@app.get("/api/documents/{document_id}", response_model=ApiEnvelope)
async def get_document(request: Request, document_id: int):
    denied = require_scope(request, "search")
    if denied:
        return denied
    result = await service.get_document(document_id)
    return envelope(result.code, result.message, result.data, result.meta, status_code=result.status_code)


@app.delete("/api/documents/{document_id}", response_model=ApiEnvelope)
async def delete_document(request: Request, document_id: int):
    denied = require_scope(request, "fetch")
    if denied:
        return denied
    try:
        deleted = await asyncio.to_thread(store.delete_document, document_id)
        if not deleted:
            return envelope(4041, "document not found", status_code=404)
        return envelope(0, "ok", {"id": document_id, "deleted": True})
    except StorageError as exc:
        return envelope(4002, str(exc), status_code=503)


@app.get("/api/robots", response_model=ApiEnvelope)
async def get_robots(request: Request, url: str):
    denied = require_scope(request, "fetch")
    if denied:
        return denied
    result = await service.get_robots(url)
    return envelope(result.code, result.message, result.data, result.meta, status_code=result.status_code)


@app.get("/api/sitemap", response_model=ApiEnvelope)
async def get_sitemap(request: Request, url: str):
    denied = require_scope(request, "fetch")
    if denied:
        return denied
    result = await service.get_sitemap(url)
    return envelope(result.code, result.message, result.data, result.meta, status_code=result.status_code)


WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
if WEB_ROOT.is_dir():
    app.mount("/", StaticFiles(directory=WEB_ROOT, html=True), name="web")
