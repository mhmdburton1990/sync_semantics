from __future__ import annotations

import json
from pathlib import Path

from databricks_to_pbi.writers.pbi_model import (
    PBIAnnotation,
    PBIColumn,
    PBIMeasure,
    PBIModel,
    PBIRelationship,
    PBITable,
)
from databricks_to_pbi.writers.tmsl import render_tmsl, write_bim


def _model() -> PBIModel:
    return PBIModel(
        name="SalesModel", description=None,
        tables=[
            PBITable(
                name="Orders",
                storage_mode="direct_query",
                uc_path="main.sales.orders",
                sql_definition=None,
                columns=[
                    PBIColumn(name="amount", data_type="DECIMAL(18,2)", source_column="amount")
                ],
                measures=[PBIMeasure(
                    name="Total Sales", dax="SUM('Orders'[amount])",
                    annotations=[PBIAnnotation(name="dbx2pbi_object_hash", value="h1")],
                )],
                description="Sales fact",
                annotations=[
                    PBIAnnotation(name="dbx2pbi_source_kind", value="metric_view"),
                    PBIAnnotation(name="dbx2pbi_object_hash", value="hT"),
                ],
            ),
        ],
        relationships=[
            PBIRelationship(
                from_table="Orders", from_columns=["customer_id"],
                to_table="Customers", to_columns=["id"],
                cardinality="many_to_one",
            ),
        ],
        annotations=[],
    )


def test_render_tmsl_top_level_shape() -> None:
    tmsl = render_tmsl(_model())
    assert tmsl["createOrReplace"]["database"]["name"] == "SalesModel"
    assert tmsl["createOrReplace"]["database"]["compatibilityLevel"] == 1567


def test_render_tmsl_includes_table_columns_measures() -> None:
    tmsl = render_tmsl(_model())
    db = tmsl["createOrReplace"]["database"]
    table = db["model"]["tables"][0]
    assert table["name"] == "Orders"
    assert table["columns"][0]["name"] == "amount"
    assert table["measures"][0]["name"] == "Total Sales"
    assert table["measures"][0]["expression"] == "SUM('Orders'[amount])"


def test_render_tmsl_attaches_dbx2pbi_annotations() -> None:
    tmsl = render_tmsl(_model())
    table = tmsl["createOrReplace"]["database"]["model"]["tables"][0]
    annos = {a["name"]: a["value"] for a in table["annotations"]}
    assert annos["dbx2pbi_source_kind"] == "metric_view"


def test_render_tmsl_emits_relationships() -> None:
    tmsl = render_tmsl(_model())
    rels = tmsl["createOrReplace"]["database"]["model"]["relationships"]
    assert len(rels) == 1
    assert rels[0]["fromTable"] == "Orders"
    assert rels[0]["toTable"] == "Customers"
    assert rels[0]["fromCardinality"] == "many"
    assert rels[0]["toCardinality"] == "one"


def test_write_bim_creates_file(tmp_path: Path) -> None:
    path = tmp_path / "Model.bim"
    write_bim(_model(), output_path=path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["createOrReplace"]["database"]["name"] == "SalesModel"
