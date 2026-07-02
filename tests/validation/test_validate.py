from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from databricks_to_pbi.ir import (
    Column,
    DatabricksSemanticIR,
    Dimension,
    Measure,
    SourceRef,
    Table,
)
from databricks_to_pbi.validation.dimension import GroupByDim
from databricks_to_pbi.validation.oracle import OracleResult
from databricks_to_pbi.validation.timeframe import DateWindow
from databricks_to_pbi.validation.validate import ValidationInputs, validate_model


def _src(kind: str = "metric_view") -> SourceRef:
    return SourceRef(
        kind=kind,  # type: ignore[arg-type]
        fully_qualified_name="main.s.mv",
        object_hash="h",
        fetched_at=datetime(2026, 6, 3, tzinfo=UTC),
    )


def _measure(name: str, kind: str = "metric_view") -> Measure:
    return Measure(
        name=name, sql_expression="SUM(amount)", dependencies=[],
        description=None, format_string=None, source=_src(kind),
    )


def _ir(measures: list[Measure]) -> DatabricksSemanticIR:
    table = Table(
        name="orders", uc_path="main.s.orders", sql_definition=None,
        columns=[Column(name="region", uc_path=None, data_type="string", role="dimension")],
        description=None, source=_src(),
    )
    dims = [Dimension(name="region", expression="region",
                      underlying_columns=["region"], description=None, hierarchy=None)]
    return DatabricksSemanticIR(
        name="sales", description=None, tables=[table], dimensions=dims,
        measures=measures, relationships=[], sources=[_src()],
    )


class _FakeOracle:
    def __init__(self, result: OracleResult) -> None:
        self._r = result

    def __call__(
        self, wc: object, *, view: str, measure: str, dim: GroupByDim | None,
        where: str | None = None,
    ) -> OracleResult:
        return self._r


class _FakeDax:
    def __init__(self, scalar: float | None, by_dim: dict[str, float]) -> None:
        self._s = scalar
        self._b = by_dim

    def scalar(self, measure: str, date_filter: str | None = None) -> float | None:
        return self._s

    def by_dim(
        self, measure: str, dax_table: str, dax_column: str,
        date_filter: str | None = None,
    ) -> dict[str, float]:
        return self._b


def _inputs(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ir": _ir([_measure("rev")]),
        "methods": {"rev": "rule"},
        "dax": {"rev": _FakeDax(100.0, {"EU": 60.0, "US": 40.0})},
        "wc": object(),
        "dim": GroupByDim(sql_ref="region", dax_table="orders", dax_column="region"),
        "oracle": _FakeOracle(OracleResult(scalar=100.0, by_dim={"EU": 60.0, "US": 40.0})),
    }
    base.update(kw)
    return base


def _run(cfg: dict[str, Any]) -> Any:
    return validate_model(
        ValidationInputs(
            ir=cfg["ir"],
            methods=cfg["methods"],
            wc=cfg["wc"],
            dax_client_for=lambda name: cfg["dax"][name],
            dim_override=cfg["dim"],
            oracle_fn=cfg["oracle"],
            model="sales",
            dataset_id="ds",
            workspace_id="ws",
            ran_at=datetime(2026, 6, 3, tzinfo=UTC),
        )
    )


def test_passed_when_all_match() -> None:
    report = _run(_inputs())
    assert report.summary.passed == 1
    r = report.results[0]
    assert r.status == "passed"
    assert r.dim_used == "region"
    assert {d.key for d in r.by_dim} == {"EU", "US"}


def test_failed_on_scalar_mismatch() -> None:
    cfg = _inputs(dax={"rev": _FakeDax(999.0, {"EU": 60.0, "US": 40.0})})
    report = _run(cfg)
    assert report.results[0].status == "failed"
    assert report.summary.failed == 1


def test_failed_when_dim_key_missing_on_dax_side() -> None:
    cfg = _inputs(dax={"rev": _FakeDax(100.0, {"EU": 60.0})})  # missing US
    report = _run(cfg)
    r = report.results[0]
    assert r.status == "failed"
    us = next(d for d in r.by_dim if d.key == "US")
    assert us.dax is None and us.matched is False


def test_skip_placeholder() -> None:
    cfg = _inputs(methods={"rev": "placeholder"})
    report = _run(cfg)
    assert report.results[0].status == "skipped"
    assert "placeholder" in (report.results[0].skip_reason or "")
    assert report.summary.skipped == 1


def test_skip_non_metric_view() -> None:
    cfg = _inputs(ir=_ir([_measure("rev", kind="dashboard")]))
    report = _run(cfg)
    assert report.results[0].status == "skipped"
    assert "metric view" in (report.results[0].skip_reason or "").lower()


def test_query_error_marks_skipped() -> None:
    class _Boom:
        def scalar(self, measure: str, date_filter: str | None = None) -> float | None:
            raise RuntimeError("model still refreshing")

        def by_dim(
            self, measure: str, dax_table: str, dax_column: str,
            date_filter: str | None = None,
        ) -> dict[str, float]:
            raise RuntimeError("model still refreshing")

    cfg = _inputs(dax={"rev": _Boom()})
    report = _run(cfg)
    r = report.results[0]
    assert r.status == "skipped"
    # raw error is now in skip_detail; skip_reason holds the actionable hint
    assert "refreshing" in (r.skip_detail or "")
    assert r.skip_category == "dax_error"


def test_date_window_threads_filters() -> None:
    """where + date_filter are forwarded to oracle and DAX client when a DateWindow is set."""
    captured_where: list[str | None] = []
    captured_date_filter: list[str | None] = []

    class _RecordingOracle:
        def __call__(
            self, wc: object, *, view: str, measure: str, dim: GroupByDim | None,
            where: str | None = None,
        ) -> OracleResult:
            captured_where.append(where)
            return OracleResult(scalar=100.0)

    class _RecordingDax:
        def scalar(self, measure: str, date_filter: str | None = None) -> float | None:
            captured_date_filter.append(date_filter)
            return 100.0

        def by_dim(
            self, measure: str, dax_table: str, dax_column: str,
            date_filter: str | None = None,
        ) -> dict[str | None, float | None]:
            return {}

    class _NullWC:
        def run_query(self, statement: str) -> list[list[object]]:
            return []

    window = DateWindow(
        sql_column="d", dax_table="t", dax_column="d",
        start=date(2020, 1, 1), end=date(2020, 12, 31),
    )
    dax_client = _RecordingDax()
    validate_model(
        ValidationInputs(
            ir=_ir([_measure("rev")]),
            methods={"rev": "rule"},
            wc=_NullWC(),
            dax_client_for=lambda _name: dax_client,
            dim_override=None,
            oracle_fn=_RecordingOracle(),
            model="sales",
            dataset_id="ds",
            workspace_id="ws",
            ran_at=datetime(2026, 6, 3, tzinfo=UTC),
            date_window=window,
        )
    )

    assert len(captured_where) == 1
    assert captured_where[0] is not None
    assert len(captured_date_filter) == 1
    assert captured_date_filter[0] is not None


def test_skip_dax_credentials_is_categorized() -> None:
    class _BadDax:
        def scalar(self, measure: str, date_filter: str | None = None) -> float | None:
            raise RuntimeError("DatasetExecuteQueriesError: sign in required")

        def by_dim(
            self, measure: str, dax_table: str, dax_column: str,
            date_filter: str | None = None,
        ) -> dict[str | None, float | None]:
            return {}

    ir = _ir([_measure("total")])
    inputs = ValidationInputs(
        ir=ir, methods={"total": "rule"}, wc=object(),  # type: ignore[arg-type]
        dax_client_for=lambda _m: _BadDax(),
        model="m", dataset_id="d", workspace_id="w",
        ran_at=datetime(2026, 6, 11, tzinfo=UTC),
        oracle_fn=_FakeOracle(OracleResult(scalar=10.0)),
    )
    report = validate_model(inputs)
    r = report.results[0]
    assert r.status == "skipped"
    assert r.skip_category == "credentials_not_signed_in"
    assert r.failed_side == "dax"


def test_skip_source_error_is_categorized() -> None:
    def _boom(wc: object, **_: object) -> OracleResult:
        raise RuntimeError("metric view exploded")

    ir = _ir([_measure("total")])
    inputs = ValidationInputs(
        ir=ir, methods={"total": "rule"}, wc=object(),  # type: ignore[arg-type]
        dax_client_for=lambda _m: object(),  # type: ignore[arg-type,return-value]
        model="m", dataset_id="d", workspace_id="w",
        ran_at=datetime(2026, 6, 11, tzinfo=UTC),
        oracle_fn=_boom,
    )
    report = validate_model(inputs)
    r = report.results[0]
    assert r.status == "skipped"
    assert r.skip_category == "source_sql_error"
    assert r.failed_side == "source_sql"
