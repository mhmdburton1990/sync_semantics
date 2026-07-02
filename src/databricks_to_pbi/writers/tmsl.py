"""Serialize a PBIModel to TMSL (Tabular Model Scripting Language) JSON.

The output is a single dict suitable for an XMLA `Execute` command, structured
as a `createOrReplace` against the model's database.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from databricks_to_pbi.writers.pbi_model import (
    PBIAnnotation,
    PBIColumn,
    PBIMeasure,
    PBIModel,
    PBIRelationship,
    PBITable,
)

__all__ = ["render_tmsl", "write_bim"]


_DATATYPE_MAP = {
    "STRING": "string",
    "INT": "int64",
    "BIGINT": "int64",
    "DOUBLE": "double",
    "FLOAT": "double",
    "BOOLEAN": "boolean",
    "DATE": "dateTime",
    "TIMESTAMP": "dateTime",
}


_CARDINALITY_MAP = {
    "one_to_many":  ("one",  "many"),
    "many_to_one":  ("many", "one"),
    "one_to_one":   ("one",  "one"),
    "many_to_many": ("many", "many"),
}


def _map_data_type(uc_type: str) -> str:
    head = uc_type.split("(")[0].upper().strip()
    if head.startswith("DECIMAL") or head.startswith("NUMERIC"):
        return "decimal"
    return _DATATYPE_MAP.get(head, "string")


def _annos(items: list[PBIAnnotation]) -> list[dict[str, Any]]:
    return [{"name": a.name, "value": a.value} for a in items]


def _column(c: PBIColumn) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": c.name,
        "dataType": _map_data_type(c.data_type),
        "sourceColumn": c.source_column,
    }
    if c.description:
        out["description"] = c.description
    if c.annotations:
        out["annotations"] = _annos(c.annotations)
    return out


def _measure(m: PBIMeasure) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": m.name,
        "expression": m.dax,
    }
    if m.format_string:
        out["formatString"] = m.format_string
    if m.description:
        out["description"] = m.description
    if m.annotations:
        out["annotations"] = _annos(m.annotations)
    return out


def _partition(t: PBITable) -> dict[str, Any]:
    if t.uc_path:
        catalog, schema, table_name = t.uc_path.split(".", 2)
        m_expr = (
            f'let Source = Databricks.Catalogs(null, null, []), '
            f'#"{catalog}" = Source{{[Name="{catalog}"]}}[Data], '
            f'#"{schema}" = #"{catalog}"{{[Name="{schema}"]}}[Data], '
            f'#"{table_name}" = #"{schema}"{{[Name="{table_name}"]}}[Data] '
            f'in #"{table_name}"'
        )
    else:
        sql = (t.sql_definition or "").replace('"', '""')
        m_expr = f'let Source = Databricks.Query(null, null, "{sql}", []) in Source'
    return {
        "name": f"{t.name}-DBX",
        "mode": "directQuery" if t.storage_mode == "direct_query" else t.storage_mode,
        "source": {"type": "m", "expression": m_expr},
    }


def _table(t: PBITable) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": t.name,
        "columns": [_column(c) for c in t.columns],
        "partitions": [_partition(t)],
    }
    if t.measures:
        out["measures"] = [_measure(m) for m in t.measures]
    if t.description:
        out["description"] = t.description
    if t.annotations:
        out["annotations"] = _annos(t.annotations)
    return out


def _relationship(r: PBIRelationship) -> dict[str, Any]:
    from_card, to_card = _CARDINALITY_MAP[r.cardinality]
    from_cols = ",".join(r.from_columns)
    to_cols = ",".join(r.to_columns)
    cross_filter = "oneDirection" if r.cross_filter == "single" else "bothDirections"
    return {
        "name": f"{r.from_table}_{from_cols}_to_{r.to_table}_{to_cols}",
        "fromTable": r.from_table,
        "fromColumn": r.from_columns[0],
        "fromCardinality": from_card,
        "toTable": r.to_table,
        "toColumn": r.to_columns[0],
        "toCardinality": to_card,
        "crossFilteringBehavior": cross_filter,
        "isActive": r.is_active,
    }


def render_tmsl(model: PBIModel) -> dict[str, Any]:
    db: dict[str, Any] = {
        "name": model.name,
        "compatibilityLevel": 1567,
        "model": {
            "culture": "en-US",
            "tables": [_table(t) for t in model.tables],
            "relationships": [_relationship(r) for r in model.relationships],
        },
    }
    if model.description:
        db["description"] = model.description
    if model.annotations:
        db["model"]["annotations"] = _annos(model.annotations)
    return {"createOrReplace": {"object": {"database": model.name}, "database": db}}


def write_bim(model: PBIModel, *, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(render_tmsl(model), indent=2), encoding="utf-8")
    return output_path
