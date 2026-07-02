"""App/CLI-facing glue that assembles a ValidationReport from engine outputs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import requests

from databricks_to_pbi.auth.fabric import (
    POWER_BI_SCOPE,
    FabricAuth,
    load_credentials_from_env,
)
from databricks_to_pbi.ir import DatabricksSemanticIR
from databricks_to_pbi.validation.dax_query import DaxQueryClient
from databricks_to_pbi.validation.dimension import GroupByDim, WarehouseLike
from databricks_to_pbi.validation.models import ValidationReport
from databricks_to_pbi.validation.timeframe import Timeframe, compute_window
from databricks_to_pbi.validation.validate import (
    DaxClientLike,
    ValidationInputs,
    validate_model,
)

__all__ = ["ValidationContext", "default_dax_factory", "run_validation"]


@dataclass(frozen=True, slots=True)
class ValidationContext:
    ir: DatabricksSemanticIR
    methods: dict[str, str]
    wc: WarehouseLike
    dataset_id: str
    workspace_id: str
    model: str
    ran_at: datetime
    dax_client_factory: Callable[[str], DaxClientLike]
    dim_override: GroupByDim | None = None
    timeframe: Timeframe = "all"
    date_override: tuple[str, str] | None = None
    run_id: str | None = None
    # (catalog, schema) whose run_history table the verdict is MERGEd into —
    # must match where Apply wrote the row (both derive from the same sources).
    history_namespace: tuple[str, str] | None = None


def default_dax_factory(
    *, workspace_id: str, dataset_id: str,
) -> Callable[[str], DaxClientLike]:
    """Build DaxQueryClients sharing one Power-BI-scoped auth + session."""
    auth = FabricAuth(credentials=load_credentials_from_env(), scope=POWER_BI_SCOPE)
    session = requests.Session()

    def factory(_measure: str) -> DaxClientLike:
        return DaxQueryClient(
            workspace_id=workspace_id, dataset_id=dataset_id,
            auth=auth, session=session,
        )

    return factory


def run_validation(ctx: ValidationContext) -> ValidationReport:
    window = compute_window(ctx.wc, ctx.ir, ctx.timeframe, ctx.date_override)
    return validate_model(
        ValidationInputs(
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
    )
