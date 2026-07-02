from __future__ import annotations

from datetime import UTC, datetime

from databricks_to_pbi.ir import (
    Column,
    DatabricksSemanticIR,
    GenieAnnotation,
    Measure,
    SourceRef,
    Table,
)
from databricks_to_pbi.sync.merge import merge_irs


def _src(kind: str, name: str = "x", h: str = "h") -> SourceRef:
    return SourceRef(
        kind=kind,  # type: ignore[arg-type]
        fully_qualified_name=name,
        object_hash=h,
        fetched_at=datetime.now(UTC),
    )


def _ir(
    name: str,
    *,
    tables: list[Table] | None = None,
    measures: list[Measure] | None = None,
    genie: GenieAnnotation | None = None,
) -> DatabricksSemanticIR:
    src = _src("metric_view", name=name)
    return DatabricksSemanticIR(
        name=name, description=None,
        tables=tables or [],
        dimensions=[], measures=measures or [],
        relationships=[],
        genie=genie,
        sources=[src],
    )


def test_merge_two_disjoint_irs_yields_union() -> None:
    src_a = _src("metric_view", "a")
    src_b = _src("dashboard", "b")
    a = _ir("A", tables=[Table(
        name="Orders", uc_path="main.sales.orders", sql_definition=None,
        storage_mode="direct_query", columns=[], description=None, source=src_a,
    )])
    b = _ir("B", tables=[Table(
        name="Customers", uc_path=None, sql_definition="SELECT * FROM x",
        storage_mode="direct_query", columns=[], description=None, source=src_b,
    )])
    merged = merge_irs([a, b], target_name="Sales")
    assert merged.name == "Sales"
    assert {t.name for t in merged.tables} == {"Orders", "Customers"}


def test_merge_keeps_higher_fidelity_table_on_uc_path_collision() -> None:
    mv_src = _src("metric_view", "mv")
    dash_src = _src("dashboard", "dash")
    mv_table = Table(name="Orders", uc_path="main.sales.orders", sql_definition=None,
                     storage_mode="direct_query",
                     columns=[Column(
                         name="amount", uc_path="main.sales.orders.amount",
                         data_type="DECIMAL(18,2)",
                     )],
                     description="canonical fact", source=mv_src)
    dash_table = Table(name="Orders", uc_path="main.sales.orders", sql_definition=None,
                       storage_mode="direct_query", columns=[], description=None, source=dash_src)
    merged = merge_irs(
        [_ir("from-dashboard", tables=[dash_table]), _ir("from-mv", tables=[mv_table])],
        target_name="Sales",
    )
    orders = next(t for t in merged.tables if t.uc_path == "main.sales.orders")
    assert orders.description == "canonical fact"
    assert len(orders.columns) == 1


def test_merge_keeps_higher_fidelity_measure_and_accumulates_sources() -> None:
    mv_src = _src("metric_view", "mv")
    genie_src = _src("genie_space", "space::gross_revenue")
    mv_measure = Measure(name="gross_revenue", sql_expression="SUM(amount)", dependencies=[],
                         description="MV measure", format_string=None, source=mv_src)
    genie_measure = Measure(name="gross_revenue", sql_expression="SUM(amount)", dependencies=[],
                            description="Genie measure", format_string=None, source=genie_src)
    merged = merge_irs(
        [_ir("genie", measures=[genie_measure]), _ir("mv", measures=[mv_measure])],
        target_name="x",
    )
    kept = next(m for m in merged.measures if m.name == "gross_revenue")
    assert kept.description == "MV measure"
    fqns = {s.fully_qualified_name for s in merged.sources}
    assert "mv" in fqns
    assert "space::gross_revenue" in fqns


def test_merge_picks_first_non_none_genie_annotation() -> None:
    a = _ir("a", genie=None)
    b = _ir("b", genie=GenieAnnotation(instructions="hello", sample_questions=[]))
    c = _ir("c", genie=GenieAnnotation(instructions="overridden", sample_questions=[]))
    merged = merge_irs([a, b, c], target_name="x")
    assert merged.genie is not None
    assert merged.genie.instructions == "hello"


def test_merge_dedups_sources_by_name_and_hash() -> None:
    s = _src("metric_view", "main.sales.mv", h="h1")
    a = DatabricksSemanticIR(name="a", description=None, tables=[], dimensions=[], measures=[],
                              relationships=[], genie=None, sources=[s])
    b = DatabricksSemanticIR(name="b", description=None, tables=[], dimensions=[], measures=[],
                              relationships=[], genie=None, sources=[s])
    merged = merge_irs([a, b], target_name="x")
    assert len(merged.sources) == 1


def test_merge_empty_list_yields_empty_ir() -> None:
    merged = merge_irs([], target_name="X")
    assert merged.name == "X"
    assert merged.tables == []
    assert merged.measures == []
    assert merged.genie is None
