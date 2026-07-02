from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from databricks_to_pbi.app.main import create_app


def test_app_serves_index_when_dist_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><h1>UI</h1>", encoding="utf-8")
    monkeypatch.setenv("DBX2PBI_FRONTEND_DIST", str(dist))

    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "UI" in resp.text


def test_app_returns_helpful_message_when_dist_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DBX2PBI_FRONTEND_DIST", raising=False)
    # Ensure the default `frontend/dist` doesn't accidentally exist
    monkeypatch.setenv("DBX2PBI_FRONTEND_DIST", "/tmp/__nonexistent_dist__")
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "pnpm build" in resp.text


def test_spa_routes_return_index_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPA client-side routes (/target, /preview, ...) must return index.html
    instead of 404 so React Router can take over."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><h1>SPA</h1>", encoding="utf-8")
    monkeypatch.setenv("DBX2PBI_FRONTEND_DIST", str(dist))

    app = create_app()
    with TestClient(app) as client:
        for path in ("/target", "/preview", "/apply", "/history", "/some/deep/path"):
            resp = client.get(path)
            assert resp.status_code == 200, f"{path} returned {resp.status_code}"
            assert "SPA" in resp.text, f"{path} did not return index.html"


def test_api_routes_still_404_for_unknown_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPA catch-all must NOT swallow /api/* — those should still 404."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><h1>SPA</h1>", encoding="utf-8")
    monkeypatch.setenv("DBX2PBI_FRONTEND_DIST", str(dist))

    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/api/this-does-not-exist")
        assert resp.status_code == 404
