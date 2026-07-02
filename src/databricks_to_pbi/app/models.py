"""Request/response Pydantic schemas for the App API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from databricks_to_pbi.reporting.report import SyncReport
from databricks_to_pbi.validation.models import (
    MeasureValidation,
    ValidationReport,
    ValidationSummary,
)

__all__ = [
    "CacheStatus",
    "CatalogSummary",
    "DashboardSummary",
    "DimensionsRequest",
    "FabricWorkspaceSummary",
    "GenieSpaceSummary",
    "HistoryEntry",
    "MetricViewSummary",
    "RunDetail",
    "SchemaSummary",
    "SourceKind",
    "StartValidationResponse",
    "SyncRequest",
    "SyncSourceRef",
    "SyncTarget",
    "ValidateRequest",
    "ValidationDimensionsResponse",
    "ValidationJobStatus",
    "WarehouseSummary",
]


SourceKind = Literal["metric_view", "dashboard", "genie_space"]


class MetricViewSummary(BaseModel):
    fully_qualified_name: str
    owner: str | None = None
    updated_at: datetime | None = None
    description: str | None = None


class DashboardSummary(BaseModel):
    id: str
    name: str
    owner: str | None = None
    updated_at: datetime | None = None


class GenieSpaceSummary(BaseModel):
    id: str
    name: str
    owner: str | None = None
    updated_at: datetime | None = None


class CatalogSummary(BaseModel):
    name: str


class SchemaSummary(BaseModel):
    name: str


class FabricWorkspaceSummary(BaseModel):
    """A Power BI workspace the Fabric SP can publish to.

    is_dedicated_capacity is True for Premium/Fabric capacity — XMLA writes
    only work against those, not Pro workspaces.
    """

    id: str
    name: str
    is_dedicated_capacity: bool = False
    capacity_id: str | None = None


class SyncSourceRef(BaseModel):
    kind: SourceKind
    id: str


class SyncTarget(BaseModel):
    kind: Literal["pbip", "pbit", "xmla"]
    target_id: str


class SyncRequest(BaseModel):
    sources: list[SyncSourceRef]
    target: SyncTarget
    model_name: str
    description: str | None = None
    xmla_merge: bool = False
    # Optional per-table storage-mode overrides keyed by table name.
    # Values: "import" | "direct_query" | "dual". Tables not in the map
    # use the reader's default (typically directQuery).
    storage_modes: dict[str, str] = {}
    # Measure names the user de-selected on Preview; dropped from the model on Apply.
    exclude_measures: list[str] = []


class ValidateRequest(BaseModel):
    sources: list[SyncSourceRef]
    model_name: str
    dataset_id: str
    workspace_id: str
    dim_sql_ref: str | None = None
    timeframe: Literal["all", "day", "week", "month", "quarter", "year"] = "all"
    date_table: str | None = None
    date_column: str | None = None
    exclude_measures: list[str] = []
    run_id: str | None = None


class DimensionsRequest(BaseModel):
    sources: list[SyncSourceRef]
    model_name: str


class DateColumnRef(BaseModel):
    table: str
    column: str


class ValidationDimensionsResponse(BaseModel):
    dimensions: list[str]
    has_date_column: bool
    date_columns: list[DateColumnRef] = []


class HistoryEntry(BaseModel):
    run_id: str
    created_at: datetime
    model_name: str | None = None
    state: str = "unknown"
    summary_created: int = 0
    summary_updated: int = 0
    summary_needs_manual_review: int = 0
    validation_status: str = "not_run"
    val_passed: int = 0
    val_failed: int = 0
    val_skipped: int = 0


class RunDetail(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    run_id: str
    created_at: datetime
    run_by: str | None = None
    model_name: str | None = None
    delivery: str
    state: str
    validation_status: str
    report: SyncReport
    validation: ValidationReport | None = None
    sources: list[SyncSourceRef] = []
    dataset_id: str | None = None
    workspace_id: str | None = None
    val_dimension: str | None = None
    val_timeframe: str | None = None


class CacheStatus(BaseModel):
    entries: int
    bytes: int
    path: str


class WarehouseSummary(BaseModel):
    id: str
    name: str
    state: str | None = None       # RUNNING, STOPPED, STARTING, ...
    size: str | None = None         # 2X-Small, ..., 4X-Large
    serverless: bool | None = None


class StartValidationResponse(BaseModel):
    job_id: str
    total: int


class ValidationJobStatus(BaseModel):
    status: Literal["pending", "running", "done", "error", "canceled"]
    total: int
    results: list[MeasureValidation]
    summary: ValidationSummary
    error: str | None = None
    current: str | None = None
