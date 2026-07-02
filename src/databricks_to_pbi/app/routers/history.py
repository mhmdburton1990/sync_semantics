"""GET /api/sync/history + /api/sync/history/{run_id} — store-backed lookup."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from databricks_to_pbi.app.auth import current_obo_token
from databricks_to_pbi.app.deps import get_history_store
from databricks_to_pbi.app.errors import AppError
from databricks_to_pbi.app.models import HistoryEntry, RunDetail, SyncSourceRef
from databricks_to_pbi.history.store import RunDetailRow, RunHistoryStore
from databricks_to_pbi.reporting.confidence import render_confidence_html
from databricks_to_pbi.reporting.report import SyncReport
from databricks_to_pbi.validation.models import ValidationReport

__all__ = ["router"]


router = APIRouter(
    prefix="/api/sync/history",
    tags=["history"],
    dependencies=[Depends(current_obo_token)],
)


def _load_run(
    run_id: str, store: RunHistoryStore,
) -> tuple[RunDetailRow, SyncReport, ValidationReport | None]:
    row = store.get_run(run_id)
    if row is None:
        raise AppError(
            code="run_not_found",
            message=f"No run with run_id={run_id}",
            status_code=404,
        )
    if row.report_json is None:
        raise AppError(
            code="report_unavailable",
            message=f"Run {run_id} has no stored report payload.",
            status_code=500,
        )
    report = SyncReport.model_validate_json(row.report_json)
    validation = (
        ValidationReport.model_validate_json(row.validation_json) if row.validation_json else None
    )
    return row, report, validation


@router.get("", response_model=list[HistoryEntry])
def list_history(
    store: RunHistoryStore = Depends(get_history_store),  # noqa: B008
) -> list[HistoryEntry]:
    return [
        HistoryEntry(
            run_id=r.run_id,
            created_at=r.created_at,
            model_name=r.model_name,
            state=r.state,
            summary_created=r.measures_created,
            summary_updated=r.measures_updated,
            summary_needs_manual_review=r.needs_manual_review,
            validation_status=r.validation_status,
            val_passed=r.val_passed,
            val_failed=r.val_failed,
            val_skipped=r.val_skipped,
        )
        for r in store.list_runs()
    ]


@router.get("/{run_id}", response_model=RunDetail)
def get_history(
    run_id: str,
    store: RunHistoryStore = Depends(get_history_store),  # noqa: B008
) -> RunDetail:
    row, report, validation = _load_run(run_id, store)
    return RunDetail(
        run_id=row.run_id,
        created_at=row.created_at,
        run_by=row.run_by,
        model_name=row.model_name,
        delivery=row.delivery,
        state=row.state,
        validation_status=row.validation_status,
        report=report.model_copy(update={"validation": validation}),
        validation=validation,
        sources=[
            SyncSourceRef(kind=s.kind, id=s.fully_qualified_name)
            for s in report.source_inventory
        ],
        dataset_id=report.published_dataset_id,
        workspace_id=report.target.target_id,
        val_dimension=row.val_dimension,
        val_timeframe=row.val_timeframe,
    )


@router.get("/{run_id}/report.html")
def get_report_html(
    run_id: str,
    store: RunHistoryStore = Depends(get_history_store),  # noqa: B008
) -> Response:
    _row, report, validation = _load_run(run_id, store)
    return Response(
        content=render_confidence_html(report, validation),
        media_type="text/html",
    )
