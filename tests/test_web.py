from fastapi.testclient import TestClient

from app.main import app


def test_static_assets_revalidate_and_include_mcp_dialog() -> None:
    with TestClient(app) as client:
        index = client.get("/")
        script = client.get("/app.js")

    assert index.status_code == 200
    assert script.status_code == 200
    assert index.headers["cache-control"] == "no-cache"
    assert script.headers["cache-control"] == "no-cache"
    assert "app.js?v=" in index.text
    assert "showMcpDialog" in script.text
    assert "get mcpConfig()" in script.text
    assert "FETCHLY_API_TOKEN" in script.text
    assert "headers:" in script.text
