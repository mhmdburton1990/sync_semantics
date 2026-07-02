from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from databricks_to_pbi.cli import main


def test_sales_simple_full_apply(
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    yaml_body = (fixtures_dir / "metric_views" / "sales_simple.yaml").read_text()
    sdk = MagicMock()

    def _exec(statement: str, **_: object) -> MagicMock:
        # The reader now calls DESCRIBE TABLE on joined sources to discover
        # their columns. Return an empty column list for that path so the
        # test stays focused on the metric-view YAML pipeline.
        if statement.upper().startswith("DESCRIBE EXTENDED"):
            data = [["View Definition", yaml_body, ""]]
        else:
            data = []
        return MagicMock(result=MagicMock(data_array=data))

    sdk.statement_execution.execute_statement.side_effect = _exec
    monkeypatch.setattr(
        "databricks_to_pbi.cli._make_sdk_client",
        lambda: sdk,
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "sync",
            "--metric-view", "main.sales.orders_mv",
            "--warehouse-id", "wh-1",
            "--model-name", "Sales",
            "--target-pbip", str(tmp_path / "out"),
            "--uc-volume", str(tmp_path / "uc_volume"),
            "--apply",
        ],
    )
    assert result.exit_code == 0, result.output

    sem = tmp_path / "out" / "Sales.SemanticModel" / "definition"
    table_file = sem / "tables" / "orders.tmdl"
    assert table_file.exists()
    content = table_file.read_text(encoding="utf-8")
    assert "table orders" in content
    # Measures now live on the synthetic 'Measures' table.
    measures_content = (sem / "tables" / "_Measures.tmdl").read_text(encoding="utf-8")
    assert "measure 'total_sales' = SUM('orders'[amount])" in measures_content
    assert "measure 'order_count' = COUNTROWS('orders')" in measures_content

    manifest_files = list((tmp_path / "uc_volume" / "manifests").glob("*.json"))
    assert manifest_files

    assert list((tmp_path / "uc_volume" / "reports").glob("*.json"))
    assert list((tmp_path / "uc_volume" / "reports").glob("*.md"))
    assert list((tmp_path / "uc_volume" / "reports").glob("*.html"))
