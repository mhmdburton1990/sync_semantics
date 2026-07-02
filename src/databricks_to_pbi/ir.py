"""Frozen Pydantic IR for Databricks-side semantics."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "Column",
    "DatabricksSemanticIR",
    "Dimension",
    "GenieAnnotation",
    "Measure",
    "Relationship",
    "SourceRef",
    "Table",
    "WindowClause",
]


_FROZEN = ConfigDict(frozen=True, extra="forbid")


class SourceRef(BaseModel):
    model_config = _FROZEN
    kind: Literal["metric_view", "dashboard", "genie_space"]
    fully_qualified_name: str
    object_hash: str
    fetched_at: datetime


class Column(BaseModel):
    model_config = _FROZEN
    # `name` is the column identifier used by the PBI model: lowercase
    # always, so it matches across the TMDL ``name:`` property,
    # relationship fromColumn/toColumn references, and the metric view's
    # YAML join conditions (which are lowercase).
    name: str
    # `source_column` is the column name as Databricks stores it (the
    # casing returned by DESCRIBE TABLE). The PBI Databricks connector
    # uses this when generating DirectQuery SQL, so it must match the
    # actual UC casing — otherwise Databricks raises
    # `column 't0.l_orderkey' of the table wasn't found` because the
    # underlying column is `L_ORDERKEY`. Defaults to ``name`` for
    # backwards compatibility with synthetic/test fixtures.
    source_column: str = ""
    uc_path: str | None
    data_type: str
    description: str | None = None
    is_key: bool = False
    role: Literal["dimension", "attribute", "fact"] = "attribute"


class Dimension(BaseModel):
    model_config = _FROZEN
    name: str
    expression: str
    underlying_columns: list[str]
    description: str | None
    hierarchy: list[str] | None


class WindowClause(BaseModel):
    model_config = _FROZEN
    order: str          # dimension name the window is ordered by, e.g. "order_date"
    range: str          # raw range string: "trailing 7 day inclusive" | "cumulative" | "current"


class Measure(BaseModel):
    model_config = _FROZEN
    name: str
    sql_expression: str
    dependencies: list[str]
    description: str | None
    format_string: str | None
    source: SourceRef
    window: list[WindowClause] | None = None


class Relationship(BaseModel):
    model_config = _FROZEN
    from_table: str
    from_columns: list[str]
    to_table: str
    to_columns: list[str]
    cardinality: Literal["one_to_many", "many_to_one", "one_to_one", "many_to_many"]
    is_active: bool = True
    cross_filter: Literal["single", "both"] = "single"


class Table(BaseModel):
    model_config = _FROZEN
    name: str
    uc_path: str | None
    sql_definition: str | None
    storage_mode: Literal["direct_query", "dual", "import"] = "direct_query"
    columns: list[Column]
    description: str | None
    source: SourceRef


class GenieAnnotation(BaseModel):
    model_config = _FROZEN
    instructions: str | None = None
    sample_questions: list[str] = []
    example_question_sqls: list[tuple[str, str]] = []


class DatabricksSemanticIR(BaseModel):
    model_config = _FROZEN
    name: str
    description: str | None
    tables: list[Table]
    dimensions: list[Dimension]
    measures: list[Measure]
    relationships: list[Relationship]
    genie: GenieAnnotation | None = None
    sources: list[SourceRef]
