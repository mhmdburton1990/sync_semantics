"""GET /api/sources/* — discovery endpoints for selectable inputs."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query

from databricks_to_pbi.app.auth import current_obo_token
from databricks_to_pbi.app.deps import get_workspace_client, require_warehouse_id
from databricks_to_pbi.app.errors import AppError
from databricks_to_pbi.app.models import (
    CatalogSummary,
    DashboardSummary,
    GenieSpaceSummary,
    MetricViewSummary,
    SchemaSummary,
)
from databricks_to_pbi.ir import DatabricksSemanticIR
from databricks_to_pbi.readers.dashboard import read_dashboard
from databricks_to_pbi.readers.genie import read_genie_space
from databricks_to_pbi.readers.metric_view import read_metric_view
from databricks_to_pbi.workspace import WorkspaceClient

__all__ = ["router"]


router = APIRouter(
    prefix="/api/sources",
    tags=["sources"],
    dependencies=[Depends(current_obo_token)],
)


def _parse_iso(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# Valid UC identifier: letters, digits, underscore. Backticks/dots/quotes
# rejected so the SQL string-interpolation paths below stay safe. UC names
# can technically contain a wider character set if backtick-quoted, but
# the picker UX only surfaces simple identifiers from `SHOW` results.
_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _require_ident(value: str, field: str) -> str:
    if not _IDENT_RE.match(value):
        raise AppError(
            code="invalid_identifier",
            message=f"{field} must contain only letters, digits, and underscores",
            status_code=400,
        )
    return value


@router.get("/catalogs", response_model=list[CatalogSummary])
def list_catalogs(
    wc: WorkspaceClient = Depends(get_workspace_client),  # noqa: B008
    _: str = Depends(require_warehouse_id),
) -> list[CatalogSummary]:
    """Catalogs the OBO user can see (filtered by Unity Catalog grants)."""
    rows = wc.run_query("SHOW CATALOGS")
    return [CatalogSummary(name=str(r[0])) for r in rows if r and r[0]]


@router.get(
    "/catalogs/{catalog}/schemas", response_model=list[SchemaSummary],
)
def list_schemas(
    catalog: str,
    wc: WorkspaceClient = Depends(get_workspace_client),  # noqa: B008
    _: str = Depends(require_warehouse_id),
) -> list[SchemaSummary]:
    """Schemas in a catalog (filtered by UC grants)."""
    _require_ident(catalog, "catalog")
    rows = wc.run_query(f"SHOW SCHEMAS IN {catalog}")
    return [
        SchemaSummary(name=str(r[0]))
        for r in rows
        if r and r[0] and str(r[0]).lower() != "information_schema"
    ]


@router.get("/metric_views", response_model=list[MetricViewSummary])
def list_metric_views(
    catalog: str | None = Query(None),
    schema: str | None = Query(None),
    wc: WorkspaceClient = Depends(get_workspace_client),  # noqa: B008
    _: str = Depends(require_warehouse_id),
) -> list[MetricViewSummary]:
    """List metric views the OBO user has SELECT on.

    With no filters, scans every catalog (one ``system.information_schema``
    query). With ``catalog`` + ``schema``, narrows to that namespace —
    significantly faster on workspaces with hundreds of catalogs and
    lets the UI's Catalog → Schema picker control what shows up.
    """
    if catalog:
        _require_ident(catalog, "catalog")
    if schema:
        _require_ident(schema, "schema")

    where = ["table_type = 'METRIC_VIEW'"]
    if catalog:
        where.append(f"table_catalog = '{catalog}'")
    if schema:
        where.append(f"table_schema = '{schema}'")
    query = (
        "SELECT table_catalog || '.' || table_schema || '.' || table_name AS fqn, "
        "       table_owner AS owner, comment AS description "
        "FROM system.information_schema.tables "
        "WHERE " + " AND ".join(where) + " "
        "ORDER BY 1"
    )
    rows = wc.run_query(query)
    return [
        MetricViewSummary(
            fully_qualified_name=str(r[0]),
            owner=str(r[1]) if r[1] else None,
            description=str(r[2]) if r[2] else None,
        )
        for r in rows
    ]


def _is_permission_denied(exc: BaseException) -> bool:
    """Detect Databricks SDK PermissionDenied without importing the class."""
    return type(exc).__name__ == "PermissionDenied"


@router.get("/dashboards", response_model=list[DashboardSummary])
def list_dashboards(
    wc: WorkspaceClient = Depends(get_workspace_client),  # noqa: B008
) -> list[DashboardSummary]:
    # Lakeview dashboards have no public OBO scope yet. Return empty when
    # the caller's token doesn't have access so the UI doesn't error-banner.
    try:
        raw = list(wc._sdk.lakeview.list())
    except Exception as exc:
        if _is_permission_denied(exc):
            return []
        raise
    return [
        DashboardSummary(
            id=d.dashboard_id,
            name=d.display_name,
            owner=getattr(d, "owner", None),
            updated_at=_parse_iso(getattr(d, "update_time", None)),
        )
        for d in raw
    ]


@router.get("/genie_spaces", response_model=list[GenieSpaceSummary])
def list_genie_spaces(
    wc: WorkspaceClient = Depends(get_workspace_client),  # noqa: B008
) -> list[GenieSpaceSummary]:
    try:
        raw = wc._sdk.genie.list_spaces()
    except Exception as exc:
        if _is_permission_denied(exc):
            return []
        raise
    return [
        GenieSpaceSummary(
            id=s.space_id,
            name=s.title,
            owner=getattr(s, "owner_user_name", None),
            updated_at=_parse_iso(getattr(s, "update_time", None)),
        )
        for s in raw.spaces
    ]


@router.get(
    "/{kind}/{source_id:path}/preview",
    response_model=DatabricksSemanticIR,
)
def preview_source(
    kind: Literal["metric_view", "dashboard", "genie_space"],
    source_id: str,
    wc: WorkspaceClient = Depends(get_workspace_client),  # noqa: B008
) -> DatabricksSemanticIR:
    if kind == "metric_view":
        return read_metric_view(wc, fully_qualified_name=source_id)
    if kind == "dashboard":
        return read_dashboard(wc, dashboard_id=source_id)
    return read_genie_space(wc, space_id=source_id)
