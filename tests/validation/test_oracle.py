from __future__ import annotations

from databricks_to_pbi.validation.dimension import GroupByDim
from databricks_to_pbi.validation.oracle import (
    groupby_sql,
    run_oracle,
    scalar_sql,
)


def test_scalar_sql_shape() -> None:
    assert scalar_sql("main.s.mv", "total_rev") == (
        "SELECT MEASURE(`total_rev`) AS m FROM main.s.mv GROUP BY ALL"
    )


def test_scalar_sql_with_where() -> None:
    assert scalar_sql("main.s.mv", "rev", where="`d` >= DATE '2020-01-01'") == (
        "SELECT MEASURE(`rev`) AS m FROM main.s.mv WHERE `d` >= DATE '2020-01-01' GROUP BY ALL"
    )


def test_groupby_sql_with_where() -> None:
    assert groupby_sql("main.s.mv", "rev", "region", where="`d` <= DATE '2020-01-01'") == (
        "SELECT `region` AS k, MEASURE(`rev`) AS m "
        "FROM main.s.mv WHERE `d` <= DATE '2020-01-01' GROUP BY `region`"
    )


def test_groupby_sql_shape() -> None:
    assert groupby_sql("main.s.mv", "total_rev", "region") == (
        "SELECT `region` AS k, MEASURE(`total_rev`) AS m "
        "FROM main.s.mv GROUP BY `region`"
    )


class _FakeWc:
    def __init__(self, scalar: object, rows: list[list[object]]) -> None:
        self._scalar = scalar
        self._rows = rows
        self.statements: list[str] = []

    def run_query(self, statement: str) -> list[list[object]]:
        self.statements.append(statement)
        # scalar queries end with GROUP BY ALL; per-dim queries end with GROUP BY `col`
        if "GROUP BY ALL" in statement:
            return [[self._scalar]]
        return self._rows


def test_run_oracle_scalar_only() -> None:
    wc = _FakeWc(scalar="123.5", rows=[])
    res = run_oracle(wc, view="main.s.mv", measure="rev", dim=None)
    assert res.scalar == 123.5
    assert res.by_dim == {}
    assert len(wc.statements) == 1


def test_run_oracle_with_groupby() -> None:
    wc = _FakeWc(scalar=300, rows=[["EU", 200], ["US", 100], [None, 0]])
    dim = GroupByDim(sql_ref="region", dax_table="orders", dax_column="region")
    res = run_oracle(wc, view="main.s.mv", measure="rev", dim=dim)
    assert res.scalar == 300.0
    assert res.by_dim == {"EU": 200.0, "US": 100.0, None: 0.0}
