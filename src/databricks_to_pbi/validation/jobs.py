"""In-memory async validation jobs: run validation off the request path.

The Databricks App is single-instance, so an in-memory registry is sufficient.
A job validates measures one at a time in a background thread, each bounded by a
wall-clock timeout so a slow MEASURE() query can't stall the whole job. Results
are appended as they complete so the client can poll for live progress.
"""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal, Protocol, cast

from databricks_to_pbi.history.store import RunHistoryStore, history_table_name
from databricks_to_pbi.ir import Measure
from databricks_to_pbi.validation.compare import DEFAULT_EPSILON
from databricks_to_pbi.validation.dimension import GroupByDim
from databricks_to_pbi.validation.models import (
    MeasureValidation,
    ValidationReport,
    ValidationSummary,
)
from databricks_to_pbi.validation.runner import ValidationContext
from databricks_to_pbi.validation.timeframe import DateWindow, compute_window
from databricks_to_pbi.validation.validate import (
    ValidationInputs,
    _validate_one,
)
from databricks_to_pbi.workspace import QueryCanceled

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_PER_MEASURE_TIMEOUT_S",
    "REGISTRY",
    "JobRegistry",
    "JobStatus",
    "ValidationJob",
    "run_job",
]

JobStatus = Literal["pending", "running", "done", "error", "canceled"]

DEFAULT_PER_MEASURE_TIMEOUT_S = 90.0


@dataclass
class ValidationJob:
    job_id: str
    model: str
    dataset_id: str
    workspace_id: str
    total: int
    started_at: datetime
    status: JobStatus = "pending"
    results: list[MeasureValidation] = field(default_factory=list)
    error: str | None = None
    current: str | None = None

    def summary(self) -> ValidationSummary:
        return ValidationSummary(
            passed=sum(1 for r in self.results if r.status == "passed"),
            failed=sum(1 for r in self.results if r.status == "failed"),
            skipped=sum(1 for r in self.results if r.status == "skipped"),
        )


class JobRegistry:
    """Thread-safe in-memory store of validation jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, ValidationJob] = {}
        self._lock = threading.Lock()
        self._cancels: dict[str, threading.Event] = {}

    def register(self, ctx: ValidationContext) -> str:
        job_id = uuid.uuid4().hex
        job = ValidationJob(
            job_id=job_id,
            model=ctx.model,
            dataset_id=ctx.dataset_id,
            workspace_id=ctx.workspace_id,
            total=len(ctx.ir.measures),
            started_at=ctx.ran_at,
        )
        with self._lock:
            self._jobs[job_id] = job
            self._cancels[job_id] = threading.Event()
        return job_id

    def get(self, job_id: str) -> ValidationJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def snapshot(self, job_id: str) -> ValidationJob | None:
        """A consistent point-in-time copy (results list copied under the lock),
        so a reader never sees a results/summary mismatch mid-append."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return replace(job, results=list(job.results))

    def _set_status(self, job_id: str, status: JobStatus, *, error: str | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = status
            if error is not None:
                job.error = error

    def _set_current(self, job_id: str, name: str | None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.current = name

    def _append_result(self, job_id: str, result: MeasureValidation) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.results.append(result)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancels.get(job_id)
            if event is None:
                return False
            event.set()
            return True

    def is_canceled(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancels.get(job_id)
            return event.is_set() if event is not None else False

    def start(
        self,
        ctx: ValidationContext,
        *,
        per_measure_timeout_s: float = DEFAULT_PER_MEASURE_TIMEOUT_S,
        store: _HistoryStoreLike | None = None,
    ) -> str:
        """Register a job and run it in a background daemon thread.

        ``store`` is injectable for tests; in production it defaults to None and
        ``run_job`` builds a real RunHistoryStore from ctx.wc.
        """
        job_id = self.register(ctx)
        thread = threading.Thread(
            target=run_job,
            args=(self, job_id, ctx, per_measure_timeout_s),
            kwargs={"store": store},
            daemon=True,
        )
        thread.start()
        return job_id


REGISTRY = JobRegistry()


def _inputs_from_ctx(ctx: ValidationContext, window: DateWindow | None) -> ValidationInputs:
    return ValidationInputs(
        ir=ctx.ir,
        methods=ctx.methods,
        wc=ctx.wc,
        dax_client_for=ctx.dax_client_factory,
        model=ctx.model,
        dataset_id=ctx.dataset_id,
        workspace_id=ctx.workspace_id,
        ran_at=ctx.ran_at,
        dim_override=ctx.dim_override,
        date_window=window,
    )


def _validate_measure_bounded(
    inputs: ValidationInputs,
    measure: Measure,
    dim: GroupByDim | None,
    timeout_s: float,
) -> MeasureValidation:
    """Validate one measure, abandoning it (skipped) if it exceeds ``timeout_s``.

    The executor is not context-managed and is shut down with wait=False so a
    timed-out (still-running) query does not block the job; that orphaned thread
    finishes on its own later.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_validate_one, inputs, measure, dim)
        try:
            return future.result(timeout=timeout_s)
        except FuturesTimeout:
            return MeasureValidation(
                name=measure.name,
                status="skipped",
                skip_reason=f"Validation exceeded {int(timeout_s)}s — try a narrower timeframe.",
                skip_category="timeout",
            )
        except QueryCanceled:
            return MeasureValidation(
                name=measure.name,
                status="skipped",
                skip_reason="Canceled by user.",
                skip_category="canceled",
            )
    finally:
        executor.shutdown(wait=False)


class _HistoryStoreLike(Protocol):
    def record_validation(
        self, run_id: str, report: ValidationReport, *,
        dimension: str | None, timeframe: str,
    ) -> None: ...


def _build_report(ctx: ValidationContext, job: ValidationJob) -> ValidationReport:
    return ValidationReport(
        model=ctx.model,
        dataset_id=ctx.dataset_id,
        workspace_id=ctx.workspace_id,
        epsilon=DEFAULT_EPSILON,
        ran_at=ctx.ran_at,
        results=list(job.results),
        summary=job.summary(),
    )


def _record_if_possible(
    ctx: ValidationContext, job: ValidationJob | None,
    store: _HistoryStoreLike | None,
) -> None:
    if ctx.run_id is None or store is None or job is None:
        return
    try:
        store.record_validation(
            ctx.run_id, _build_report(ctx, job),
            dimension=ctx.dim_override.sql_ref if ctx.dim_override else None,
            timeframe=ctx.timeframe,
        )
    except Exception:  # best-effort; never fail the job over history logging
        log.warning("failed to record validation for run %s", ctx.run_id, exc_info=True)


def run_job(
    registry: JobRegistry,
    job_id: str,
    ctx: ValidationContext,
    per_measure_timeout_s: float = DEFAULT_PER_MEASURE_TIMEOUT_S,
    store: _HistoryStoreLike | None = None,
) -> None:
    """Validate every measure, appending results for live polling. Synchronous;
    ``JobRegistry.start`` runs it in a thread. On a terminal state the verdict is
    recorded to run history (best-effort) when a run_id is known.

    ``store`` defaults to a RunHistoryStore built from ctx.wc; tests pass a fake.
    """
    if store is None and ctx.history_namespace is not None:
        try:
            # ctx.wc is a WorkspaceClient at runtime; _WCLike needs only run_query.
            store = RunHistoryStore(
                wc=cast(Any, ctx.wc),
                table=history_table_name(*ctx.history_namespace),
            )
        except Exception:  # never let history setup break validation
            store = None
    registry._set_status(job_id, "running")
    # Let the warehouse client hard-cancel its in-flight statement when this job
    # is canceled (duck-typed so fakes without the hook are unaffected).
    set_check = getattr(ctx.wc, "set_cancel_check", None)
    if callable(set_check):
        set_check(lambda: registry.is_canceled(job_id))
    try:
        dim = ctx.dim_override   # no auto-pick; user-chosen (or grand total)
        window = compute_window(ctx.wc, ctx.ir, ctx.timeframe, ctx.date_override)
        inputs = _inputs_from_ctx(ctx, window)
        for measure in ctx.ir.measures:
            if registry.is_canceled(job_id):
                registry._set_current(job_id, None)
                registry._set_status(job_id, "canceled")
                _record_if_possible(ctx, registry.snapshot(job_id), store)
                return
            registry._set_current(job_id, measure.name)
            result = _validate_measure_bounded(inputs, measure, dim, per_measure_timeout_s)
            # A cancel may have hard-killed the query mid-measure; don't append the
            # partial/canceled result — just end as canceled.
            if registry.is_canceled(job_id):
                registry._set_current(job_id, None)
                registry._set_status(job_id, "canceled")
                _record_if_possible(ctx, registry.snapshot(job_id), store)
                return
            registry._append_result(job_id, result)
        registry._set_current(job_id, None)
        registry._set_status(job_id, "done")
        _record_if_possible(ctx, registry.snapshot(job_id), store)
    except Exception as exc:  # a job failure must surface as state, not crash
        registry._set_current(job_id, None)
        registry._set_status(job_id, "error", error=str(exc)[:300])
    finally:
        if callable(set_check):
            set_check(None)
