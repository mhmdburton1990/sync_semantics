from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from databricks_to_pbi.app.auth import OBO_HEADER
from databricks_to_pbi.app.deps import get_workspace_client
from databricks_to_pbi.app.main import create_app
from databricks_to_pbi.workspace import WorkspaceClient


@pytest.fixture
def client_with_fake_sdk() -> Iterator[tuple[TestClient, MagicMock]]:
    sdk = MagicMock()
    # metric_views list now uses SQL via information_schema.tables
    sdk.statement_execution = MagicMock()
    sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(
            data_array=[
                ["main.sales.orders_mv", "alice@example.com", "Sales metric view"],
            ],
        ),
    )
    sdk.lakeview = MagicMock()
    sdk.lakeview.list.return_value = [
        MagicMock(
            dashboard_id="dash-1",
            display_name="Sales Dashboard",
            owner="alice@example.com",
            update_time="2026-05-20T12:00:00Z",
        ),
    ]
    sdk.genie = MagicMock()
    sdk.genie.list_spaces.return_value = MagicMock(
        spaces=[
            MagicMock(
                space_id="space-1",
                title="Sales Genie Space",
                owner_user_name="alice@example.com",
                update_time="2026-05-21T08:00:00Z",
            ),
        ],
    )

    app = create_app()

    def fake_wc() -> WorkspaceClient:
        return WorkspaceClient(sdk_client=sdk, warehouse_id="wh-1")

    app.dependency_overrides[get_workspace_client] = fake_wc

    with TestClient(app) as c:
        yield c, sdk


def test_list_metric_views_returns_information_schema_rows(
    client_with_fake_sdk: tuple[TestClient, MagicMock],
) -> None:
    from databricks_to_pbi.app.deps import WAREHOUSE_HEADER

    client, _ = client_with_fake_sdk
    resp = client.get(
        "/api/sources/metric_views",
        headers={OBO_HEADER: "tok", WAREHOUSE_HEADER: "wh-1"},
    )
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["fully_qualified_name"] == "main.sales.orders_mv"
    assert items[0]["description"] == "Sales metric view"


def test_list_metric_views_without_warehouse_returns_400(
    client_with_fake_sdk: tuple[TestClient, MagicMock],
) -> None:
    client, _ = client_with_fake_sdk
    resp = client.get("/api/sources/metric_views", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "missing_warehouse"


def test_list_dashboards(
    client_with_fake_sdk: tuple[TestClient, MagicMock],
) -> None:
    client, _ = client_with_fake_sdk
    resp = client.get("/api/sources/dashboards", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 200
    items = resp.json()
    assert items == [
        {
            "id": "dash-1",
            "name": "Sales Dashboard",
            "owner": "alice@example.com",
            "updated_at": "2026-05-20T12:00:00Z",
        },
    ]


def test_list_genie_spaces(
    client_with_fake_sdk: tuple[TestClient, MagicMock],
) -> None:
    client, _ = client_with_fake_sdk
    resp = client.get("/api/sources/genie_spaces", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 200
    items = resp.json()
    assert items == [
        {
            "id": "space-1",
            "name": "Sales Genie Space",
            "owner": "alice@example.com",
            "updated_at": "2026-05-21T08:00:00Z",
        },
    ]


def test_unauthenticated_request_returns_401(
    client_with_fake_sdk: tuple[TestClient, MagicMock],
) -> None:
    client, _ = client_with_fake_sdk
    resp = client.get("/api/sources/metric_views")
    assert resp.status_code == 401


def test_source_preview_metric_view_returns_partial_ir(
    client_with_fake_sdk: tuple[TestClient, MagicMock],
    fixtures_dir: Path,
) -> None:
    client, sdk = client_with_fake_sdk
    yaml_body = (
        fixtures_dir / "metric_views" / "sales_simple.yaml"
    ).read_text(encoding="utf-8")
    sdk.statement_execution = MagicMock()
    sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(data_array=[["View Definition", yaml_body, ""]]),
    )

    resp = client.get(
        "/api/sources/metric_view/main.sales.orders_mv/preview",
        headers={OBO_HEADER: "tok"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"]
    assert "measures" in body
    assert "tables" in body


def test_source_preview_unknown_kind_returns_validation_error(
    client_with_fake_sdk: tuple[TestClient, MagicMock],
) -> None:
    client, _ = client_with_fake_sdk
    resp = client.get(
        "/api/sources/widget/foo/preview",
        headers={OBO_HEADER: "tok"},
    )
    assert resp.status_code == 422
