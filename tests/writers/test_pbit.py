from __future__ import annotations

import json
import zipfile
from pathlib import Path

from databricks_to_pbi.writers.pbi_model import (
    PBIColumn,
    PBIModel,
    PBITable,
)
from databricks_to_pbi.writers.pbit import write_pbit


def _model() -> PBIModel:
    return PBIModel(
        name="SalesModel", description=None,
        tables=[
            PBITable(
                name="Orders", storage_mode="direct_query", uc_path="main.sales.orders",
                sql_definition=None,
                columns=[
                    PBIColumn(name="amount", data_type="DECIMAL(18,2)", source_column="amount")
                ],
                measures=[], description=None, annotations=[],
            ),
        ],
        relationships=[], annotations=[],
    )


def test_write_pbit_produces_valid_zip_with_expected_parts(tmp_path: Path) -> None:
    out = tmp_path / "SalesModel.pbit"
    write_pbit(_model(), output_path=out)
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert "DataModel" in names
        assert "Connections" in names
        assert "[Content_Types].xml" in names
        assert "Version" in names


def test_pbit_datamodel_is_valid_tmsl(tmp_path: Path) -> None:
    out = tmp_path / "x.pbit"
    write_pbit(_model(), output_path=out)
    with zipfile.ZipFile(out) as zf, zf.open("DataModel") as f:
        data = json.loads(f.read().decode("utf-8"))
    assert data["name"] == "SalesModel"
    assert data["compatibilityLevel"] == 1567
    assert data["model"]["tables"][0]["name"] == "Orders"
