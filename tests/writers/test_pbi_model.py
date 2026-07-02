from __future__ import annotations

from datetime import UTC, datetime

import pytest

from databricks_to_pbi.ir import (
    Column,
    DatabricksSemanticIR,
    Measure,
    Relationship,
    SourceRef,
    Table,
)
from databricks_to_pbi.writers.pbi_model import (
    PBIModel,
    build_pbi_model,
)


def _src(name: str = "main.sales.mv", h: str = "h1") -> SourceRef:
    return SourceRef(
        kind="metric_view",
        fully_qualified_name=name,
        object_hash=h,
        fetched_at=datetime(2026, 5, 26, tzinfo=UTC),
    )


def test_build_pbi_model_carries_annotations() -> None:
    src = _src()
    ir = DatabricksSemanticIR(
        name="SalesModel",
        description=None,
        tables=[
            Table(
                name="Orders",
                uc_path="main.sales.orders",
                sql_definition=None,
                storage_mode="direct_query",
                columns=[
                    Column(
                        name="amount",
                        uc_path="main.sales.orders.amount",
                        data_type="DECIMAL(18,2)",
                    )
                ],
                description=None,
                source=src,
            ),
        ],
        dimensions=[],
        measures=[
            Measure(
                name="Total Sales",
                sql_expression="SUM(amount)",
                dependencies=[],
                description=None,
                format_string=None,
                source=src,
            ),
        ],
        relationships=[],
        genie=None,
        sources=[src],
    )

    pm = build_pbi_model(
        ir,
        measure_dax={"Total Sales": "SUM('Orders'[amount])"},
        synced_at=datetime(2026, 5, 26, tzinfo=UTC),
    )
    assert isinstance(pm, PBIModel)
    assert pm.tables[0].name == "Orders"
    # Measures now live on a dedicated synthetic "Measures" table, not on
    # the host fact table.
    assert pm.tables[0].measures == []
    measures_table = next(t for t in pm.tables if t.is_measures_table)
    assert measures_table.name == "_Measures"
    assert measures_table.measures[0].dax == "SUM('Orders'[amount])"
    annos = {a.name: a.value for a in measures_table.measures[0].annotations}
    assert annos["dbx2pbi_source_kind"] == "metric_view"
    assert annos["dbx2pbi_object_hash"] == "h1"


def test_build_pbi_model_raises_for_missing_dax() -> None:
    src = _src()
    ir = DatabricksSemanticIR(
        name="X", description=None,
        tables=[
            Table(
                name="X", uc_path="main.x.y", sql_definition=None,
                storage_mode="direct_query", columns=[], description=None, source=src,
            ),
        ],
        dimensions=[],
        measures=[
            Measure(
                name="M", sql_expression="SUM(x)", dependencies=[],
                description=None, format_string=None, source=src,
            )
        ],
        relationships=[], genie=None, sources=[src],
    )
    with pytest.raises(KeyError):
        build_pbi_model(ir, measure_dax={}, synced_at=datetime(2026, 5, 26, tzinfo=UTC))


def test_relationship_mapped() -> None:
    src = _src()
    ir = DatabricksSemanticIR(
        name="x", description=None,
        tables=[], dimensions=[],
        measures=[],
        relationships=[Relationship(
            from_table="Orders", from_columns=["customer_id"],
            to_table="Customers", to_columns=["id"],
            cardinality="many_to_one",
        )],
        genie=None, sources=[src],
    )
    pm = build_pbi_model(ir, measure_dax={}, synced_at=datetime(2026, 5, 26, tzinfo=UTC))
    assert len(pm.relationships) == 1
    assert pm.relationships[0].cardinality == "many_to_one"
