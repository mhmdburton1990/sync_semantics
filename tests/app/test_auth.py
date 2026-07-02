from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from databricks_to_pbi.app.auth import OBO_HEADER, current_obo_token


@pytest.fixture
def app_with_protected_route() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    def whoami(token: str = Depends(current_obo_token)) -> dict[str, str]:
        return {"token_prefix": token[:8]}

    return app


def test_protected_route_requires_obo_header(
    app_with_protected_route: FastAPI,
) -> None:
    client = TestClient(app_with_protected_route)
    resp = client.get("/whoami")
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"]["code"] == "missing_obo_token"


def test_protected_route_returns_token_when_present(
    app_with_protected_route: FastAPI,
) -> None:
    client = TestClient(app_with_protected_route)
    resp = client.get("/whoami", headers={OBO_HEADER: "dapi1234567890abcdef"})
    assert resp.status_code == 200
    assert resp.json() == {"token_prefix": "dapi1234"}


def test_protected_route_rejects_empty_token(
    app_with_protected_route: FastAPI,
) -> None:
    client = TestClient(app_with_protected_route)
    resp = client.get("/whoami", headers={OBO_HEADER: ""})
    assert resp.status_code == 401
