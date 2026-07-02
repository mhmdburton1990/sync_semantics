from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from databricks_to_pbi.app.auth import OBO_HEADER
from databricks_to_pbi.app.deps import get_uc_volume_root, get_workspace_client
from databricks_to_pbi.app.main import create_app
from databricks_to_pbi.workspace import WorkspaceClient


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def sync_client(
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, MagicMock]]:
    yaml_body = (fixtures_dir / "metric_views" / "sales_simple.yaml").read_text()
    sdk = MagicMock()
    sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(data_array=[["View Definition", yaml_body, ""]]),
    )

    app = create_app()
    app.dependency_overrides[get_workspace_client] = (
        lambda: WorkspaceClient(sdk_client=sdk, warehouse_id="wh-1")
    )
    app.dependency_overrides[get_uc_volume_root] = lambda: tmp_path / "vol"

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(app) as c:
        yield c, sdk


def test_sync_preview_returns_report(
    sync_client: tuple[TestClient, MagicMock], tmp_path: Path,
) -> None:
    client, _ = sync_client
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
    body = resp.json()
    assert body["mode"] == "preview"
    assert "summary" in body
    assert "outcomes" in body


def test_sync_preview_requires_at_least_one_source(
    sync_client: tuple[TestClient, MagicMock],
) -> None:
    client, _ = sync_client
    resp = client.post(
        "/api/sync/preview",
        headers={OBO_HEADER: "tok"},
        json={
            "sources": [],
            "target": {"kind": "pbip", "target_id": "/tmp/x"},
            "model_name": "Sales",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "no_sources"


def test_sync_apply_streams_events(
    sync_client: tuple[TestClient, MagicMock], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The App rewrites PBIP target_id into _APP_OUTPUT_ROOT/<safe_name>/ so the
    # SP (which can't write to /Workspace or /Volumes) has a place to land. Point
    # that root at tmp_path so the test is hermetic.
    from databricks_to_pbi.app.routers import sync as sync_mod
    out_root = tmp_path / "app_out"
    monkeypatch.setattr(sync_mod, "_APP_OUTPUT_ROOT", out_root)

    client, _ = sync_client
    with client.stream(
        "POST",
        "/api/sync/apply",
        headers={OBO_HEADER: "tok"},
        json={
            "sources": [{"kind": "metric_view", "id": "main.sales.orders_mv"}],
            "target": {"kind": "pbip", "target_id": "ignored-by-server"},
            "model_name": "Sales",
        },
    ) as resp:
        assert resp.status_code == 200
        events: list[str] = []
        for line in resp.iter_lines():
            if line:
                events.append(line)

    joined = "\n".join(events)
    assert "event: start" in joined
    assert "event: done" in joined
    assert (
        out_root / "Sales" / "Sales.SemanticModel" / "definition" / "tables" / "orders.tmdl"
    ).exists()


def test_download_returns_zip_of_pbip_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After apply, GET /api/sync/download?model=<name> returns the output as a ZIP."""
    import zipfile

    from databricks_to_pbi.app.routers import sync as sync_mod
    out_root = tmp_path / "app_out"
    monkeypatch.setattr(sync_mod, "_APP_OUTPUT_ROOT", out_root)

    # Seed a fake PBIP output
    pbip_dir = out_root / "MyModel"
    (pbip_dir / "MyModel.SemanticModel" / "definition" / "tables").mkdir(parents=True)
    (pbip_dir / "MyModel.SemanticModel" / "definition" / "tables" / "x.tmdl").write_text("hi")

    app = create_app()
    with TestClient(app) as client:
        resp = client.get(
            "/api/sync/download",
            params={"model": "MyModel"},
            headers={OBO_HEADER: "tok"},
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(__import__("io").BytesIO(resp.content))
    assert "MyModel.SemanticModel/definition/tables/x.tmdl" in z.namelist()


def test_apply_records_history_row(
    sync_client: tuple[TestClient, MagicMock], tmp_path: Path,
) -> None:
    client, sdk = sync_client

    resp = client.post(
        "/api/sync/apply",
        headers={OBO_HEADER: "tok"},
        json={
            "sources": [{"kind": "metric_view", "id": "main.sales.orders_mv"}],
            "target": {"kind": "pbip", "target_id": str(tmp_path / "apply_out")},
            "model_name": "Sales",
        },
    )
    assert resp.status_code == 200
    assert "done" in resp.text  # consume the SSE stream so the generator runs
    stmts = [
        c.kwargs.get("statement", "")
        for c in sdk.statement_execution.execute_statement.call_args_list
    ]
    assert any("INSERT INTO" in s for s in stmts)
    assert any("CREATE TABLE IF NOT EXISTS" in s for s in stmts)
    # Table lives in the source's own catalog AND schema — not a hardcoded
    # location. Source id "main.sales.orders_mv" → main.sales.run_history.
    assert any("main.sales.run_history" in s for s in stmts)


def test_apply_history_failure_does_not_block_done(
    sync_client: tuple[TestClient, MagicMock],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(self: object, report: object, *, run_by: object) -> None:
        raise RuntimeError("history table unavailable")

    monkeypatch.setattr(
        "databricks_to_pbi.history.store.RunHistoryStore.record_apply", _boom
    )

    client, _ = sync_client
    resp = client.post(
        "/api/sync/apply",
        headers={OBO_HEADER: "tok"},
        json={
            "sources": [{"kind": "metric_view", "id": "main.sales.orders_mv"}],
            "target": {"kind": "pbip", "target_id": str(tmp_path / "apply_out2")},
            "model_name": "Sales",
        },
    )
    assert resp.status_code == 200
    assert "done" in resp.text
    assert "history_warning" in resp.text
