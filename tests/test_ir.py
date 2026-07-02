from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from databricks_to_pbi.ir import (
    Column,
    DatabricksSemanticIR,
    Dimension,
    GenieAnnotation,
    Measure,
    Relationship,
    SourceRef,
    Table,
)


def _src(kind: str = "metric_view", name: str = "main.x.y") -> SourceRef:
    return SourceRef(
        kind=kind,  # type: ignore[arg-type]
        fully_qualified_name=name,
        object_hash="deadbeefcafebabe",
        fetched_at=datetime(2026, 5, 26, 12, 0, tzinfo=UTC),
    )


def test_column_defaults() -> None:
    c = Column(name="amount", uc_path="main.sales.orders.amount", data_type="DECIMAL(18,2)")
    assert c.is_key is False
    assert c.role == "attribute"
    assert c.description is None


def test_column_invalid_role_rejected() -> None:
    with pytest.raises(ValidationError):
        Column(name="x", uc_path=None, data_type="STRING", role="totally-bogus")  # type: ignore[arg-type]


def test_dimension_requires_expression_and_columns() -> None:
    d = Dimension(
        name="OrderMonth",
        expression="DATE_TRUNC('MONTH', order_date)",
        underlying_columns=["orders.order_date"],
        description=None,
        hierarchy=None,
    )
    assert d.name == "OrderMonth"


def test_measure_carries_source_ref() -> None:
    m = Measure(
        name="Total Sales",
        sql_expression="SUM(amount)",
        dependencies=["orders.amount"],
        description="Sum of order line amounts.",
        format_string="$#,##0.00",
        source=_src(),
    )
    assert m.source.kind == "metric_view"


def test_relationship_default_cross_filter_is_single() -> None:
    r = Relationship(
        from_table="Orders",
        from_columns=["customer_id"],
        to_table="Customers",
        to_columns=["id"],
        cardinality="many_to_one",
    )
    assert r.cross_filter == "single"
    assert r.is_active is True


def test_relationship_rejects_unknown_cardinality() -> None:
    with pytest.raises(ValidationError):
        Relationship(
            from_table="A",
            from_columns=["x"],
            to_table="B",
            to_columns=["y"],
            cardinality="weird",  # type: ignore[arg-type]
        )


def test_source_ref_kinds_constrained() -> None:
    with pytest.raises(ValidationError):
        SourceRef(
            kind="invented",  # type: ignore[arg-type]
            fully_qualified_name="x",
            object_hash="h",
            fetched_at=datetime.now(UTC),
        )


def test_table_default_storage_mode_is_direct_query() -> None:
    t = Table(
        name="Orders",
        uc_path="main.sales.orders",
        sql_definition=None,
        columns=[
            Column(name="id", uc_path="main.sales.orders.id", data_type="BIGINT", is_key=True)
        ],
        description=None,
        source=_src(),
    )
    assert t.storage_mode == "direct_query"


def test_table_synthesized_from_sql_has_no_uc_path() -> None:
    t = Table(
        name="DashboardDataset_AOV",
        uc_path=None,
        sql_definition="SELECT customer_id, SUM(amount) AS spend FROM main.sales.orders GROUP BY 1",
        columns=[],
        description="Average order value rollup",
        source=_src(kind="dashboard", name="dash-123::ds-1"),
    )
    assert t.uc_path is None


def test_genie_annotation_holds_example_sqls() -> None:
    g = GenieAnnotation(
        instructions="Use month-over-month percent change for trend questions.",
        sample_questions=["What were last month's sales?"],
        example_question_sqls=[
            ("Last 30 days revenue", "SELECT SUM(amount) FROM main.sales.orders WHERE ...")
        ],
    )
    assert len(g.example_question_sqls) == 1


def test_databricks_semantic_ir_carries_all_collections() -> None:
    ir = DatabricksSemanticIR(
        name="Sales",
        description="Sales semantic model",
        tables=[],
        dimensions=[],
        measures=[],
        relationships=[],
        genie=None,
        sources=[_src()],
    )
    assert ir.name == "Sales"
    assert ir.genie is None


def test_databricks_semantic_ir_is_frozen() -> None:
    ir = DatabricksSemanticIR(
        name="x", description=None, tables=[], dimensions=[], measures=[],
        relationships=[], genie=None, sources=[],
    )
    with pytest.raises(ValidationError):
        ir.name = "y"


def test_measure_window_defaults_none_and_accepts_clauses() -> None:
    from datetime import UTC, datetime

    from databricks_to_pbi.ir import Measure, SourceRef, WindowClause

    src = SourceRef(kind="metric_view", fully_qualified_name="c.s.mv",
                    object_hash="h", fetched_at=datetime(2026, 6, 16, tzinfo=UTC))
    m = Measure(name="total_sales", sql_expression="SUM(x)", dependencies=[],
                description=None, format_string=None, source=src)
    assert m.window is None
    w = Measure(name="sales_last_7d", sql_expression="MEASURE(total_sales)", dependencies=[],
                description=None, format_string=None, source=src,
                window=[WindowClause(order="order_date", range="trailing 7 day inclusive")])
    assert w.window is not None
    assert w.window[0].order == "order_date"
    assert w.window[0].range == "trailing 7 day inclusive"
