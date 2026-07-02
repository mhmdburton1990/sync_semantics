from __future__ import annotations

from datetime import UTC, date, datetime

from databricks_to_pbi.ir import (
    Column,
    DatabricksSemanticIR,
    Dimension,
    SourceRef,
    Table,
)
from databricks_to_pbi.validation.timeframe import (
    DateWindow,
    candidate_date_columns,
    compute_window,
    dax_predicate,
    detect_date_column,
    sql_where,
)


def _ir() -> DatabricksSemanticIR:
    src = SourceRef(kind="metric_view", fully_qualified_name="main.s.mv",
                    object_hash="h", fetched_at=datetime(2026, 6, 4, tzinfo=UTC))
    cols = [
        Column(name="region", uc_path=None, data_type="string", role="dimension"),
        Column(name="o_orderdate", uc_path=None, data_type="date", role="dimension"),
        Column(name="amount", uc_path=None, data_type="double", role="fact"),
    ]
    table = Table(name="orders", uc_path="main.s.orders", sql_definition=None,
                  columns=cols, description=None, source=src)
    dims = [Dimension(name="o_orderdate", expression="o_orderdate",
                      underlying_columns=["o_orderdate"], description=None, hierarchy=None)]
    return DatabricksSemanticIR(name="sales", description=None, tables=[table],
                                dimensions=dims, measures=[], relationships=[], sources=[src])


def test_detect_date_column_picks_first_date() -> None:
    assert detect_date_column(_ir()) == ("o_orderdate", "orders", "o_orderdate")


def test_detect_date_column_none_when_absent() -> None:
    ir = _ir()
    ir2 = ir.model_copy(update={"tables": [ir.tables[0].model_copy(
        update={"columns": [c for c in ir.tables[0].columns if c.data_type != "date"]})]})
    assert detect_date_column(ir2) is None


class _FakeWc:
    def run_query(self, statement: str) -> list[list[object]]:
        assert "MAX(`o_orderdate`)" in statement
        return [["1998-08-02"]]


def test_compute_window_year() -> None:
    w = compute_window(_FakeWc(), _ir(), "year")
    assert w is not None
    assert w.sql_column == "o_orderdate"
    assert w.dax_table == "orders"
    assert w.end == date(1998, 8, 2)
    assert w.start == date(1997, 8, 2)  # 365 days earlier


def test_compute_window_all_is_none() -> None:
    assert compute_window(_FakeWc(), _ir(), "all") is None


def test_sql_where_shape() -> None:
    w = DateWindow(sql_column="o_orderdate", dax_table="orders", dax_column="o_orderdate",
                   start=date(1997, 8, 2), end=date(1998, 8, 2))
    assert sql_where(w) == (
        "`o_orderdate` >= DATE '1997-08-02' AND `o_orderdate` <= DATE '1998-08-02'"
    )


def test_dax_predicate_shape() -> None:
    w = DateWindow(sql_column="o_orderdate", dax_table="orders", dax_column="o_orderdate",
                   start=date(1997, 8, 2), end=date(1998, 8, 2))
    assert dax_predicate(w) == (
        "'orders'[o_orderdate] >= DATE(1997,8,2) && 'orders'[o_orderdate] <= DATE(1998,8,2)"
    )


def test_compute_window_month() -> None:
    w = compute_window(_FakeWc(), _ir(), "month")
    assert w is not None
    assert w.end == date(1998, 8, 2)
    assert w.start == date(1998, 7, 3)  # 30 days earlier


def test_compute_window_day() -> None:
    w = compute_window(_FakeWc(), _ir(), "day")
    assert w is not None
    assert w.end == date(1998, 8, 2)
    assert w.start == date(1998, 8, 1)  # 1 day earlier


def test_compute_window_week() -> None:
    w = compute_window(_FakeWc(), _ir(), "week")
    assert w is not None
    assert w.start == date(1998, 7, 26)  # 7 days earlier


def test_compute_window_quarter() -> None:
    w = compute_window(_FakeWc(), _ir(), "quarter")
    assert w is not None
    assert w.start == date(1998, 5, 4)  # 90 days earlier


def test_detect_date_column_prefers_declared_dimension() -> None:
    src = SourceRef(kind="metric_view", fully_qualified_name="main.s.mv",
                    object_hash="h", fetched_at=datetime(2026, 6, 4, tzinfo=UTC))
    cols = [
        Column(name="raw_dt", uc_path=None, data_type="timestamp", role="attribute"),
        Column(name="order_day", uc_path=None, data_type="date", role="dimension"),
    ]
    table = Table(name="orders", uc_path="main.s.orders", sql_definition=None,
                  columns=cols, description=None, source=src)
    dims = [Dimension(name="order_day", expression="order_day",
                      underlying_columns=["order_day"], description=None, hierarchy=None)]
    ir = DatabricksSemanticIR(name="sales", description=None, tables=[table],
                              dimensions=dims, measures=[], relationships=[], sources=[src])
    # raw_dt comes first by column order, but order_day is the declared dimension
    assert detect_date_column(ir) == ("order_day", "orders", "order_day")


def test_candidate_date_columns_lists_all_sorted() -> None:
    from databricks_to_pbi.ir import Relationship

    src = SourceRef(kind="metric_view", fully_qualified_name="main.s.mv",
                    object_hash="h", fetched_at=datetime(2026, 6, 4, tzinfo=UTC))

    def _t(name: str, col: str) -> Table:
        return Table(name=name, uc_path=f"main.s.{name}", sql_definition=None,
                     columns=[Column(name=col, uc_path=None, data_type="date", role="dimension")],
                     description=None, source=src)

    ir = DatabricksSemanticIR(
        name="x", description=None,
        tables=[_t("lineitem", "l_shipdate"), _t("orders", "o_orderdate")],
        dimensions=[
            Dimension(name="l_shipdate", expression="l_shipdate",
                      underlying_columns=["l_shipdate"], description=None, hierarchy=None),
            Dimension(name="o_orderdate", expression="orders.o_orderdate",
                      underlying_columns=["o_orderdate"], description=None, hierarchy=None),
        ],
        measures=[],
        relationships=[Relationship(from_table="lineitem", from_columns=["l_orderkey"],
                                    to_table="orders", to_columns=["o_orderkey"],
                                    cardinality="many_to_one")],
        sources=[src],
    )
    cands = candidate_date_columns(ir)
    assert cands[0] == ("o_orderdate", "orders", "o_orderdate")  # parent first
    assert ("l_shipdate", "lineitem", "l_shipdate") in cands
    assert len(cands) == 2


def test_compute_window_honors_date_override() -> None:
    src = SourceRef(kind="metric_view", fully_qualified_name="main.s.mv",
                    object_hash="h", fetched_at=datetime(2026, 6, 4, tzinfo=UTC))
    cols = [
        Column(name="ship_dt", uc_path=None, data_type="date", role="dimension"),
        Column(name="order_dt", uc_path=None, data_type="date", role="dimension"),
    ]
    table = Table(name="orders", uc_path="main.s.orders", sql_definition=None,
                  columns=cols, description=None, source=src)
    dims = [
        Dimension(name="ship_dt", expression="ship_dt",
                  underlying_columns=["ship_dt"], description=None, hierarchy=None),
        Dimension(name="order_dt", expression="order_dt",
                  underlying_columns=["order_dt"], description=None, hierarchy=None),
    ]
    ir = DatabricksSemanticIR(name="sales", description=None, tables=[table],
                              dimensions=dims, measures=[], relationships=[], sources=[src])

    class _Wc:
        def run_query(self, statement: str) -> list[list[object]]:
            assert "MAX(`ship_dt`)" in statement  # override column used, not the default
            return [["1998-08-02"]]

    w = compute_window(_Wc(), ir, "year", date_override=("orders", "ship_dt"))
    assert w is not None
    assert w.sql_column == "ship_dt"


def test_compute_window_unknown_override_falls_back_to_detect() -> None:
    w = compute_window(_FakeWc(), _ir(), "year", date_override=("nope", "missing"))
    assert w is not None
    assert w.sql_column == "o_orderdate"  # fell back to auto-detect


def test_detect_date_column_prefers_parent_table() -> None:
    from databricks_to_pbi.ir import Relationship

    src = SourceRef(kind="metric_view", fully_qualified_name="main.s.mv",
                    object_hash="h", fetched_at=datetime(2026, 6, 4, tzinfo=UTC))

    def _t(name: str, col: str) -> Table:
        return Table(name=name, uc_path=f"main.s.{name}", sql_definition=None,
                     columns=[Column(name=col, uc_path=None, data_type="date", role="dimension")],
                     description=None, source=src)

    # lineitem (leaf, *) -> orders (parent, 1); both have a date column.
    ir = DatabricksSemanticIR(
        name="x", description=None,
        tables=[_t("lineitem", "l_shipdate"), _t("orders", "o_orderdate")],
        dimensions=[
            Dimension(name="l_shipdate", expression="l_shipdate",
                      underlying_columns=["l_shipdate"], description=None, hierarchy=None),
            Dimension(name="o_orderdate", expression="o_orderdate",
                      underlying_columns=["o_orderdate"], description=None, hierarchy=None),
        ],
        measures=[],
        relationships=[Relationship(from_table="lineitem", from_columns=["l_orderkey"],
                                    to_table="orders", to_columns=["o_orderkey"],
                                    cardinality="many_to_one")],
        sources=[src],
    )
    # orders is the parent (to_table) → o_orderdate must be preferred over l_shipdate.
    assert detect_date_column(ir) == ("o_orderdate", "orders", "o_orderdate")


def test_candidate_date_columns_uses_dimension_names_not_physical() -> None:
    # A metric view exposes its DIMENSIONS as queryable columns, not the
    # underlying physical columns. The picker must offer date DIMENSIONS
    # (e.g. order_date) — querying a physical col like o_orderdate fails.
    from databricks_to_pbi.ir import Relationship

    src = SourceRef(kind="metric_view", fully_qualified_name="main.s.mv",
                    object_hash="h", fetched_at=datetime(2026, 6, 4, tzinfo=UTC))

    def _t(name: str, col: str) -> Table:
        return Table(name=name, uc_path=f"main.s.{name}", sql_definition=None,
                     columns=[Column(name=col, uc_path=None, data_type="date", role="dimension")],
                     description=None, source=src)

    ir = DatabricksSemanticIR(
        name="x", description=None,
        tables=[_t("lineitem", "l_receiptdate"), _t("calendar", "date"),
                _t("orders", "o_orderdate")],
        dimensions=[
            # order_date is exposed via the calendar join (renamed!), receipt_date is bare.
            Dimension(name="order_date", expression="source.calendar.date",
                      underlying_columns=["date"], description=None, hierarchy=None),
            Dimension(name="receipt_date", expression="l_receiptdate",
                      underlying_columns=["l_receiptdate"], description=None, hierarchy=None),
        ],
        measures=[],
        relationships=[Relationship(from_table="lineitem", from_columns=["l_receiptdate"],
                                    to_table="calendar", to_columns=["date"],
                                    cardinality="many_to_one")],
        sources=[src],
    )
    cands = candidate_date_columns(ir)
    sql_cols = [c[0] for c in cands]
    assert "order_date" in sql_cols          # the dimension name (queryable on the view)
    assert "o_orderdate" not in sql_cols     # physical col, not a dimension → excluded
    assert ("order_date", "calendar", "date") in cands  # resolves to PBI calendar.date for DAX
