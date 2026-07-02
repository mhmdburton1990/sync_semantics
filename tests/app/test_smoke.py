from __future__ import annotations

from fastapi.testclient import TestClient


def test_app_starts(client: TestClient) -> None:
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    assert spec["info"]["title"] == "sync_semantics"
    assert spec["info"]["version"] == "0.3.0"
