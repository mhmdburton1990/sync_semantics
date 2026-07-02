"""FastAPI dependency factories — wrap engine entry points so they're overridable."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, cast

from databricks.sdk import WorkspaceClient as SdkWorkspaceClient
from fastapi import Depends, Header

from databricks_to_pbi.app.auth import current_obo_token
from databricks_to_pbi.app.errors import AppError
from databricks_to_pbi.history.store import RunHistoryStore, history_table_name
from databricks_to_pbi.workspace import WorkspaceClient

log = logging.getLogger(__name__)

__all__ = [
    "get_current_user_email",
    "get_history_store",
    "get_sdk_client",
    "get_uc_volume_root",
    "get_workspace_client",
    "require_history_catalog",
    "require_history_schema",
    "require_warehouse_id",
]


WAREHOUSE_HEADER = "X-Warehouse-Id"
# Run history lives in the catalog+schema the user is working in (same namespace
# as the migrated source). The frontend sends both on history calls.
HISTORY_CATALOG_HEADER = "X-History-Catalog"
HISTORY_SCHEMA_HEADER = "X-History-Schema"


def _resolve_warehouse_id(header_value: str | None) -> str:
    """Pick warehouse from the request header first, then env var. Empty if neither."""
    if header_value:
        return header_value
    return os.environ.get("DBX2PBI_WAREHOUSE_ID") or ""


def _make_sdk(token: str) -> SdkWorkspaceClient:
    """Build a Databricks SDK client using the OBO token.

    Inside a Databricks App the SP credentials (DATABRICKS_CLIENT_ID /
    DATABRICKS_CLIENT_SECRET) are auto-injected. If we just pass `token=...`
    the SDK config rejects "more than one authorization method configured".
    Force PAT auth and pass host explicitly (DATABRICKS_HOST in Apps is
    bare hostname, no scheme).
    """
    host = os.environ.get("DATABRICKS_HOST", "")
    if host and not host.startswith("http"):
        host = f"https://{host}"
    if host:
        return SdkWorkspaceClient(host=host, token=token, auth_type="pat")
    # Local dev or test — let the SDK resolve host from profile/config
    return SdkWorkspaceClient(token=token, auth_type="pat")


def get_current_user_email(
    token: str = Depends(current_obo_token),
) -> str | None:
    """Best-effort OBO user email for run-history attribution. Never raises."""
    try:
        return _make_sdk(token).current_user.me().user_name
    except Exception as exc:
        log.debug("get_current_user_email failed: %s", exc)
        return None


def get_sdk_client(
    token: str = Depends(current_obo_token),
) -> Any:
    """Raw Databricks SDK client. For routes that don't execute SQL."""
    return _make_sdk(token)


def get_workspace_client(
    token: str = Depends(current_obo_token),
    x_warehouse_id: str | None = Header(None, alias=WAREHOUSE_HEADER),
) -> WorkspaceClient:
    """Engine WorkspaceClient. warehouse_id is whatever the request provided
    (header > env > empty). Routes that need a warehouse for SQL should pair
    this with `Depends(require_warehouse_id)` to get a clear upfront 400."""
    warehouse_id = _resolve_warehouse_id(x_warehouse_id)
    sdk = _make_sdk(token)
    return WorkspaceClient(sdk_client=cast(Any, sdk), warehouse_id=warehouse_id)


def require_warehouse_id(
    x_warehouse_id: str | None = Header(None, alias=WAREHOUSE_HEADER),
) -> str:
    """Guard dependency for routes that cannot work without a warehouse."""
    warehouse_id = _resolve_warehouse_id(x_warehouse_id)
    if not warehouse_id:
        raise AppError(
            code="missing_warehouse",
            message="No SQL warehouse selected.",
            suggestion=(
                "Pick a warehouse from the dropdown in the top nav, or pass "
                f"the {WAREHOUSE_HEADER} request header."
            ),
            status_code=400,
        )
    return warehouse_id


def require_history_catalog(
    x_history_catalog: str | None = Header(None, alias=HISTORY_CATALOG_HEADER),
) -> str:
    """Catalog whose run_history table the History tab reads. Required because
    history is scoped to the namespace the user is working in."""
    if not x_history_catalog:
        raise AppError(
            code="missing_catalog",
            message="No catalog selected.",
            suggestion=(
                "Pick a source catalog/schema first (it scopes run history), or "
                f"pass the {HISTORY_CATALOG_HEADER} request header."
            ),
            status_code=400,
        )
    return x_history_catalog


def require_history_schema(
    x_history_schema: str | None = Header(None, alias=HISTORY_SCHEMA_HEADER),
) -> str:
    """Schema whose run_history table the History tab reads — history lives in
    the same catalog AND schema as the migrated source."""
    if not x_history_schema:
        raise AppError(
            code="missing_schema",
            message="No schema selected.",
            suggestion=(
                "Pick a source schema first (it scopes run history), or pass "
                f"the {HISTORY_SCHEMA_HEADER} request header."
            ),
            status_code=400,
        )
    return x_history_schema


def get_history_store(
    wc: WorkspaceClient = Depends(get_workspace_client),  # noqa: B008
    _warehouse_id: str = Depends(require_warehouse_id),
    catalog: str = Depends(require_history_catalog),
    schema: str = Depends(require_history_schema),
) -> RunHistoryStore:
    return RunHistoryStore(wc=wc, table=history_table_name(catalog, schema))


def get_uc_volume_root() -> Path:
    raw = os.environ.get("DBX2PBI_UC_VOLUME")
    if not raw:
        raise AppError(
            code="missing_uc_volume",
            message="DBX2PBI_UC_VOLUME env var is not set",
            suggestion="Configure the App's app.yaml with a UC volume path.",
            status_code=500,
        )
    return Path(raw)
