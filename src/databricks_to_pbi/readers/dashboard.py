"""Read a Lakeview (AI/BI) dashboard and emit a partial DatabricksSemanticIR."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from databricks_to_pbi.ir import (
    Column,
    DatabricksSemanticIR,
    Measure,
    SourceRef,
    Table,
)
from databricks_to_pbi.workspace import WorkspaceClient

__all__ = ["parse_dashboard_json", "read_dashboard"]


def parse_dashboard_json(body: str) -> dict[str, Any]:
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("dashboard definition is not a JSON object")
    return data


def _hash_slice(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


_IDENTIFIER_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
_SQL_KEYWORDS = {
    "SELECT", "FROM", "WHERE", "GROUP", "BY", "ORDER", "HAVING",
    "AS", "AND", "OR", "NOT", "NULL", "DISTINCT", "ALL",
    "SUM", "AVG", "MIN", "MAX", "COUNT", "CASE", "WHEN", "THEN", "ELSE", "END",
    "DATE_TRUNC", "MONTH", "YEAR", "DAY", "QUARTER",
    "INNER", "LEFT", "RIGHT", "OUTER", "JOIN", "ON", "LIMIT", "OFFSET",
    "FILTER", "OVER", "PARTITION", "BETWEEN", "IN", "IS", "LIKE", "ILIKE",
}


def _infer_columns_from_sql(sql: str, uc_path_prefix: str | None) -> list[Column]:
    out: dict[str, Column] = {}
    for tok in _IDENTIFIER_RE.findall(sql):
        if tok.upper() in _SQL_KEYWORDS or tok.isdigit():
            continue
        # Skip tokens without any lowercase char (likely missed SQL keywords or constants).
        if not any(c.islower() for c in tok):
            continue
        if tok not in out:
            out[tok] = Column(
                name=tok,
                uc_path=f"{uc_path_prefix}.{tok}" if uc_path_prefix else None,
                data_type="STRING",  # unknown at parse time; STRING is permissive default
            )
    return list(out.values())


def _src_for_dataset(dashboard_id: str, ds: dict[str, Any]) -> SourceRef:
    return SourceRef(
        kind="dashboard",
        fully_qualified_name=f"{dashboard_id}::{ds['id']}",
        object_hash=_hash_slice(ds),
        fetched_at=datetime.now(UTC),
    )


def _src_for_widget(dashboard_id: str, widget: dict[str, Any], calc: dict[str, Any]) -> SourceRef:
    return SourceRef(
        kind="dashboard",
        fully_qualified_name=f"{dashboard_id}::{widget['id']}::{calc['name']}",
        object_hash=_hash_slice({"widget": widget["id"], "calc": calc}),
        fetched_at=datetime.now(UTC),
    )


def _build_table_from_dataset(dashboard_id: str, ds: dict[str, Any]) -> Table:
    src = _src_for_dataset(dashboard_id, ds)
    return Table(
        name=ds["name"],
        uc_path=None,
        sql_definition=ds["query"],
        storage_mode="direct_query",
        columns=_infer_columns_from_sql(ds["query"], uc_path_prefix=None),
        description=None,
        source=src,
    )


def _build_measures(dashboard_id: str, widgets: list[dict[str, Any]]) -> list[Measure]:
    measures: list[Measure] = []
    for w in widgets:
        for c in w.get("calculations", []) or []:
            measures.append(
                Measure(
                    name=c["name"],
                    sql_expression=c["expr"],
                    dependencies=[],
                    description=c.get("description"),
                    format_string=c.get("format"),
                    source=_src_for_widget(dashboard_id, w, c),
                )
            )
    return measures


def _fetch_dashboard(client: WorkspaceClient, dashboard_id: str) -> dict[str, Any]:
    """Pull dashboard JSON via the SDK seam.

    NOTE: The exact Lakeview API method may evolve; we use a stable shape via
    the workspace client mock seam. Tests inject ``sdk.lakeview.get(...)`` returning
    an object whose ``.as_dict()`` yields ``{"serialized_dashboard": <json-string>}``.
    """
    resp = client._sdk.lakeview.get(dashboard_id=dashboard_id)
    payload = resp.as_dict()
    serialized = payload.get("serialized_dashboard")
    if not isinstance(serialized, str):
        raise ValueError(f"dashboard {dashboard_id}: serialized_dashboard missing")
    return parse_dashboard_json(serialized)


def read_dashboard(client: WorkspaceClient, *, dashboard_id: str) -> DatabricksSemanticIR:
    parsed = _fetch_dashboard(client, dashboard_id)
    dataset_tables = [
        _build_table_from_dataset(dashboard_id, ds)
        for ds in parsed.get("datasets", []) or []
    ]
    measures = _build_measures(dashboard_id, parsed.get("widgets", []) or [])
    sources = [t.source for t in dataset_tables] + [m.source for m in measures]
    return DatabricksSemanticIR(
        name=parsed.get("name", dashboard_id),
        description=None,
        tables=dataset_tables,
        dimensions=[],
        measures=measures,
        relationships=[],
        genie=None,
        sources=sources,
    )
