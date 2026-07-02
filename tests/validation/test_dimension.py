from __future__ import annotations

from datetime import UTC, datetime

from databricks_to_pbi.ir import (
    Column,
    DatabricksSemanticIR,
    Dimension,
    SourceRef,
    Table,
)
from databricks_to_pbi.validation.dimension import candidate_dims


def _src() -> SourceRef:
    return SourceRef(
        kind="metric_view",
        fully_qualified_name="main.sales.orders_mv",
        object_hash="deadbeef",
        fetched_at=datetime(2026, 6, 3, tzinfo=UTC),
    )


def _ir() -> DatabricksSemanticIR:
    cols = [
        Column(
            name="region", source_column="REGION",
            uc_path=None, data_type="string", role="dimension",
        ),
        Column(
            name="amount", source_column="AMOUNT",
            uc_path=None, data_type="double", role="fact",
        ),
    ]
    table = Table(name="orders", uc_path="main.sales.orders", sql_definition=None,
                  columns=cols, description=None, source=_src())
    dims = [
        Dimension(name="region", expression="region", underlying_columns=["region"],
                  description=None, hierarchy=None),
        # computed dim — two underlying columns, NOT a candidate
        Dimension(name="full_name", expression="concat(a,b)", underlying_columns=["a", "b"],
                  description=None, hierarchy=None),
    ]
    return DatabricksSemanticIR(
        name="sales", description=None, tables=[table], dimensions=dims,
        measures=[], relationships=[], sources=[_src()],
    )


def test_candidate_dims_only_clean_1to1() -> None:
    cands = candidate_dims(_ir())
    assert [c.sql_ref for c in cands] == ["region"]
    assert cands[0].dax_table == "orders"
    assert cands[0].dax_column == "region"




def test_candidate_dims_resolves_dotted_join_paths() -> None:
    from datetime import UTC, datetime

    from databricks_to_pbi.ir import (
        Column,
        DatabricksSemanticIR,
        Dimension,
        SourceRef,
        Table,
    )

    src = SourceRef(kind="metric_view", fully_qualified_name="main.s.mv",
                    object_hash="h", fetched_at=datetime(2026, 6, 4, tzinfo=UTC))

    def _t(name: str, cols: list[str]) -> Table:
        return Table(name=name, uc_path=f"main.s.{name}", sql_definition=None,
                     columns=[Column(name=c, uc_path=None, data_type="string", role="dimension")
                              for c in cols],
                     description=None, source=src)

    ir = DatabricksSemanticIR(
        name="x", description=None,
        tables=[_t("lineitem", ["l_returnflag"]), _t("orders", ["o_orderstatus"]),
                _t("customer", ["c_name"]), _t("calendar", ["year"])],
        dimensions=[
            Dimension(name=n, expression=n, underlying_columns=[u],
                      description=None, hierarchy=None)
            for n, u in [
                ("l_returnflag", "l_returnflag"),
                ("o_orderstatus", "orders.o_orderstatus"),
                ("c_name", "orders.customer.c_name"),
                ("order_year", "orders.calendar.year"),
            ]
        ],
        measures=[], relationships=[], sources=[src],
    )
    by_ref = {c.sql_ref: (c.dax_table, c.dax_column) for c in candidate_dims(ir)}
    assert by_ref["l_returnflag"] == ("lineitem", "l_returnflag")
    assert by_ref["o_orderstatus"] == ("orders", "o_orderstatus")
    assert by_ref["c_name"] == ("customer", "c_name")
    # sql_ref is the dimension name; dax column resolves to calendar.year
    assert by_ref["order_year"] == ("calendar", "year")
