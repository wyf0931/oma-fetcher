import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app import service
from app.config import settings
from app.main import app
from app.mcp_server import (
    fetchly_get_result,
    fetchly_list_results,
    fetchly_search_results,
    fetchly_sitemap,
    fetchly_web_fetch,
    mcp,
)
from app.service import ServiceResult
from app.storage import DocumentStore

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0"},
    },
}


def make_store(tmp_path: Path) -> DocumentStore:
    dictionary = tmp_path / "custom.txt"
    dictionary.write_text("国家标准 10\n外文版 10\n", encoding="utf-8")
    store = DocumentStore(str(tmp_path / "research.db"), str(dictionary))
    store.initialize()
    assert store.available
    return store


def persist_sample(store: DocumentStore):
    return store.persist(
        requested_url="https://samr.gov.cn/request",
        final_url="https://samr.gov.cn/final",
        content="市场监管总局公开征求国家标准外文版管理办法意见。",
        page={
            "url": "https://samr.gov.cn/final",
            "title": "国家标准外文版管理办法征求意见",
            "description": "市场监管总局公开征求意见",
            "hostname": "samr.gov.cn",
            "date": "2026-09-09",
            "tags": ["国家标准", "市场监管"],
        },
        strategy="httpx",
        status_code=200,
        content_type="text/html",
        attempts=[{"strategy": "httpx", "reason": "success"}],
        raw_response={"code": 0},
    )


def sse_result(response) -> dict:
    payload = [line[5:] for line in response.text.splitlines() if line.startswith("data: ")]
    assert payload, response.text
    return json.loads(payload[-1])


def test_tool_contract() -> None:
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}

    assert set(tools) == {
        "fetchly_web_fetch",
        "fetchly_robots",
        "fetchly_sitemap",
        "fetchly_search_results",
        "fetchly_list_results",
        "fetchly_get_result",
    }
    assert all(tool.description for tool in tools.values())
    assert tools["fetchly_web_fetch"].input_schema["required"] == ["url"]
    assert tools["fetchly_web_fetch"].input_schema["properties"]["output_format"]["enum"] == ["markdown", "txt", "json", "xml"]
    assert tools["fetchly_get_result"].input_schema["required"] == ["document_id"]


def test_fetch_tool_maps_service_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(**_: object) -> ServiceResult:
        return ServiceResult(
            0,
            "ok",
            "# Hello",
            {
                "final_url": "https://example.com/final",
                "strategy": "httpx",
                "status_code": 200,
                "content_type": "text/html",
                "content_kind": "article",
                "extraction_method": "trafilatura",
                "page": {"title": "Example", "sitename": "Example Site", "date": "2026-01-01", "language": "en"},
                "attempts": [{"strategy": "httpx", "reason": "success"}],
                "failback": {"signals": []},
                "storage": {"saved": True, "document_id": 42, "deduplicated": False},
            },
        )

    monkeypatch.setattr(service, "fetch_page", fake_fetch)
    result = asyncio.run(fetchly_web_fetch(url="https://example.com/article"))

    assert result["ok"] is True
    assert result["code"] == 0
    assert result["content"] == "# Hello"
    assert result["document_id"] == 42
    assert result["title"] == "Example"
    assert result["saved"] is True


def test_fetch_tool_returns_failure_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(**_: object) -> ServiceResult:
        return ServiceResult(2003, "all configured fetch strategies failed", meta={"attempts": [{"strategy": "httpx", "reason": "boom"}]}, status_code=502)

    monkeypatch.setattr(service, "fetch_page", fake_fetch)

    result = asyncio.run(fetchly_web_fetch(url="https://example.com/blocked"))

    assert result["ok"] is False
    assert result["code"] == 2003
    assert result["attempts"] == [{"strategy": "httpx", "reason": "boom"}]
    assert "content" not in result


def test_sitemap_tool_bounds_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = [f"https://example.com/{index}" for index in range(5)]
    async def fake_sitemap(_url: str) -> ServiceResult:
        return ServiceResult(0, "ok", json.dumps(urls), {"origin": "https://example.com", "sitemaps": ["https://example.com/sitemap.xml"], "count": 5, "truncated": False})

    monkeypatch.setattr(service, "get_sitemap", fake_sitemap)

    result = asyncio.run(fetchly_sitemap(url="https://example.com", max_urls=2))

    assert result["total"] == 5
    assert result["returned"] == 2
    assert result["urls"] == urls[:2]
    assert result["truncated"] is True


def test_result_tools_read_persisted_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path)
    saved = persist_sample(store)
    monkeypatch.setattr(service, "store", store)

    search = asyncio.run(fetchly_search_results(query="国家标准"))
    listing = asyncio.run(fetchly_list_results())
    detail = asyncio.run(fetchly_get_result(document_id=saved.document_id))
    missing = asyncio.run(fetchly_get_result(document_id=999_999))

    assert search["ok"] is True
    assert search["count"] == 1
    assert search["results"][0]["id"] == saved.document_id
    assert listing["total"] == 1
    assert listing["results"][0]["title"] == "国家标准外文版管理办法征求意见"
    assert detail["ok"] is True
    assert detail["document"]["content"].startswith("市场监管总局")
    assert missing["ok"] is False
    assert missing["code"] == 4041


def test_mcp_http_transport_lists_and_calls_tools() -> None:
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with TestClient(app, base_url="http://127.0.0.1:7890") as client:
        initialized = client.post("/mcp", json=INITIALIZE, headers=headers)
        assert initialized.status_code == 200
        session_id = initialized.headers["mcp-session-id"]

        session_headers = {**headers, "mcp-session-id": session_id}
        listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=session_headers)
        names = {tool["name"] for tool in sse_result(listed)["result"]["tools"]}
        called = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "fetchly_get_result", "arguments": {"document_id": 999_999}}},
            headers=session_headers,
        )
        result = sse_result(called)["result"]

    assert names == {
        "fetchly_web_fetch",
        "fetchly_robots",
        "fetchly_sitemap",
        "fetchly_search_results",
        "fetchly_list_results",
        "fetchly_get_result",
    }
    assert result["structuredContent"]["ok"] is False
    assert result["structuredContent"]["code"] == 4041


def test_mcp_requires_bearer_token_when_auth_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with TestClient(app, base_url="http://127.0.0.1:7890") as client:
        response = client.post("/mcp", json=INITIALIZE, headers=headers)

    assert response.status_code == 401
    assert response.json()["message"] == "authentication required"


def test_tools_enforce_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.delenv("FETCHLY_MCP_TOKEN", raising=False)

    result = asyncio.run(fetchly_search_results(query="anything"))

    assert result["ok"] is False
    assert result["code"] == 401


def test_http_tools_enforce_scopes_from_request_headers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path)
    monkeypatch.setattr(service, "store", store)
    monkeypatch.setattr(main_module, "store", store)
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "api_key_pepper", "p" * 32)
    token, _ = store.create_api_key(name="reader", scopes=["fetch"], expires_at=None, pepper=settings.api_key_pepper)

    base_headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    with TestClient(app, base_url="http://127.0.0.1:7890") as client:
        initialized = client.post("/mcp", json=INITIALIZE, headers=base_headers)
        assert initialized.status_code == 200
        session_headers = {**base_headers, "mcp-session-id": initialized.headers["mcp-session-id"]}
        called = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "fetchly_get_result", "arguments": {"document_id": 1}}},
            headers=session_headers,
        )
        result = sse_result(called)["result"]

    assert result["structuredContent"]["ok"] is False
    assert result["structuredContent"]["code"] == 403
    assert "insufficient scope" in result["structuredContent"]["message"]
