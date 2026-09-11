"""Tests for /api/fabric/workspaces."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import ClientAuthenticationError
from fastapi.testclient import TestClient

from databricks_to_pbi.app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _hdrs() -> dict[str, str]:
    return {"X-Forwarded-Access-Token": "obo-token-xyz"}


def test_workspaces_returns_empty_when_sp_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No FABRIC_SP_* env vars → 400 with the configuration error envelope."""
    for k in ("FABRIC_SP_CLIENT_ID", "FABRIC_SP_CLIENT_SECRET", "FABRIC_TENANT_ID"):
        monkeypatch.delenv(k, raising=False)
    resp = client.get("/api/fabric/workspaces", headers=_hdrs())
    assert resp.status_code == 400
    assert resp.json()["code"] == "fabric_sp_not_configured"


def test_workspaces_returns_groups_from_pbi_api(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fabric SP configured + PBI returns groups → 200 with the workspace list."""
    monkeypatch.setenv("FABRIC_SP_CLIENT_ID", "cid")
    monkeypatch.setenv("FABRIC_SP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("FABRIC_TENANT_ID", "tid")

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.ok = True
    fake_resp.json.return_value = {
        "value": [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "name": "Sales Workspace",
                "isOnDedicatedCapacity": True,
                "capacityId": "cap-1",
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "name": "Marketing Workspace",
                "isOnDedicatedCapacity": False,
            },
        ],
    }
    with patch(
        "databricks_to_pbi.app.routers.fabric.requests.get",
        return_value=fake_resp,
    ) as req_get, patch(
        "databricks_to_pbi.app.routers.fabric.FabricAuth.bearer_token",
        return_value="bearer-xyz",
    ):
        resp = client.get("/api/fabric/workspaces", headers=_hdrs())

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["id"] == "11111111-1111-1111-1111-111111111111"
    assert body[0]["name"] == "Sales Workspace"
    assert body[0]["is_dedicated_capacity"] is True
    assert body[0]["capacity_id"] == "cap-1"
    assert body[1]["is_dedicated_capacity"] is False
    # And the PBI API was called with the right scope.
    req_get.assert_called_once()
    args, kwargs = req_get.call_args
    assert args[0] == "https://api.powerbi.com/v1.0/myorg/groups"
    assert kwargs["headers"]["Authorization"] == "Bearer bearer-xyz"


def test_workspaces_401_from_pbi_surfaces_unauthorized(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FABRIC_SP_CLIENT_ID", "cid")
    monkeypatch.setenv("FABRIC_SP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("FABRIC_TENANT_ID", "tid")

    fake_resp = MagicMock()
    fake_resp.status_code = 401
    fake_resp.ok = False
    with patch(
        "databricks_to_pbi.app.routers.fabric.requests.get",
        return_value=fake_resp,
    ), patch(
        "databricks_to_pbi.app.routers.fabric.FabricAuth.bearer_token",
        return_value="bearer-xyz",
    ):
        resp = client.get("/api/fabric/workspaces", headers=_hdrs())

    assert resp.status_code == 502
    assert resp.json()["code"] == "fabric_sp_unauthorized"


def test_workspaces_403_from_pbi_surfaces_forbidden(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FABRIC_SP_CLIENT_ID", "cid")
    monkeypatch.setenv("FABRIC_SP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("FABRIC_TENANT_ID", "tid")

    fake_resp = MagicMock()
    fake_resp.status_code = 403
    fake_resp.ok = False
    with patch(
        "databricks_to_pbi.app.routers.fabric.requests.get",
        return_value=fake_resp,
    ), patch(
        "databricks_to_pbi.app.routers.fabric.FabricAuth.bearer_token",
        return_value="bearer-xyz",
    ):
        resp = client.get("/api/fabric/workspaces", headers=_hdrs())

    assert resp.status_code == 502
    assert resp.json()["code"] == "fabric_sp_forbidden"


def test_workspaces_expired_secret_surfaces_unauthorized_with_detail(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Azure token acquisition failing (e.g. expired secret) → 502 with the
    unauthorized envelope and the underlying AADSTS detail surfaced, not a
    bare 500."""
    monkeypatch.setenv("FABRIC_SP_CLIENT_ID", "cid")
    monkeypatch.setenv("FABRIC_SP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("FABRIC_TENANT_ID", "tid")

    aadsts = (
        "Authentication failed: AADSTS7000222: The provided client secret "
        "keys for app 'xxx' are expired. Visit the Azure portal to create "
        "new keys for your app."
    )
    with patch(
        "databricks_to_pbi.app.routers.fabric.FabricAuth.bearer_token",
        side_effect=ClientAuthenticationError(message=aadsts),
    ):
        resp = client.get("/api/fabric/workspaces", headers=_hdrs())

    assert resp.status_code == 502
    body = resp.json()
    assert body["code"] == "fabric_sp_unauthorized"
    # The real Azure cause must reach the client so the UI can show it.
    assert "AADSTS7000222" in (body["suggestion"] or "")
