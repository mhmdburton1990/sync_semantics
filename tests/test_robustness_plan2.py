from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from databricks_to_pbi.readers.dashboard import parse_dashboard_json, read_dashboard
from databricks_to_pbi.readers.genie import parse_genie_space, read_genie_space
from databricks_to_pbi.sync.merge import merge_irs
from databricks_to_pbi.workspace import WorkspaceClient
from databricks_to_pbi.writers.pbi_model import PBIModel
from databricks_to_pbi.writers.pbit import write_pbit
from databricks_to_pbi.writers.tmsl import render_tmsl


def test_parse_dashboard_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        parse_dashboard_json("[]")


def test_parse_genie_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        parse_genie_space("[]")


def test_dashboard_with_no_datasets_yields_empty_tables() -> None:
    sdk = MagicMock()
    sdk.lakeview = MagicMock()
    sdk.lakeview.get.return_value = MagicMock(
        as_dict=MagicMock(
            return_value={
                "serialized_dashboard": '{"id":"x","name":"y","datasets":[],"widgets":[]}',
            },
        ),
    )
    wc = WorkspaceClient(sdk_client=sdk, warehouse_id="wh-1")
    ir = read_dashboard(wc, dashboard_id="x")
    assert ir.tables == []
    assert ir.measures == []


def test_genie_with_no_metric_definitions() -> None:
    sdk = MagicMock()
    sdk.genie = MagicMock()
    sdk.genie.get_space.return_value = MagicMock(
        as_dict=MagicMock(
            return_value={"serialized_space": '{"id":"x","name":"y","instructions":"hi"}'},
        ),
    )
    wc = WorkspaceClient(sdk_client=sdk, warehouse_id="wh-1")
    ir = read_genie_space(wc, space_id="x")
    assert ir.measures == []
    assert ir.genie is not None
    assert ir.genie.instructions == "hi"


def test_merge_empty_list_yields_empty_ir() -> None:
    merged = merge_irs([], target_name="X")
    assert merged.name == "X"
    assert merged.tables == []


def test_pbit_with_empty_model_is_valid_zip(tmp_path: Path) -> None:
    out = tmp_path / "empty.pbit"
    write_pbit(
        PBIModel(
            name="Empty", description=None, tables=[],
            relationships=[], annotations=[],
        ),
        output_path=out,
    )
    assert out.exists()


def test_tmsl_render_for_empty_model() -> None:
    payload = render_tmsl(
        PBIModel(
            name="E", description=None, tables=[],
            relationships=[], annotations=[],
        ),
    )
    assert payload["createOrReplace"]["database"]["model"]["tables"] == []
