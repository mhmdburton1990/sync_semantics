from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from databricks_to_pbi.readers.dashboard import (
    parse_dashboard_json,
    read_dashboard,
)


@pytest.fixture
def dashboard_json(fixtures_dir: Path) -> str:
    return (fixtures_dir / "lakeview_dashboards" / "sales_dashboard.json").read_text(
        encoding="utf-8"
    )


def test_parse_dashboard_json_extracts_datasets_and_calculations(dashboard_json: str) -> None:
    parsed = parse_dashboard_json(dashboard_json)
    assert parsed["id"] == "dash-abc-123"
    assert {d["name"] for d in parsed["datasets"]} == {"Orders by Month", "Customer Spend"}
    calc_names = {c["name"] for w in parsed["widgets"] for c in w.get("calculations", [])}
    assert calc_names == {"avg_order_value"}


def test_read_dashboard_returns_partial_ir(dashboard_json: str) -> None:
    sdk = MagicMock()
    sdk.lakeview = MagicMock()
    sdk.lakeview.get.return_value = MagicMock(
        as_dict=MagicMock(return_value={"serialized_dashboard": dashboard_json})
    )

    from databricks_to_pbi.workspace import WorkspaceClient
    wc = WorkspaceClient(sdk_client=sdk, warehouse_id="wh-1")

    ir = read_dashboard(wc, dashboard_id="dash-abc-123")

    table_names = {t.name for t in ir.tables}
    assert table_names == {"Orders by Month", "Customer Spend"}

    for t in ir.tables:
        assert t.uc_path is None
        assert t.sql_definition
        assert t.storage_mode == "direct_query"

    assert {m.name for m in ir.measures} == {"avg_order_value"}
    assert all(m.source.kind == "dashboard" for m in ir.measures)
    measure_src = next(m.source for m in ir.measures if m.name == "avg_order_value")
    assert "dash-abc-123" in measure_src.fully_qualified_name
    assert "w-aov" in measure_src.fully_qualified_name


def test_dashboard_tables_have_inferred_columns(dashboard_json: str) -> None:
    sdk = MagicMock()
    sdk.lakeview = MagicMock()
    sdk.lakeview.get.return_value = MagicMock(
        as_dict=MagicMock(return_value={"serialized_dashboard": dashboard_json})
    )
    from databricks_to_pbi.workspace import WorkspaceClient
    wc = WorkspaceClient(sdk_client=sdk, warehouse_id="wh-1")

    ir = read_dashboard(wc, dashboard_id="dash-abc-123")

    orders_table = next(t for t in ir.tables if t.name == "Orders by Month")
    column_names = {c.name for c in orders_table.columns}
    # SQL: SELECT DATE_TRUNC('MONTH', order_date) AS order_month, SUM(amount) AS total_sales ...
    # Identifiers in SQL: order_date, amount (we drop keywords/aliases)
    assert "order_date" in column_names
    assert "amount" in column_names
