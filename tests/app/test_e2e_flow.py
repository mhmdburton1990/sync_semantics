from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from databricks_to_pbi.app.auth import OBO_HEADER
from databricks_to_pbi.app.deps import get_history_store, get_uc_volume_root, get_workspace_client
from databricks_to_pbi.app.main import create_app
from databricks_to_pbi.history.store import RunListRow
from databricks_to_pbi.workspace import WorkspaceClient


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent.parent / "fixtures"


class _StubHistoryStore:
    def list_runs(self, limit: int = 100) -> list[RunListRow]:
        return [
            RunListRow(
                run_id="r-e2e", created_at=datetime(2026, 5, 25, tzinfo=UTC),
                model_name="Sales", state="exported",
                measures_created=1, measures_updated=0, needs_manual_review=0,
                validation_status="not_run", val_passed=0, val_failed=0, val_skipped=0,
            ),
        ]


@pytest.fixture
def configured_client(
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, MagicMock]]:
    yaml_body = (fixtures_dir / "metric_views" / "sales_simple.yaml").read_text()
    sdk = MagicMock()

    def fake_execute(statement: str, warehouse_id: str, **_: object) -> MagicMock:
        if "information_schema.tables" in statement:
            return MagicMock(result=MagicMock(data_array=[
                ["main.sales.orders_mv", "alice@example.com", "Sales"],
            ]))
        return MagicMock(result=MagicMock(
            data_array=[["View Definition", yaml_body, ""]],
        ))

    sdk.statement_execution.execute_statement.side_effect = fake_execute

    monkeypatch.setenv("DBX2PBI_FABRIC_WORKSPACES", "ws-a")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    app = create_app()
    app.dependency_overrides[get_workspace_client] = (
        lambda: WorkspaceClient(sdk_client=sdk, warehouse_id="wh-1")
    )
    app.dependency_overrides[get_uc_volume_root] = lambda: tmp_path / "vol"
    app.dependency_overrides[get_history_store] = lambda: _StubHistoryStore()
    with TestClient(app) as c:
        yield c, sdk


def test_full_flow_list_preview_apply(
    configured_client: tuple[TestClient, MagicMock],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = configured_client

    from databricks_to_pbi.app.deps import WAREHOUSE_HEADER

    # 1) List sources (needs warehouse for the information_schema SQL)
    resp = client.get(
        "/api/sources/metric_views",
        headers={OBO_HEADER: "tok", WAREHOUSE_HEADER: "wh-1"},
    )
    assert resp.status_code == 200
    items = resp.json()
    assert items[0]["fully_qualified_name"] == "main.sales.orders_mv"

    # 2) Preview
    resp = client.post(
        "/api/sync/preview",
        headers={OBO_HEADER: "tok"},
        json={
            "sources": [{"kind": "metric_view", "id": "main.sales.orders_mv"}],
            "target": {"kind": "pbip", "target_id": str(tmp_path / "preview_out")},
            "model_name": "Sales",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "preview"

    # 3) Apply (SSE) — server rewrites pbip target_id to _APP_OUTPUT_ROOT/<safe>/.
    from databricks_to_pbi.app.routers import sync as sync_mod
    out_root = tmp_path / "app_out"
    monkeypatch.setattr(sync_mod, "_APP_OUTPUT_ROOT", out_root)

    with client.stream(
        "POST",
        "/api/sync/apply",
        headers={OBO_HEADER: "tok"},
        json={
            "sources": [{"kind": "metric_view", "id": "main.sales.orders_mv"}],
            "target": {"kind": "pbip", "target_id": "ignored"},
            "model_name": "Sales",
        },
    ) as resp:
        assert resp.status_code == 200
        list(resp.iter_lines())

    assert (
        out_root / "Sales" / "Sales.SemanticModel" / "definition" / "tables" / "orders.tmdl"
    ).exists()

    # 4) History.
    resp = client.get("/api/sync/history", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) >= 1
    assert runs[0]["model_name"] == "Sales"
