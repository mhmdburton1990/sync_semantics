from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from databricks_to_pbi.cli import main


def test_combined_three_sources_merged_into_one_model(
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mv_body = (fixtures_dir / "metric_views" / "sales_simple.yaml").read_text()
    dash_body = (fixtures_dir / "lakeview_dashboards" / "sales_dashboard.json").read_text()
    genie_body = (fixtures_dir / "genie_spaces" / "sales_space.json").read_text()

    sdk = MagicMock()
    sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(data_array=[["View Definition", mv_body, ""]]),
    )
    sdk.lakeview = MagicMock()
    sdk.lakeview.get.return_value = MagicMock(
        as_dict=MagicMock(return_value={"serialized_dashboard": dash_body}),
    )
    sdk.genie = MagicMock()
    sdk.genie.get_space.return_value = MagicMock(
        as_dict=MagicMock(return_value={"serialized_space": genie_body}),
    )
    monkeypatch.setattr("databricks_to_pbi.cli._make_sdk_client", lambda: sdk)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "sync",
            "--metric-view", "main.sales.orders_mv",
            "--dashboard", "dash-abc-123",
            "--genie-space", "space-xyz-789",
            "--warehouse-id", "wh-1",
            "--model-name", "FullSales",
            "--target-pbip", str(tmp_path / "out"),
            "--uc-volume", str(tmp_path / "uc_volume"),
            "--apply",
        ],
    )
    assert result.exit_code == 0, result.output

    sem = tmp_path / "out" / "FullSales.SemanticModel" / "definition" / "tables"
    table_names = {p.stem for p in sem.iterdir()}
    assert "orders" in table_names
    assert {"Orders by Month", "Customer Spend"}.issubset(table_names)
    assert "customers" in table_names
