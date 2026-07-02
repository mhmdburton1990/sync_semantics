from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from databricks_to_pbi.cli import main


def test_sales_with_joins(
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    yaml_body = (fixtures_dir / "metric_views" / "sales_with_joins.yaml").read_text()
    sdk = MagicMock()

    def _exec(statement: str, **_: object) -> MagicMock:
        s = statement.upper()
        if s.startswith("DESCRIBE EXTENDED"):
            data = [["View Definition", yaml_body, ""]]
        elif s.startswith("DESCRIBE TABLE") and "CUSTOMERS" in s:
            data = [
                ["id", "bigint", ""],
                ["name", "string", ""],
                ["region", "string", ""],
                ["segment", "string", ""],
            ]
        elif s.startswith("DESCRIBE TABLE") and "ORDERS" in s:
            data = [
                ["order_id", "bigint", ""],
                ["customer_id", "bigint", ""],
                ["amount", "decimal(18,2)", ""],
                ["status", "string", ""],
                ["order_date", "date", ""],
            ]
        else:
            data = []
        return MagicMock(result=MagicMock(data_array=data))

    sdk.statement_execution.execute_statement.side_effect = _exec
    monkeypatch.setattr("databricks_to_pbi.cli._make_sdk_client", lambda: sdk)

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
    assert (sem / "tables" / "orders.tmdl").exists()
    assert (sem / "tables" / "customers.tmdl").exists()

    rels = (sem / "relationships.tmdl").read_text(encoding="utf-8")
    # TMDL relationships use combined `fromColumn: Table.Column` (quoting
    # either part only when the identifier needs it).
    assert "fromColumn: source." in rels or "fromColumn: orders." in rels
    assert "toColumn: customers." in rels

    measures_tmdl = (sem / "tables" / "_Measures.tmdl").read_text(encoding="utf-8")
    assert "DIVIDE(SUM('orders'[amount])" in measures_tmdl
    assert "CALCULATE(SUM('orders'[amount])" in measures_tmdl
    assert "DISTINCTCOUNT('orders'[customer_id])" in measures_tmdl
