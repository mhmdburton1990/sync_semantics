from __future__ import annotations

import time
from datetime import UTC, datetime

import databricks_to_pbi.validation.jobs as jobs_mod
from databricks_to_pbi.ir import (
    Column,
    DatabricksSemanticIR,
    Dimension,
    Measure,
    SourceRef,
    Table,
)
from databricks_to_pbi.validation.jobs import JobRegistry, run_job
from databricks_to_pbi.validation.models import MeasureValidation
from databricks_to_pbi.validation.runner import ValidationContext
from databricks_to_pbi.validation.validate import DaxClientLike


class _StubWC:
    """Minimal WarehouseLike stub — never actually called in these tests."""

    def run_query(self, statement: str) -> list[list[object]]:
        return []


class _StubDax:
    """Minimal DaxClientLike stub — never actually called in these tests."""

    def scalar(self, measure: str, date_filter: str | None = None) -> float | None:
        return None

    def by_dim(
        self, measure: str, dax_table: str, dax_column: str,
        date_filter: str | None = None,
    ) -> dict[str | None, float | None]:
        return {}


def _src() -> SourceRef:
    return SourceRef(kind="metric_view", fully_qualified_name="main.s.mv",
                     object_hash="h", fetched_at=datetime(2026, 6, 4, tzinfo=UTC))


def _ctx(measure_names: list[str]) -> ValidationContext:
    col = Column(name="region", uc_path=None, data_type="string", role="dimension")
    table = Table(name="orders", uc_path="main.s.orders", sql_definition=None,
                  columns=[col], description=None, source=_src())
    dims = [Dimension(name="region", expression="region", underlying_columns=["region"],
                      description=None, hierarchy=None)]
    measures = [Measure(name=n, sql_expression="SUM(amount)", dependencies=[],
                        description=None, format_string=None, source=_src())
                for n in measure_names]
    ir = DatabricksSemanticIR(
        name="sales", description=None, tables=[table],
        dimensions=dims, measures=measures, relationships=[], sources=[_src()],
    )

    def _dax_factory(_n: str) -> DaxClientLike:
        return _StubDax()

    return ValidationContext(
        ir=ir, methods=dict.fromkeys(measure_names, "rule"), wc=_StubWC(),
        dataset_id="ds", workspace_id="ws", model="sales",
        ran_at=datetime(2026, 6, 4, tzinfo=UTC),
        dax_client_factory=_dax_factory,
    )


def test_run_job_validates_all_measures(monkeypatch: object) -> None:
    def fake_validate_one(_inputs: object, measure: Measure, _dim: object) -> MeasureValidation:
        return MeasureValidation(name=measure.name, status="passed", scalar_matched=True)
    monkeypatch.setattr(jobs_mod, "_validate_one", fake_validate_one)  # type: ignore[attr-defined]

    reg = JobRegistry()
    job_id = reg.register(_ctx(["a", "b"]))
    run_job(reg, job_id, _ctx(["a", "b"]), per_measure_timeout_s=5.0)

    job = reg.get(job_id)
    assert job is not None
    assert job.status == "done"
    assert [r.name for r in job.results] == ["a", "b"]
    assert job.summary().passed == 2


def test_run_job_times_out_slow_measure(monkeypatch: object) -> None:
    def slow_validate_one(_inputs: object, measure: Measure, _dim: object) -> MeasureValidation:
        time.sleep(0.5)
        return MeasureValidation(name=measure.name, status="passed")
    monkeypatch.setattr(jobs_mod, "_validate_one", slow_validate_one)  # type: ignore[attr-defined]

    reg = JobRegistry()
    ctx = _ctx(["slow"])
    job_id = reg.register(ctx)
    run_job(reg, job_id, ctx, per_measure_timeout_s=0.2)

    job = reg.get(job_id)
    assert job is not None
    assert job.status == "done"
    assert job.results[0].status == "skipped"
    assert "exceeded" in (job.results[0].skip_reason or "")


def test_query_canceled_midflight_ends_canceled(monkeypatch: object) -> None:
    from databricks_to_pbi.workspace import QueryCanceled

    reg = JobRegistry()
    ctx = _ctx(["a"])
    job_id = reg.register(ctx)

    # The worker hits a hard-cancelled statement: cancel flag set, QueryCanceled raised.
    def boom(_inputs: object, _measure: object, _dim: object) -> MeasureValidation:
        reg.cancel(job_id)
        raise QueryCanceled("statement canceled by user")
    monkeypatch.setattr(jobs_mod, "_validate_one", boom)  # type: ignore[attr-defined]

    run_job(reg, job_id, ctx, per_measure_timeout_s=1.0)

    job = reg.get(job_id)
    assert job is not None
    assert job.status == "canceled"  # not "error"


def test_run_job_clears_current_when_done(monkeypatch: object) -> None:
    def ok(_inputs: object, measure: Measure, _dim: object) -> MeasureValidation:
        return MeasureValidation(name=measure.name, status="passed")
    monkeypatch.setattr(jobs_mod, "_validate_one", ok)  # type: ignore[attr-defined]

    reg = JobRegistry()
    ctx = _ctx(["a"])
    job_id = reg.register(ctx)
    assert reg.get(job_id).current is None  # field exists, starts unset
    run_job(reg, job_id, ctx, per_measure_timeout_s=5.0)
    job = reg.get(job_id)
    assert job.status == "done"
    assert job.current is None  # cleared on terminal state


def test_run_job_records_error_on_exception(monkeypatch: object) -> None:
    def boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("kaboom")
    monkeypatch.setattr(jobs_mod, "compute_window", boom)  # type: ignore[attr-defined]

    reg = JobRegistry()
    ctx = _ctx(["a"])
    job_id = reg.register(ctx)
    run_job(reg, job_id, ctx, per_measure_timeout_s=1.0)

    job = reg.get(job_id)
    assert job is not None
    assert job.status == "error"
    assert "kaboom" in (job.error or "")


def test_get_unknown_job_returns_none() -> None:
    assert JobRegistry().get("nope") is None


def test_cancel_stops_job(monkeypatch: object) -> None:
    def fake_validate_one(_inputs: object, measure: Measure, _dim: object) -> MeasureValidation:
        return MeasureValidation(name=measure.name, status="passed", scalar_matched=True)
    monkeypatch.setattr(jobs_mod, "_validate_one", fake_validate_one)  # type: ignore[attr-defined]

    reg = JobRegistry()
    ctx = _ctx(["a", "b"])
    job_id = reg.register(ctx)
    # Cancel before running: the first is_canceled check in the loop fires immediately.
    reg.cancel(job_id)
    run_job(reg, job_id, ctx, per_measure_timeout_s=5.0)

    job = reg.get(job_id)
    assert job is not None
    assert job.status == "canceled"
    assert job.results == []


def test_cancel_unknown_job_returns_false() -> None:
    assert JobRegistry().cancel("nope") is False


def test_run_job_records_validation_on_done() -> None:
    from dataclasses import replace

    recorded: list[tuple[str, object]] = []

    class _Store:
        def record_validation(
            self, run_id: str, report: object, *, dimension: object, timeframe: object,
        ) -> None:
            recorded.append((run_id, report))

    ctx = replace(_ctx(["total"]), run_id="r-42")
    reg = JobRegistry()
    job_id = reg.register(ctx)
    run_job(reg, job_id, ctx, store=_Store())

    job = reg.get(job_id)
    assert job is not None and job.status == "done"
    assert recorded and recorded[0][0] == "r-42"


def test_run_job_without_run_id_does_not_record() -> None:
    recorded: list[str] = []

    class _Store:
        def record_validation(
            self, run_id: str, report: object, *, dimension: object, timeframe: object,
        ) -> None:
            recorded.append(run_id)

    ctx = _ctx(["total"])  # run_id defaults to None
    reg = JobRegistry()
    job_id = reg.register(ctx)
    run_job(reg, job_id, ctx, store=_Store())

    assert recorded == []
