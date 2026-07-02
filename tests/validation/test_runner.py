from __future__ import annotations

from datetime import UTC, datetime

from databricks_to_pbi.ir import (
    Column,
    DatabricksSemanticIR,
    Dimension,
    Measure,
    SourceRef,
    Table,
)
from databricks_to_pbi.validation.runner import ValidationContext, run_validation


def _src() -> SourceRef:
    return SourceRef(kind="metric_view", fully_qualified_name="main.s.mv",
                     object_hash="h", fetched_at=datetime(2026, 6, 3, tzinfo=UTC))


def _ir() -> DatabricksSemanticIR:
    t = Table(name="orders", uc_path="main.s.orders", sql_definition=None,
              columns=[Column(name="region", uc_path=None, data_type="string", role="dimension")],
              description=None, source=_src())
    d = [Dimension(name="region", expression="region", underlying_columns=["region"],
                   description=None, hierarchy=None)]
    m = [Measure(name="rev", sql_expression="SUM(amount)", dependencies=[],
                 description=None, format_string=None, source=_src())]
    return DatabricksSemanticIR(name="sales", description=None, tables=[t],
                                dimensions=d, measures=m, relationships=[], sources=[_src()])


class _FakeWc:
    def run_query(self, statement: str) -> list[list[object]]:
        if "approx_count_distinct" in statement:
            return [[3]]
        # scalar queries end with GROUP BY ALL; per-dim queries end with GROUP BY `col`
        if "GROUP BY ALL" in statement:
            return [[100.0]]
        if "GROUP BY" in statement:
            return [["EU", 60.0], ["US", 40.0]]
        return [[100.0]]


class _FakeDax:
    def scalar(self, measure: str, date_filter: str | None = None) -> float | None:
        return 100.0

    def by_dim(
        self, measure: str, dax_table: str, dax_column: str,
        date_filter: str | None = None,
    ) -> dict[str | None, float | None]:
        return {"EU": 60.0, "US": 40.0}


def test_run_validation_passes() -> None:
    ctx = ValidationContext(
        ir=_ir(), methods={"rev": "rule"}, wc=_FakeWc(),
        dataset_id="ds", workspace_id="ws", model="sales",
        ran_at=datetime(2026, 6, 3, tzinfo=UTC),
        dax_client_factory=lambda name: _FakeDax(),
    )
    report = run_validation(ctx)
    assert report.summary.passed == 1
