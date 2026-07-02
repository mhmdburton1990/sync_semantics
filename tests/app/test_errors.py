from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from databricks_to_pbi.app.errors import AppError, install_error_handlers


@pytest.fixture
def app_raising_app_error() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise AppError(
            code="boom",
            message="something exploded",
            suggestion="try not exploding",
            docs_link="https://example.com/boom",
            status_code=400,
        )

    return app


def test_app_error_serializes_to_envelope(
    app_raising_app_error: FastAPI,
) -> None:
    client = TestClient(app_raising_app_error)
    resp = client.get("/boom")
    assert resp.status_code == 400
    body = resp.json()
    assert body == {
        "code": "boom",
        "message": "something exploded",
        "suggestion": "try not exploding",
        "docs_link": "https://example.com/boom",
    }


def test_unhandled_exception_returns_generic_envelope() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/oops")
    def oops() -> dict[str, str]:
        raise RuntimeError("internal state corrupt")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/oops")
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "internal_error"
    assert "internal" in body["message"].lower()
    assert "internal state corrupt" not in body["message"]
