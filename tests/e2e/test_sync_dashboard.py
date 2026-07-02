from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from databricks_to_pbi.cli import main


def test_dashboard_only_sync_emits_pbip_with_dataset_tables(
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dash_body = (fixtures_dir / "lakeview_dashboards" / "sales_dashboard.json").read_text()
    sdk = MagicMock()
    sdk.lakeview = MagicMock()
    sdk.lakeview.get.return_value = MagicMock(
        as_dict=MagicMock(return_value={"serialized_dashboard": dash_body}),
    )
    monkeypatch.setattr("databricks_to_pbi.cli._make_sdk_client", lambda: sdk)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "sync",
            "--dashboard", "dash-abc-123",
            "--warehouse-id", "wh-1",
            "--model-name", "SalesDashModel",
            "--target-pbip", str(tmp_path / "out"),
            "--uc-volume", str(tmp_path / "uc_volume"),
            "--apply",
        ],
    )
    assert result.exit_code == 0, result.output

    sem = tmp_path / "out" / "SalesDashModel.SemanticModel" / "definition" / "tables"
    table_names = {p.stem for p in sem.iterdir()}
    assert {"Orders by Month", "Customer Spend"}.issubset(table_names)
