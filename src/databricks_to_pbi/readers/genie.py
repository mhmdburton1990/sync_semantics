"""Read a Genie space and emit a partial DatabricksSemanticIR."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from databricks_to_pbi.ir import (
    DatabricksSemanticIR,
    GenieAnnotation,
    Measure,
    SourceRef,
    Table,
)
from databricks_to_pbi.workspace import WorkspaceClient

__all__ = ["parse_genie_space", "read_genie_space"]


def parse_genie_space(body: str) -> dict[str, Any]:
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("genie space definition is not a JSON object")
    return data


def _hash_slice(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _src_for_metric(space_id: str, m: dict[str, Any]) -> SourceRef:
    return SourceRef(
        kind="genie_space",
        fully_qualified_name=f"{space_id}::{m['name']}",
        object_hash=_hash_slice(m),
        fetched_at=datetime.now(UTC),
    )


def _src_for_table(space_id: str, uc_path: str) -> SourceRef:
    return SourceRef(
        kind="genie_space",
        fully_qualified_name=f"{space_id}::table::{uc_path}",
        object_hash=hashlib.sha256(uc_path.encode("utf-8")).hexdigest()[:16],
        fetched_at=datetime.now(UTC),
    )


def _build_genie_annotation(parsed: dict[str, Any]) -> GenieAnnotation:
    return GenieAnnotation(
        instructions=parsed.get("instructions"),
        sample_questions=list(parsed.get("sample_questions") or []),
        example_question_sqls=[
            (e["question"], e["sql"])
            for e in (parsed.get("example_question_sqls") or [])
        ],
    )


def _build_metric_measures(space_id: str, parsed: dict[str, Any]) -> list[Measure]:
    measures: list[Measure] = []
    for m in parsed.get("metric_definitions", []) or []:
        measures.append(
            Measure(
                name=m["name"],
                sql_expression=m["expr"],
                dependencies=[],
                description=m.get("description"),
                format_string=m.get("format"),
                source=_src_for_metric(space_id, m),
            )
        )
    return measures


def _build_linked_tables(space_id: str, parsed: dict[str, Any]) -> list[Table]:
    tables: list[Table] = []
    for uc_path in parsed.get("linked_tables", []) or []:
        tables.append(
            Table(
                name=uc_path.split(".")[-1],
                uc_path=uc_path,
                sql_definition=None,
                storage_mode="direct_query",
                columns=[],
                description=None,
                source=_src_for_table(space_id, uc_path),
            )
        )
    return tables


def _fetch_genie_space(client: WorkspaceClient, space_id: str) -> dict[str, Any]:
    resp = client._sdk.genie.get_space(space_id=space_id)
    payload = resp.as_dict()
    serialized = payload.get("serialized_space")
    if not isinstance(serialized, str):
        raise ValueError(f"genie space {space_id}: serialized_space missing")
    return parse_genie_space(serialized)


def read_genie_space(client: WorkspaceClient, *, space_id: str) -> DatabricksSemanticIR:
    parsed = _fetch_genie_space(client, space_id)
    measures = _build_metric_measures(space_id, parsed)
    tables = _build_linked_tables(space_id, parsed)
    annotation = _build_genie_annotation(parsed)
    sources = [t.source for t in tables] + [m.source for m in measures]
    return DatabricksSemanticIR(
        name=parsed.get("name", space_id),
        description=None,
        tables=tables,
        dimensions=[],
        measures=measures,
        relationships=[],
        genie=annotation,
        sources=sources,
    )
