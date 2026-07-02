from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from databricks_to_pbi.app.auth import OBO_HEADER
from databricks_to_pbi.app.deps import get_sdk_client
from databricks_to_pbi.app.main import create_app


@pytest.fixture
def client_with_warehouses() -> Iterator[tuple[TestClient, MagicMock]]:
    sdk = MagicMock()
    state_running = MagicMock()
    state_running.value = "RUNNING"
    state_stopped = MagicMock()
    state_stopped.value = "STOPPED"

    w1 = MagicMock()
    w1.id = "wh-001"
    w1.name = "Shared Warehouse"
    w1.state = state_running
    w1.cluster_size = "2X-Small"
    w1.enable_serverless_compute = True

    w2 = MagicMock()
    w2.id = "wh-002"
    w2.name = "Big BI Warehouse"
    w2.state = state_stopped
    w2.cluster_size = "Medium"
    w2.enable_serverless_compute = False

    sdk.warehouses.list.return_value = [w1, w2]

    app = create_app()
    app.dependency_overrides[get_sdk_client] = lambda: sdk
    with TestClient(app) as c:
        yield c, sdk


def test_list_warehouses_returns_id_name_state(
    client_with_warehouses: tuple[TestClient, MagicMock],
) -> None:
    client, _ = client_with_warehouses
    resp = client.get("/api/warehouses", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert {w["id"] for w in body} == {"wh-001", "wh-002"}
    by_id = {w["id"]: w for w in body}
    assert by_id["wh-001"]["name"] == "Shared Warehouse"
    assert by_id["wh-001"]["state"] == "RUNNING"
    assert by_id["wh-001"]["size"] == "2X-Small"
    assert by_id["wh-001"]["serverless"] is True
    assert by_id["wh-002"]["serverless"] is False


def test_list_warehouses_requires_auth(
    client_with_warehouses: tuple[TestClient, MagicMock],
) -> None:
    client, _ = client_with_warehouses
    resp = client.get("/api/warehouses")
    assert resp.status_code == 401
