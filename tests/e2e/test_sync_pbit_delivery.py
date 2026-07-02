from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from databricks_to_pbi.cli import main


def test_pbit_delivery_produces_valid_zip(
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mv_body = (fixtures_dir / "metric_views" / "sales_simple.yaml").read_text()
    sdk = MagicMock()
    sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(data_array=[["View Definition", mv_body, ""]]),
    )
    monkeypatch.setattr("databricks_to_pbi.cli._make_sdk_client", lambda: sdk)

    runner = CliRunner()
    out = tmp_path / "Sales.pbit"
    result = runner.invoke(
        main,
        [
            "sync",
            "--metric-view", "main.sales.orders_mv",
            "--warehouse-id", "wh-1",
            "--model-name", "Sales",
            "--target-pbit", str(out),
            "--uc-volume", str(tmp_path / "uc_volume"),
            "--apply",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()

    with zipfile.ZipFile(out) as zf, zf.open("DataModel") as f:
        data = json.loads(f.read().decode("utf-8"))
    assert data["name"] == "Sales"
    assert any(t["name"] == "orders" for t in data["model"]["tables"])
