from fastapi.testclient import TestClient

from app.main import app, store


def test_liveness_and_readiness_endpoints() -> None:
    with TestClient(app) as client:
        live = client.get("/livez")
        ready = client.get("/readyz")
        health = client.get("/health")
        healthz = client.get("/healthz")

    assert live.status_code == 200
    assert live.json()["data"]["status"] == "live"
    assert ready.status_code == 200
    assert ready.json()["data"] == {"status": "ready", "storage_ready": True}
    assert health.status_code == 200
    assert healthz.status_code == 200


def test_readiness_returns_503_when_storage_failed() -> None:
    with TestClient(app) as client:
        original_error = store.initialization_error
        try:
            store.initialization_error = "simulated initialization failure"
            response = client.get("/readyz")
        finally:
            store.initialization_error = original_error

    assert response.status_code == 503
    assert response.json()["data"]["status"] == "not_ready"
