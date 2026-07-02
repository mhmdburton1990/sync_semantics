"""GET /api/warehouses — list SQL warehouses the OBO user can access."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from databricks_to_pbi.app.auth import current_obo_token
from databricks_to_pbi.app.deps import get_sdk_client
from databricks_to_pbi.app.models import WarehouseSummary

__all__ = ["router"]


router = APIRouter(
    prefix="/api/warehouses",
    tags=["warehouses"],
    dependencies=[Depends(current_obo_token)],
)


def _serverless(w: Any) -> bool | None:
    # Different SDK versions expose this differently.
    if hasattr(w, "enable_serverless_compute"):
        return bool(w.enable_serverless_compute)
    if hasattr(w, "warehouse_type"):
        wt = str(getattr(w, "warehouse_type", "") or "").upper()
        if wt:
            return "SERVERLESS" in wt or "PRO" in wt
    return None


@router.get("", response_model=list[WarehouseSummary])
def list_warehouses(
    sdk: Any = Depends(get_sdk_client),  # noqa: B008
) -> list[WarehouseSummary]:
    raw = list(sdk.warehouses.list())
    return [
        WarehouseSummary(
            id=str(w.id),
            name=str(w.name),
            state=getattr(getattr(w, "state", None), "value", None)
            or (str(w.state) if getattr(w, "state", None) else None),
            size=getattr(w, "cluster_size", None),
            serverless=_serverless(w),
        )
        for w in raw
    ]
