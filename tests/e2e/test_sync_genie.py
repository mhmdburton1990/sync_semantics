from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from databricks_to_pbi.cli import main


def test_genie_only_sync_emits_pbip_with_linked_tables_and_metric_measure(
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    genie_body = (fixtures_dir / "genie_spaces" / "sales_space.json").read_text()
    sdk = MagicMock()
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
            "--genie-space", "space-xyz-789",
            "--warehouse-id", "wh-1",
            "--model-name", "GenieSales",
            "--target-pbip", str(tmp_path / "out"),
            "--uc-volume", str(tmp_path / "uc_volume"),
            "--apply",
        ],
    )
    assert result.exit_code == 0, result.output

    sem = tmp_path / "out" / "GenieSales.SemanticModel" / "definition"
    assert (sem / "tables" / "orders.tmdl").exists()
    assert (sem / "tables" / "customers.tmdl").exists()

    # Measures live on the synthetic 'Measures' table.
    measures_tmdl = (sem / "tables" / "_Measures.tmdl").read_text(encoding="utf-8")
    assert "measure 'gross_revenue'" in measures_tmdl
