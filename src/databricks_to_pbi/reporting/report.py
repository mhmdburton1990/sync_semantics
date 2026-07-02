"""SyncReport model and JSON renderer."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from databricks_to_pbi.ir import SourceRef
from databricks_to_pbi.sync.manifest import TargetDescriptor
from databricks_to_pbi.validation.models import ValidationReport

__all__ = [
    "ErrorEntry",
    "ObjectOutcome",
    "SummaryStats",
    "SyncReport",
    "TableInfo",
    "write_json",
]


class TableInfo(BaseModel):
    """Per-table metadata the Preview UI uses to render the storage-mode
    picker. ``storage_mode`` reflects the value that will be published if
    no override is supplied at apply time.
    """

    name: str
    storage_mode: Literal["import", "direct_query", "dual"]
    uc_path: str | None = None
    column_count: int = 0
    is_measures_table: bool = False


class ObjectOutcome(BaseModel):
    object_kind: Literal["table", "measure", "relationship", "dimension"]
    name: str
    action: Literal["created", "updated", "unchanged", "deleted", "renamed", "skipped"]
    source_refs: list[SourceRef]
    translation_method: Literal["rule", "cache", "llm", "placeholder", "n/a"] | None
    warnings: list[str]
    needs_manual_review: bool
    diff_preview: str | None
    # Before/after for measures so the UI can render SQL → DAX side-by-side.
    sql_expression: str | None = None  # raw Databricks SQL the engine consumed
    dax: str | None = None              # translated DAX (or // MANUAL placeholder)


class SummaryStats(BaseModel):
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    renamed: int = 0
    skipped: int = 0
    needs_manual_review: int = 0


class ErrorEntry(BaseModel):
    code: str
    message: str
    object: str | None = None
    recoverable: bool = True


class SyncReport(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime
    target: TargetDescriptor
    target_model_name: str | None = None
    mode: Literal["preview", "apply"]
    delivery: Literal["xmla_create", "xmla_merge", "pbip", "pbit"]
    summary: SummaryStats
    outcomes: list[ObjectOutcome]
    errors: list[ErrorEntry]
    fatal_error: ErrorEntry | None
    source_inventory: list[SourceRef]
    tables: list[TableInfo] = []
    published_dataset_id: str | None = None
    validation: ValidationReport | None = None


def write_json(report: SyncReport, *, root: Path) -> Path:
    path = root / "reports" / f"{report.run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path
