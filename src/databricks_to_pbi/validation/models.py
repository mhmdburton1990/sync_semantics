"""Frozen verdict types for result validation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "DimValue",
    "MeasureValidation",
    "ValidationReport",
    "ValidationSummary",
]

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class DimValue(BaseModel):
    model_config = _FROZEN
    key: str | None
    sql: float | None
    dax: float | None
    delta: float | None
    matched: bool


class MeasureValidation(BaseModel):
    model_config = _FROZEN
    name: str
    status: Literal["passed", "failed", "skipped"]
    dim_used: str | None = None
    scalar_sql: float | None = None
    scalar_dax: float | None = None
    scalar_delta: float | None = None
    scalar_matched: bool | None = None
    by_dim: list[DimValue] = []
    skip_reason: str | None = None
    skip_category: str | None = None
    skip_detail: str | None = None
    failed_side: Literal["source_sql", "dax", "setup"] | None = None


class ValidationSummary(BaseModel):
    model_config = _FROZEN
    passed: int = 0
    failed: int = 0
    skipped: int = 0


class ValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())
    model: str
    dataset_id: str
    workspace_id: str
    epsilon: float
    ran_at: datetime
    results: list[MeasureValidation]
    summary: ValidationSummary
