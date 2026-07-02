from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from databricks_to_pbi.readers.metric_view import (
    parse_metric_view_yaml,
    read_metric_view,
)


@pytest.fixture
def simple_yaml(fixtures_dir: Path) -> str:
    return (fixtures_dir / "metric_views" / "sales_simple.yaml").read_text(encoding="utf-8")


@pytest.fixture
def joins_yaml(fixtures_dir: Path) -> str:
    return (fixtures_dir / "metric_views" / "sales_with_joins.yaml").read_text(encoding="utf-8")


def test_parse_metric_view_yaml_extracts_source_and_measures(simple_yaml: str) -> None:
    parsed = parse_metric_view_yaml(simple_yaml)
    assert parsed["source"] == "main.sales.orders"
    assert {m["name"] for m in parsed["measures"]} == {"total_sales", "order_count"}


def test_parse_metric_view_yaml_extracts_joins(joins_yaml: str) -> None:
    parsed = parse_metric_view_yaml(joins_yaml)
    assert len(parsed["joins"]) == 1
    assert parsed["joins"][0]["name"] == "customers"


def test_read_metric_view_returns_partial_ir(simple_yaml: str) -> None:
    sdk = MagicMock()
    sdk.statement_execution.execute_statement.side_effect = [
        MagicMock(result=MagicMock(data_array=[
            ["# col_name", "data_type", "comment"],
            ["", "", ""],
            ["# Detailed Table Information", "", ""],
            ["View Definition", simple_yaml, ""],
        ])),
    ]
    from databricks_to_pbi.workspace import WorkspaceClient
    wc = WorkspaceClient(sdk_client=sdk, warehouse_id="wh-1")

    ir_partial = read_metric_view(wc, fully_qualified_name="main.sales.orders_mv")

    assert ir_partial.tables[0].uc_path == "main.sales.orders"
    assert {m.name for m in ir_partial.measures} == {"total_sales", "order_count"}
    assert all(m.source.kind == "metric_view" for m in ir_partial.measures)


def test_build_measures_captures_window() -> None:
    from datetime import UTC, datetime

    from databricks_to_pbi.ir import SourceRef
    from databricks_to_pbi.readers.metric_view import _build_measures

    src = SourceRef(kind="metric_view", fully_qualified_name="c.s.mv",
                    object_hash="h", fetched_at=datetime(2026, 6, 16, tzinfo=UTC))
    parsed = {"measures": [
        {"name": "total_sales", "expr": "SUM(l_extendedprice)"},
        {"name": "sales_last_7d", "expr": "MEASURE(total_sales)",
         "window": [{"order": "order_date", "semiadditive": "last",
                     "range": "trailing 7 day inclusive"}]},
    ]}
    ms = {m.name: m for m in _build_measures(parsed, src)}
    assert ms["total_sales"].window is None
    assert ms["sales_last_7d"].window is not None
    assert ms["sales_last_7d"].window[0].order == "order_date"
    assert ms["sales_last_7d"].window[0].range == "trailing 7 day inclusive"


def test_build_relationships_resolves_source_keyword_and_join_alias() -> None:
    # Regression: a join `on: source.X = <source_basename>.Y` must resolve to the
    # HOST table (not literal "source") and the join ALIAS (not the source table
    # basename), or Fabric publish fails with Workload_FailedToParseFile.
    from databricks_to_pbi.readers.metric_view import _build_relationships

    parsed = {
        "source": "specialists_sessions.dss_tpch.lineitem",
        "joins": [
            {
                "name": "calendar",
                "source": "specialists_sessions.dss_tpch.dim_calendar",
                "on": "source.l_receiptdate = dim_calendar.date",
                "rely": {"at_most_one_match": True},
            },
        ],
    }
    rels = _build_relationships(parsed)
    assert len(rels) == 1
    r = rels[0]
    assert r.from_table == "lineitem"      # `source.` → host table
    assert r.from_columns == ["l_receiptdate"]
    assert r.to_table == "calendar"        # join alias, not basename "dim_calendar"
    assert r.to_columns == ["date"]
