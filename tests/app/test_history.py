from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from databricks_to_pbi.app.auth import OBO_HEADER
from databricks_to_pbi.app.deps import get_history_store
from databricks_to_pbi.app.main import create_app
from databricks_to_pbi.history.store import RunDetailRow, RunListRow


class _StubStore:
    def list_runs(self, limit: int = 100) -> list[RunListRow]:
        return [
            RunListRow(
                run_id="r-002", created_at=datetime(2026, 5, 26, tzinfo=UTC),
                model_name="Sales", state="published",
                measures_created=0, measures_updated=2, needs_manual_review=0,
                validation_status="passed", val_passed=2, val_failed=0, val_skipped=0,
            ),
            RunListRow(
                run_id="r-001", created_at=datetime(2026, 5, 25, tzinfo=UTC),
                model_name="Sales", state="published",
                measures_created=3, measures_updated=0, needs_manual_review=1,
                validation_status="not_run", val_passed=0, val_failed=0, val_skipped=0,
            ),
        ]

    def get_run(self, run_id: str) -> RunDetailRow | None:
        if run_id != "r-001":
            return None
        return RunDetailRow(
            run_id="r-001", created_at=datetime(2026, 5, 25, tzinfo=UTC),
            run_by="alice@x.com", model_name="Sales", delivery="xmla_create",
            state="published", validation_status="not_run",
            report_json='{"run_id":"r-001","mode":"apply","delivery":"xmla_create",'
            '"summary":{"created":3,"updated":0,"needs_manual_review":1},'
            '"outcomes":[],"target":{"kind":"xmla","target_id":"ws"},'
            '"started_at":"2026-05-25T00:00:00+00:00",'
            '"finished_at":"2026-05-25T00:01:00+00:00","errors":[],'
            '"fatal_error":null,"published_dataset_id":"ds-9",'
            '"source_inventory":[{"kind":"metric_view",'
            '"fully_qualified_name":"main.sales.orders_mv",'
            '"object_hash":"h1","fetched_at":"2026-05-25T00:00:00+00:00"}]}',
            validation_json=None,
            val_dimension="region",
            val_timeframe="quarter",
        )


@pytest.fixture
def history_client() -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_history_store] = lambda: _StubStore()
    with TestClient(app) as c:
        yield c


def test_list_history_newest_first_with_validation(history_client: TestClient) -> None:
    resp = history_client.get("/api/sync/history", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 200
    body = resp.json()
    assert [e["run_id"] for e in body] == ["r-002", "r-001"]
    assert body[0]["validation_status"] == "passed"
    assert body[0]["state"] == "published"


def test_get_run_detail(history_client: TestClient) -> None:
    resp = history_client.get("/api/sync/history/r-001", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "r-001"
    assert body["report"]["summary"]["created"] == 3
    assert body["validation"] is None


def test_get_run_detail_404(history_client: TestClient) -> None:
    resp = history_client.get("/api/sync/history/missing", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 404
    assert resp.json()["code"] == "run_not_found"


def test_report_html_endpoint(history_client: TestClient) -> None:
    resp = history_client.get(
        "/api/sync/history/r-001/report.html", headers={OBO_HEADER: "tok"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "Migration confidence report" in resp.text


def test_history_requires_catalog_header() -> None:
    # get_history_store needs a catalog (history lives in the selected catalog).
    # Override only the workspace-client dep so we exercise the real catalog
    # guard; a warehouse but no X-History-Catalog → 400 missing_catalog.
    from databricks_to_pbi.app.deps import get_workspace_client

    app = create_app()
    app.dependency_overrides[get_workspace_client] = lambda: object()
    with TestClient(app) as c:
        resp = c.get(
            "/api/sync/history",
            headers={OBO_HEADER: "tok", "X-Warehouse-Id": "wh-1"},
        )
    assert resp.status_code == 400
    assert resp.json()["code"] == "missing_catalog"


def test_history_requires_schema_header() -> None:
    # History lives in the source's catalog AND schema, so both headers are
    # required. Catalog present but no X-History-Schema → 400 missing_schema.
    from databricks_to_pbi.app.deps import get_workspace_client

    app = create_app()
    app.dependency_overrides[get_workspace_client] = lambda: object()
    with TestClient(app) as c:
        resp = c.get(
            "/api/sync/history",
            headers={
                OBO_HEADER: "tok",
                "X-Warehouse-Id": "wh-1",
                "X-History-Catalog": "specialists_sessions",
            },
        )
    assert resp.status_code == 400
    assert resp.json()["code"] == "missing_schema"


def test_report_html_404(history_client: TestClient) -> None:
    resp = history_client.get(
        "/api/sync/history/missing/report.html", headers={OBO_HEADER: "tok"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "run_not_found"


def test_get_run_detail_exposes_validation_inputs(history_client: TestClient) -> None:
    resp = history_client.get("/api/sync/history/r-001", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sources"] == [{"kind": "metric_view", "id": "main.sales.orders_mv"}]
    assert body["dataset_id"] == "ds-9"
    assert body["workspace_id"] == "ws"


def test_get_run_detail_exposes_dimension_and_timeframe(history_client: TestClient) -> None:
    resp = history_client.get("/api/sync/history/r-001", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["val_dimension"] == "region"
    assert body["val_timeframe"] == "quarter"
