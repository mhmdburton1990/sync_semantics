"""Tests for POST /api/sync/validate/start and GET /api/sync/validate/jobs/{job_id}."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from databricks_to_pbi.app.auth import OBO_HEADER
from databricks_to_pbi.app.deps import get_uc_volume_root, get_workspace_client
from databricks_to_pbi.app.main import create_app
from databricks_to_pbi.ir import (
    Column,
    DatabricksSemanticIR,
    Dimension,
    Measure,
    SourceRef,
    Table,
)
from databricks_to_pbi.workspace import WorkspaceClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _src() -> SourceRef:
    return SourceRef(
        kind="metric_view",
        fully_qualified_name="main.s.mv",
        object_hash="abc123",
        fetched_at=datetime(2026, 6, 3, tzinfo=UTC),
    )


def _fake_ir() -> DatabricksSemanticIR:
    src = _src()
    table = Table(
        name="orders",
        uc_path="main.s.orders",
        sql_definition=None,
        columns=[Column(name="region", uc_path=None, data_type="STRING")],
        description=None,
        source=src,
    )
    dims = [Dimension(
        name="region", expression="region",
        underlying_columns=["region"], description=None, hierarchy=None,
    )]
    measures = [Measure(
        name="total_sales", sql_expression="SUM(amount)",
        dependencies=[], description=None, format_string=None, source=src,
    )]
    return DatabricksSemanticIR(
        name="sales", description=None,
        tables=[table], dimensions=dims, measures=measures,
        relationships=[], sources=[src],
    )


class _FakeDax:
    def scalar(self, measure: str) -> float | None:
        return 100.0

    def by_dim(
        self, measure: str, dax_table: str, dax_column: str,
    ) -> dict[str | None, float | None]:
        return {"EU": 60.0, "US": 40.0}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def _make_sdk_for_validate() -> MagicMock:
    """SDK mock that returns sensible rows for the validation SQL queries."""
    sdk = MagicMock()

    def _execute(statement: str, **_kwargs: object) -> MagicMock:
        if "approx_count_distinct" in statement:
            data: list[list[object]] = [[3]]
        elif "GROUP BY" in statement:
            data = [["EU", 60.0], ["US", 40.0]]
        else:
            data = [[100.0]]
        return MagicMock(result=MagicMock(data_array=data))

    sdk.statement_execution.execute_statement.side_effect = _execute
    return sdk


@pytest.fixture
def validate_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, Any]]:
    """TestClient with all external deps monkeypatched. Yields (client, None)."""
    import databricks_to_pbi.app.routers.sync as sync_mod

    fake_ir = _fake_ir()

    # Patch _build_partial_irs so we never need a real SDK for reading.
    monkeypatch.setattr(
        sync_mod, "_build_partial_irs",
        lambda sources, wc: [fake_ir],
    )
    # Patch merge_irs to return the same fake IR unchanged.
    monkeypatch.setattr(
        sync_mod, "merge_irs",
        lambda partial_irs, *, target_name, description: fake_ir,
    )
    # Patch translate_for_validation to return a simple method map.
    monkeypatch.setattr(
        sync_mod, "translate_for_validation",
        lambda ir, cache, claude: {"total_sales": "SUM([amount])"},
    )
    # Patch default_dax_factory so no Fabric credentials are needed.
    monkeypatch.setattr(
        sync_mod, "default_dax_factory",
        lambda *, workspace_id, dataset_id: lambda _measure: _FakeDax(),
    )

    # SDK mock that returns correct rows for validation SQL (oracle + dim probe).
    sdk = _make_sdk_for_validate()
    app = create_app()
    app.dependency_overrides[get_workspace_client] = (
        lambda: WorkspaceClient(sdk_client=sdk, warehouse_id="wh-1")
    )
    app.dependency_overrides[get_uc_volume_root] = lambda: tmp_path / "vol"

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Provide dummy Fabric SP credentials so the eager credential check passes.
    monkeypatch.setenv("FABRIC_SP_CLIENT_ID", "dummy-client-id")
    monkeypatch.setenv("FABRIC_SP_CLIENT_SECRET", "dummy-client-secret")
    monkeypatch.setenv("FABRIC_TENANT_ID", "dummy-tenant-id")

    with TestClient(app) as client:
        yield client, None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_start_then_poll_returns_done(
    validate_client: tuple[TestClient, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _fakes = validate_client
    import databricks_to_pbi.validation.jobs as jobs_mod
    from databricks_to_pbi.validation.runner import ValidationContext

    # Run the job synchronously instead of in a thread (monkeypatch auto-undoes it).
    def sync_start(
        self: jobs_mod.JobRegistry,
        ctx: ValidationContext,
        *,
        per_measure_timeout_s: float = 90.0,
    ) -> str:
        job_id = self.register(ctx)
        jobs_mod.run_job(self, job_id, ctx, per_measure_timeout_s)
        return job_id

    monkeypatch.setattr(jobs_mod.JobRegistry, "start", sync_start)

    resp = client.post("/api/sync/validate/start", json={
        "sources": [{"kind": "metric_view", "id": "main.s.mv"}],
        "model_name": "sales", "dataset_id": "ds", "workspace_id": "ws",
    }, headers={"X-Forwarded-Access-Token": "tok", "X-Warehouse-Id": "w1"})
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]
    assert resp.json()["total"] >= 1

    poll = client.get(f"/api/sync/validate/jobs/{job_id}",
                      headers={"X-Forwarded-Access-Token": "tok", "X-Warehouse-Id": "w1"})
    assert poll.status_code == 200, poll.text
    body = poll.json()
    assert body["status"] == "done"
    assert "results" in body and "summary" in body


def test_poll_unknown_job_404(
    validate_client: tuple[TestClient, Any],
) -> None:
    client, _fakes = validate_client
    resp = client.get("/api/sync/validate/jobs/does-not-exist",
                      headers={"X-Forwarded-Access-Token": "tok", "X-Warehouse-Id": "w1"})
    assert resp.status_code == 404


def test_start_unknown_dim_returns_422(
    validate_client: tuple[TestClient, Any],
) -> None:
    client, _fakes = validate_client
    resp = client.post("/api/sync/validate/start", json={
        "sources": [{"kind": "metric_view", "id": "main.s.mv"}],
        "model_name": "sales", "dataset_id": "ds", "workspace_id": "ws",
        "dim_sql_ref": "does_not_exist",
    }, headers={"X-Forwarded-Access-Token": "tok", "X-Warehouse-Id": "w1"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "unknown_dim_sql_ref"


def test_start_requires_obo_token(
    validate_client: tuple[TestClient, Any],
) -> None:
    client, _fakes = validate_client
    resp = client.post(
        "/api/sync/validate/start",
        json={
            "sources": [{"kind": "metric_view", "id": "main.s.mv"}],
            "model_name": "sales",
            "dataset_id": "ds",
            "workspace_id": "ws",
        },
    )
    assert resp.status_code == 401


def test_start_requires_at_least_one_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty sources list should return 400 via _build_partial_irs."""
    # Use the REAL _build_partial_irs (not patched) but fake deps.
    sdk = MagicMock()
    app = create_app()
    app.dependency_overrides[get_workspace_client] = (
        lambda: WorkspaceClient(sdk_client=sdk, warehouse_id="wh-1")
    )
    app.dependency_overrides[get_uc_volume_root] = lambda: tmp_path / "vol"

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with TestClient(app) as client:
        resp = client.post(
            "/api/sync/validate/start",
            headers={OBO_HEADER: "tok"},
            json={
                "sources": [],
                "model_name": "sales",
                "dataset_id": "ds",
                "workspace_id": "ws",
            },
        )
    assert resp.status_code == 400
    assert resp.json()["code"] == "no_sources"


def test_list_dimensions(validate_client: tuple[TestClient, Any]) -> None:
    client, _fakes = validate_client
    resp = client.post("/api/sync/validate/dimensions", json={
        "sources": [{"kind": "metric_view", "id": "main.s.mv"}], "model_name": "sales",
    }, headers={"X-Forwarded-Access-Token": "tok", "X-Warehouse-Id": "w1"})
    assert resp.status_code == 200
    body = resp.json()
    assert "dimensions" in body and isinstance(body["dimensions"], list)
    assert "has_date_column" in body


def test_dimensions_response_includes_date_columns(
    validate_client: tuple[TestClient, Any],
) -> None:
    client, _fakes = validate_client
    resp = client.post("/api/sync/validate/dimensions", json={
        "sources": [{"kind": "metric_view", "id": "main.s.mv"}], "model_name": "sales",
    }, headers={"X-Forwarded-Access-Token": "tok", "X-Warehouse-Id": "w1"})
    assert resp.status_code == 200
    body = resp.json()
    assert "date_columns" in body and isinstance(body["date_columns"], list)
    assert all({"table", "column"} <= set(dc) for dc in body["date_columns"])
    assert body["has_date_column"] == bool(body["date_columns"])


def test_validate_start_excludes_measures(
    validate_client: tuple[TestClient, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = validate_client
    import databricks_to_pbi.validation.jobs as jobs_mod
    from databricks_to_pbi.validation.runner import ValidationContext

    def sync_start(self: jobs_mod.JobRegistry, ctx: ValidationContext, *,
                   per_measure_timeout_s: float = 90.0) -> str:
        return self.register(ctx)  # register only
    monkeypatch.setattr(jobs_mod.JobRegistry, "start", sync_start)

    resp = client.post("/api/sync/validate/start", json={
        "sources": [{"kind": "metric_view", "id": "main.s.mv"}],
        "model_name": "sales", "dataset_id": "ds", "workspace_id": "ws",
        "exclude_measures": ["total_sales"],
    }, headers={"X-Forwarded-Access-Token": "tok", "X-Warehouse-Id": "w1"})
    assert resp.status_code == 200, resp.text
    # The fake IR has exactly one measure (total_sales); excluding it → total 0.
    assert resp.json()["total"] == 0


def test_start_unknown_date_column_returns_422(
    validate_client: tuple[TestClient, Any],
) -> None:
    client, _fakes = validate_client
    resp = client.post("/api/sync/validate/start", json={
        "sources": [{"kind": "metric_view", "id": "main.s.mv"}],
        "model_name": "sales", "dataset_id": "ds", "workspace_id": "ws",
        "date_table": "nope", "date_column": "missing",
    }, headers={"X-Forwarded-Access-Token": "tok", "X-Warehouse-Id": "w1"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "unknown_date_column"


def test_cancel_running_job(
    validate_client: tuple[TestClient, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _fakes = validate_client
    import databricks_to_pbi.validation.jobs as jobs_mod
    from databricks_to_pbi.validation.runner import ValidationContext

    # Register a job WITHOUT running it, so it stays cancelable.
    def fake_start(
        self: jobs_mod.JobRegistry,
        ctx: ValidationContext,
        *,
        per_measure_timeout_s: float = 90.0,
    ) -> str:
        return self.register(ctx)  # register only; don't run

    monkeypatch.setattr(jobs_mod.JobRegistry, "start", fake_start)

    start = client.post("/api/sync/validate/start", json={
        "sources": [{"kind": "metric_view", "id": "main.s.mv"}],
        "model_name": "sales", "dataset_id": "ds", "workspace_id": "ws",
    }, headers={"X-Forwarded-Access-Token": "tok", "X-Warehouse-Id": "w1"})
    job_id = start.json()["job_id"]

    cancel = client.post(
        f"/api/sync/validate/jobs/{job_id}/cancel",
        headers={"X-Forwarded-Access-Token": "tok", "X-Warehouse-Id": "w1"},
    )
    assert cancel.status_code == 200


def test_cancel_unknown_job_404(validate_client: tuple[TestClient, Any]) -> None:
    client, _fakes = validate_client
    resp = client.post(
        "/api/sync/validate/jobs/nope/cancel",
        headers={"X-Forwarded-Access-Token": "tok", "X-Warehouse-Id": "w1"},
    )
    assert resp.status_code == 404


def test_start_missing_fabric_credentials_returns_422(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing FABRIC_SP_* env vars must return 422 with code='no_fabric_credentials'."""
    import databricks_to_pbi.app.routers.sync as sync_mod

    # Remove Fabric SP env vars so load_credentials_from_env() returns None.
    monkeypatch.delenv("FABRIC_SP_CLIENT_ID", raising=False)
    monkeypatch.delenv("FABRIC_SP_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("FABRIC_TENANT_ID", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    fake_ir = _fake_ir()

    # Patch the upstream pipeline steps so the route reaches the credential check.
    monkeypatch.setattr(sync_mod, "_build_partial_irs", lambda sources, wc: [fake_ir])
    monkeypatch.setattr(
        sync_mod, "merge_irs",
        lambda partial_irs, *, target_name, description: fake_ir,
    )
    monkeypatch.setattr(
        sync_mod, "translate_for_validation",
        lambda ir, cache, claude: {"total_sales": "SUM([amount])"},
    )

    sdk = MagicMock()
    app = create_app()
    app.dependency_overrides[get_workspace_client] = (
        lambda: WorkspaceClient(sdk_client=sdk, warehouse_id="wh-1")
    )
    app.dependency_overrides[get_uc_volume_root] = lambda: tmp_path / "vol"

    with TestClient(app) as client:
        resp = client.post(
            "/api/sync/validate/start",
            headers={OBO_HEADER: "tok", "X-Warehouse-Id": "w1"},
            json={
                "sources": [{"kind": "metric_view", "id": "main.s.mv"}],
                "model_name": "sales",
                "dataset_id": "ds",
                "workspace_id": "ws",
            },
        )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "no_fabric_credentials"
