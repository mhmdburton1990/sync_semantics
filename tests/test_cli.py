from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from databricks_to_pbi.cli import main


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "sync" in result.output


def test_cli_sync_dry_run_with_mocked_reader(tmp_path: Path, fixtures_dir: Path) -> None:
    yaml_body = (fixtures_dir / "metric_views" / "sales_simple.yaml").read_text()
    sdk_resp = MagicMock(result=MagicMock(data_array=[["View Definition", yaml_body, ""]]))
    with patch("databricks_to_pbi.cli._make_sdk_client") as factory:
        sdk = MagicMock()
        sdk.statement_execution.execute_statement.return_value = sdk_resp
        factory.return_value = sdk

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
                "--preview",
            ],
        )

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "out").exists()
    reports = list((tmp_path / "uc_volume" / "reports").glob("*.json"))
    assert reports


def test_cli_accepts_multiple_sources(tmp_path: Path, fixtures_dir: Path) -> None:
    yaml_body = (fixtures_dir / "metric_views" / "sales_simple.yaml").read_text()
    dash_body = (fixtures_dir / "lakeview_dashboards" / "sales_dashboard.json").read_text()
    genie_body = (fixtures_dir / "genie_spaces" / "sales_space.json").read_text()

    sdk_resp_mv = MagicMock(result=MagicMock(data_array=[["View Definition", yaml_body, ""]]))
    sdk = MagicMock()
    sdk.statement_execution.execute_statement.return_value = sdk_resp_mv
    sdk.lakeview = MagicMock()
    sdk.lakeview.get.return_value = MagicMock(
        as_dict=MagicMock(return_value={"serialized_dashboard": dash_body}),
    )
    sdk.genie = MagicMock()
    sdk.genie.get_space.return_value = MagicMock(
        as_dict=MagicMock(return_value={"serialized_space": genie_body}),
    )

    with patch("databricks_to_pbi.cli._make_sdk_client", return_value=sdk):
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "sync",
                "--metric-view", "main.sales.orders_mv",
                "--dashboard", "dash-abc-123",
                "--genie-space", "space-xyz-789",
                "--warehouse-id", "wh-1",
                "--target-pbip", str(tmp_path / "out"),
                "--uc-volume", str(tmp_path / "uc_volume"),
                "--model-name", "CombinedSales",
                "--apply",
            ],
        )
    assert result.exit_code == 0, result.output

    sem = tmp_path / "out" / "CombinedSales.SemanticModel" / "definition" / "tables"
    assert (sem / "orders.tmdl").exists()


def test_cli_pbit_delivery(tmp_path: Path, fixtures_dir: Path) -> None:
    yaml_body = (fixtures_dir / "metric_views" / "sales_simple.yaml").read_text()
    sdk = MagicMock()
    sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(data_array=[["View Definition", yaml_body, ""]]),
    )
    with patch("databricks_to_pbi.cli._make_sdk_client", return_value=sdk):
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "sync",
                "--metric-view", "main.sales.orders_mv",
                "--warehouse-id", "wh-1",
                "--target-pbit", str(tmp_path / "out.pbit"),
                "--uc-volume", str(tmp_path / "uc_volume"),
                "--model-name", "SalesModel",
                "--apply",
            ],
        )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out.pbit").exists()


def test_cli_xmla_delivery_requires_creds(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    yaml_body = (fixtures_dir / "metric_views" / "sales_simple.yaml").read_text()
    sdk = MagicMock()
    sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(data_array=[["View Definition", yaml_body, ""]]),
    )
    for k in ("FABRIC_SP_CLIENT_ID", "FABRIC_SP_CLIENT_SECRET", "FABRIC_TENANT_ID"):
        monkeypatch.delenv(k, raising=False)

    with patch("databricks_to_pbi.cli._make_sdk_client", return_value=sdk):
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "sync",
                "--metric-view", "main.sales.orders_mv",
                "--warehouse-id", "wh-1",
                "--target-xmla", "ws-123",
                "--uc-volume", str(tmp_path / "uc_volume"),
                "--model-name", "SalesModel",
                "--apply",
            ],
        )
    assert result.exit_code != 0
    assert "Fabric" in result.output or "credentials" in result.output.lower()


def test_cli_warns_when_no_anthropic_key_and_lists_untranslated_measures(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    untranslatable_yaml = """version: 0.1
source: main.sales.orders
dimensions:
  - name: order_date
    expr: order_date
measures:
  - name: total_sales
    expr: SUM(amount)
  - name: prev_day_sales
    expr: LAG(SUM(amount), 1) OVER (ORDER BY order_date)
"""
    sdk = MagicMock()
    sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(data_array=[["View Definition", untranslatable_yaml, ""]]),
    )

    with patch("databricks_to_pbi.cli._make_sdk_client", return_value=sdk):
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
    assert "ANTHROPIC_API_KEY" in result.output
    assert (
        "LLM fallback disabled" in result.output
        or "manual review" in result.output.lower()
    )
    assert "prev_day_sales" in result.output


def test_cli_no_banner_when_anthropic_key_is_set(
    tmp_path: Path, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    yaml_body = (fixtures_dir / "metric_views" / "sales_simple.yaml").read_text()
    sdk = MagicMock()
    sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(data_array=[["View Definition", yaml_body, ""]]),
    )
    fake_client = MagicMock()
    fake_client.translate.return_value = "SUM('orders'[amount])"

    with patch("databricks_to_pbi.cli._make_sdk_client", return_value=sdk), \
         patch("databricks_to_pbi.cli._load_claude_client", return_value=fake_client):
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
    assert "LLM fallback disabled" not in result.output
