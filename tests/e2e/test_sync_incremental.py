from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner, Result

from databricks_to_pbi.cli import main


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    fixtures_dir: Path,
    tmp_path: Path,
    yaml_file: str,
) -> Result:
    yaml_body = (fixtures_dir / "metric_views" / yaml_file).read_text()
    sdk = MagicMock()
    sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(data_array=[["View Definition", yaml_body, ""]])
    )
    monkeypatch.setattr("databricks_to_pbi.cli._make_sdk_client", lambda: sdk)

    runner = CliRunner()
    return runner.invoke(
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


def test_re_apply_with_no_changes_reports_all_unchanged(
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r1 = _invoke(monkeypatch, fixtures_dir, tmp_path, "sales_simple.yaml")
    assert r1.exit_code == 0, r1.output
    r2 = _invoke(monkeypatch, fixtures_dir, tmp_path, "sales_simple.yaml")
    assert r2.exit_code == 0, r2.output
    assert "unchanged=" in r2.output
    assert "created=0" in r2.output
