"""POST /api/sync/preview + /api/sync/apply — engine entry points."""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from databricks_to_pbi.app.auth import current_obo_token
from databricks_to_pbi.app.deps import (
    get_current_user_email,
    get_uc_volume_root,
    get_workspace_client,
)
from databricks_to_pbi.app.errors import AppError
from databricks_to_pbi.app.models import (
    DateColumnRef,
    DimensionsRequest,
    StartValidationResponse,
    SyncRequest,
    SyncSourceRef,
    ValidateRequest,
    ValidationDimensionsResponse,
    ValidationJobStatus,
)
from databricks_to_pbi.auth.fabric import load_credentials_from_env
from databricks_to_pbi.history.store import (
    RunHistoryStore,
    history_table_name,
    namespace_from_sources,
)
from databricks_to_pbi.ir import DatabricksSemanticIR
from databricks_to_pbi.readers.dashboard import read_dashboard
from databricks_to_pbi.readers.genie import read_genie_space
from databricks_to_pbi.readers.metric_view import read_metric_view
from databricks_to_pbi.reporting.html import write_html
from databricks_to_pbi.reporting.markdown import write_markdown
from databricks_to_pbi.reporting.report import SyncReport, write_json
from databricks_to_pbi.sync.engine import (
    SyncInputsMulti,
    run_sync_multi,
    translate_for_validation,
)
from databricks_to_pbi.sync.manifest import TargetDescriptor
from databricks_to_pbi.sync.merge import merge_irs
from databricks_to_pbi.translator.cache import TranslationCache
from databricks_to_pbi.translator.claude_client import load_from_env
from databricks_to_pbi.validation.dimension import candidate_dims
from databricks_to_pbi.validation.jobs import REGISTRY
from databricks_to_pbi.validation.runner import (
    ValidationContext,
    default_dax_factory,
)
from databricks_to_pbi.validation.timeframe import candidate_date_columns
from databricks_to_pbi.workspace import WorkspaceClient

__all__ = ["router"]


router = APIRouter(
    prefix="/api/sync",
    tags=["sync"],
    dependencies=[Depends(current_obo_token)],
)


# Databricks Apps containers don't fuse-mount /Workspace or /Volumes, so the
# only path the App SP can write to is its own filesystem. We force PBIP/PBIT
# output into a known subdir of /tmp so the download endpoint can stream it
# back to the user later — whatever the user typed gets remapped here.
_APP_OUTPUT_ROOT = Path("/tmp/dbx2pbi/out")

_SAFE_BASENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_basename(name: str) -> str:
    cleaned = _SAFE_BASENAME_RE.sub("_", name.strip()) or "model"
    return cleaned[:80]


def _resolve_target_id(req: SyncRequest) -> str:
    """For pbip/pbit, redirect any user-supplied filesystem path into /tmp/."""
    if req.target.kind in ("pbip", "pbit"):
        safe = _safe_basename(req.model_name)
        suffix = ".pbit" if req.target.kind == "pbit" else ""
        return str(_APP_OUTPUT_ROOT / f"{safe}{suffix}")
    return req.target.target_id


def _build_partial_irs(
    sources: list[SyncSourceRef],
    wc: WorkspaceClient,
) -> list[DatabricksSemanticIR]:
    if not sources:
        raise AppError(
            code="no_sources",
            message="At least one source is required.",
            suggestion="Pick at least one metric view, dashboard, or Genie space.",
            status_code=400,
        )
    irs: list[DatabricksSemanticIR] = []
    for s in sources:
        if s.kind == "metric_view":
            irs.append(read_metric_view(wc, fully_qualified_name=s.id))
        elif s.kind == "dashboard":
            irs.append(read_dashboard(wc, dashboard_id=s.id))
        else:
            irs.append(read_genie_space(wc, space_id=s.id))
    return irs


def _databricks_connection_defaults(wc: WorkspaceClient) -> tuple[str | None, str | None]:
    """Read the Databricks workspace host + HTTP path so they can become
    defaults for the published model's WorkspaceHost / HttpPath parameters.

    Host comes from the ``DATABRICKS_HOST`` env var the App container is
    started with (bare hostname, no scheme). HTTP path is built from the
    SQL warehouse the user has selected.
    """
    host = os.environ.get("DATABRICKS_HOST") or None
    if host:
        # Strip scheme if present — PBI's Databricks connector wants the bare
        # hostname (matches what the workspace settings UI shows).
        host = host.removeprefix("https://").removeprefix("http://").rstrip("/")
    http_path = f"/sql/1.0/warehouses/{wc.warehouse_id}" if wc.warehouse_id else None
    return host, http_path


@router.post("/preview", response_model=SyncReport)
def sync_preview(
    req: SyncRequest,
    wc: WorkspaceClient = Depends(get_workspace_client),  # noqa: B008
    uc_volume: Path = Depends(get_uc_volume_root),  # noqa: B008
) -> SyncReport:
    partial_irs = _build_partial_irs(req.sources, wc)
    cache = TranslationCache.load(uc_volume / "caches" / "sql_to_dax.json")
    target = TargetDescriptor(kind=req.target.kind, target_id=_resolve_target_id(req))
    host, http_path = _databricks_connection_defaults(wc)
    return run_sync_multi(
        inputs=SyncInputsMulti(
            partial_irs=partial_irs,
            target=target,
            mode="preview",
            target_model_name=req.model_name,
            target_model_description=req.description,
            xmla_merge=req.xmla_merge,
            workspace_host=host,
            http_path=http_path,
            storage_mode_overrides=dict(req.storage_modes),
        ),
        cache=cache,
        uc_volume_root=uc_volume,
        claude=load_from_env(),
    )


@router.post("/validate/start", response_model=StartValidationResponse)
def validate_start(
    req: ValidateRequest,
    wc: WorkspaceClient = Depends(get_workspace_client),  # noqa: B008
    uc_volume: Path = Depends(get_uc_volume_root),  # noqa: B008
) -> StartValidationResponse:
    partial_irs = _build_partial_irs(req.sources, wc)
    merged = merge_irs(partial_irs, target_name=req.model_name, description=None)
    if req.exclude_measures:
        excluded = set(req.exclude_measures)
        merged = merged.model_copy(update={
            "measures": [m for m in merged.measures if m.name not in excluded],
        })
    cache = TranslationCache.load(uc_volume / "caches" / "sql_to_dax.json")
    methods = translate_for_validation(merged, cache, load_from_env())
    dim_override = None
    if req.dim_sql_ref:
        dim_override = next(
            (d for d in candidate_dims(merged) if d.sql_ref == req.dim_sql_ref), None,
        )
        if dim_override is None:
            valid = ", ".join(sorted(d.sql_ref for d in candidate_dims(merged))) or "(none)"
            raise AppError(
                code="unknown_dim_sql_ref",
                message=f"dim_sql_ref {req.dim_sql_ref!r} is not a valid group-by dimension.",
                suggestion=f"Valid candidate dimensions: {valid}.",
                status_code=422,
            )
    date_override: tuple[str, str] | None = None
    if req.date_table is not None or req.date_column is not None:
        if req.date_table is None or req.date_column is None:
            raise AppError(
                code="unknown_date_column",
                message="Both date_table and date_column are required to pick a calendar column.",
                suggestion="Send both, or neither to auto-detect.",
                status_code=422,
            )
        match = next(
            (c for c in candidate_date_columns(merged)
             if c[1] == req.date_table and c[2] == req.date_column),
            None,
        )
        if match is None:
            valid = ", ".join(
                f"{t}.{c}" for (_v, t, c) in candidate_date_columns(merged)
            ) or "(none)"
            raise AppError(
                code="unknown_date_column",
                message=f"{req.date_table}.{req.date_column} is not a date column in this model.",
                suggestion=f"Valid calendar columns: {valid}.",
                status_code=422,
            )
        date_override = (req.date_table, req.date_column)
    if load_credentials_from_env() is None:
        raise AppError(
            code="no_fabric_credentials",
            message="Cannot run validation: no Fabric credentials configured.",
            suggestion="Set FABRIC_SP_CLIENT_ID / FABRIC_SP_CLIENT_SECRET / FABRIC_TENANT_ID.",
            status_code=422,
        )
    ctx = ValidationContext(
        ir=merged,
        methods=methods,
        wc=wc,
        dataset_id=req.dataset_id,
        workspace_id=req.workspace_id,
        model=req.model_name,
        ran_at=datetime.now(UTC),
        dax_client_factory=default_dax_factory(
            workspace_id=req.workspace_id, dataset_id=req.dataset_id,
        ),
        dim_override=dim_override,
        timeframe=req.timeframe,
        date_override=date_override,
        run_id=req.run_id,
        history_namespace=namespace_from_sources(s.id for s in req.sources),
    )
    job_id = REGISTRY.start(ctx)
    return StartValidationResponse(job_id=job_id, total=len(merged.measures))


@router.get("/validate/jobs/{job_id}", response_model=ValidationJobStatus)
def validate_job(job_id: str) -> ValidationJobStatus:
    job = REGISTRY.snapshot(job_id)
    if job is None:
        raise AppError(
            code="validation_job_not_found",
            message=f"No validation job {job_id!r} (it may have expired on restart).",
            suggestion="Start validation again.",
            status_code=404,
        )
    return ValidationJobStatus(
        status=job.status,
        total=job.total,
        results=job.results,
        summary=job.summary(),
        error=job.error,
        current=job.current,
    )


@router.post("/validate/dimensions", response_model=ValidationDimensionsResponse)
def validate_dimensions(
    req: DimensionsRequest,
    wc: WorkspaceClient = Depends(get_workspace_client),  # noqa: B008
) -> ValidationDimensionsResponse:
    partial_irs = _build_partial_irs(req.sources, wc)
    merged = merge_irs(partial_irs, target_name=req.model_name, description=None)
    cands = candidate_date_columns(merged)
    return ValidationDimensionsResponse(
        dimensions=[d.sql_ref for d in candidate_dims(merged)],
        has_date_column=bool(cands),
        date_columns=[DateColumnRef(table=t, column=c) for (_view, t, c) in cands],
    )


@router.post("/validate/jobs/{job_id}/cancel", response_model=ValidationJobStatus)
def validate_cancel(job_id: str) -> ValidationJobStatus:
    if not REGISTRY.cancel(job_id):
        raise AppError(
            code="validation_job_not_found",
            message=f"No validation job {job_id!r} to cancel.",
            suggestion="It may have already finished or expired.",
            status_code=404,
        )
    job = REGISTRY.snapshot(job_id)
    if job is None:
        raise AppError(
            code="validation_job_not_found",
            message=f"No validation job {job_id!r}.",
            suggestion="Start validation again.",
            status_code=404,
        )
    return ValidationJobStatus(
        status=job.status, total=job.total, results=job.results,
        summary=job.summary(), error=job.error, current=job.current,
    )


@router.post("/apply")
async def sync_apply(
    req: SyncRequest,
    wc: WorkspaceClient = Depends(get_workspace_client),  # noqa: B008
    uc_volume: Path = Depends(get_uc_volume_root),  # noqa: B008
    run_by: str | None = Depends(get_current_user_email),
) -> EventSourceResponse:
    partial_irs = _build_partial_irs(req.sources, wc)
    cache = TranslationCache.load(uc_volume / "caches" / "sql_to_dax.json")
    target = TargetDescriptor(kind=req.target.kind, target_id=_resolve_target_id(req))
    host, http_path = _databricks_connection_defaults(wc)

    async def stream() -> AsyncIterator[dict[str, str]]:
        yield {"event": "start", "data": json.dumps({"model": req.model_name})}
        report = run_sync_multi(
            inputs=SyncInputsMulti(
                partial_irs=partial_irs,
                target=target,
                mode="apply",
                target_model_name=req.model_name,
                target_model_description=req.description,
                xmla_merge=req.xmla_merge,
                workspace_host=host,
                http_path=http_path,
                exclude_measures=frozenset(req.exclude_measures),
            ),
            cache=cache,
            uc_volume_root=uc_volume,
            claude=load_from_env(),
        )
        # NOTE: validation is intentionally NOT run synchronously here. Source
        # MEASURE() queries can take minutes, which would block the apply
        # request past proxy/browser timeouts. Validation runs as a manual,
        # async job after publish: POST /api/sync/validate/start then poll
        # GET /api/sync/validate/jobs/{job_id}.
        cache.save()
        write_json(report, root=uc_volume)
        write_markdown(report, root=uc_volume)
        write_html(report, root=uc_volume)
        try:
            namespace = namespace_from_sources(s.id for s in req.sources)
            if namespace is None:
                raise ValueError(
                    "no Unity Catalog source to anchor run history "
                    "(needs a catalog.schema.object source)"
                )
            RunHistoryStore(
                wc=wc, table=history_table_name(*namespace),
            ).record_apply(report, run_by=run_by)
        except Exception as exc:  # best-effort; never break a successful apply
            yield {
                "event": "history_warning",
                "data": json.dumps({"message": str(exc)[:300]}),
            }
        yield {"event": "done", "data": report.model_dump_json()}

    return EventSourceResponse(stream())


def _zip_dir(src: Path) -> Iterator[bytes]:
    """Yield a ZIP archive of `src` in memory chunks suitable for streaming."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(src)))
    buf.seek(0)
    while True:
        chunk = buf.read(64 * 1024)
        if not chunk:
            break
        yield chunk


@router.get("/download")
def download_output(
    model: str = Query(..., description="PBIP model name (basename only)."),
) -> StreamingResponse:
    """Stream the App-container's PBIP/PBIT output for a model as a ZIP."""
    safe = _safe_basename(model)
    pbip_dir = _APP_OUTPUT_ROOT / safe
    pbit_file = _APP_OUTPUT_ROOT / f"{safe}.pbit"

    if pbit_file.is_file():
        # Single-file delivery — stream the .pbit directly.
        def _file_iter() -> Iterator[bytes]:
            with pbit_file.open("rb") as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(
            _file_iter(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{safe}.pbit"'},
        )

    if not pbip_dir.is_dir():
        raise AppError(
            code="output_not_found",
            message=f"No PBIP/PBIT output for model={safe!r}.",
            suggestion="Run apply against this model first.",
            status_code=404,
        )
    return StreamingResponse(
        _zip_dir(pbip_dir),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}.zip"'},
    )
