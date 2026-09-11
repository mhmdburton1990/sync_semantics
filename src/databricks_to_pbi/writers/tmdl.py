"""Emit a PBIP project folder with TMDL files.

Indentation is meaningful in TMDL: 4 spaces per level.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from databricks_to_pbi.writers.pbi_model import (
    PBIAnnotation,
    PBIColumn,
    PBIMeasure,
    PBIModel,
    PBIParameter,
    PBIRelationship,
    PBITable,
)

__all__ = [
    "render_database_tmdl",
    "render_expressions_tmdl",
    "render_model_tmdl",
    "render_relationships_tmdl",
    "render_table_tmdl",
    "tmdl_parts",
    "write_pbip",
]


_DATATYPE_MAP: dict[str, str] = {
    "STRING": "string",
    "INT": "int64",
    "BIGINT": "int64",
    "DOUBLE": "double",
    "FLOAT": "double",
    "BOOLEAN": "boolean",
    "DATE": "dateTime",
    "TIMESTAMP": "dateTime",
}


def _map_data_type(uc_type: str) -> str:
    head = uc_type.split("(")[0].upper().strip()
    if head.startswith("DECIMAL") or head.startswith("NUMERIC"):
        return "decimal"
    return _DATATYPE_MAP.get(head, "string")


def _i(n: int) -> str:
    return "    " * n


def _render_annotations(annotations: list[PBIAnnotation], indent: int) -> list[str]:
    return [f"{_i(indent)}annotation {a.name} = {a.value}" for a in annotations]


def _render_column(c: PBIColumn) -> list[str]:
    # Descriptions go as /// doc-comments BEFORE the declaration — same
    # convention as table/model. Fabric's TMDL parser rejects the inline
    # `description:` property at every object level.
    lines: list[str] = []
    if c.description:
        lines.extend(f"{_i(1)}/// {line}" for line in c.description.splitlines())
    lines.append(f"{_i(1)}column {c.name}")
    lines.append(f"{_i(2)}dataType: {_map_data_type(c.data_type)}")
    lines.append(f"{_i(2)}sourceColumn: {c.source_column}")
    if c.is_hidden:
        lines.append(f"{_i(2)}isHidden")
    lines.extend(_render_annotations(c.annotations, indent=2))
    lines.append("")
    return lines


def _render_measure(m: PBIMeasure) -> list[str]:
    lines: list[str] = []
    if m.description:
        lines.extend(f"{_i(1)}/// {line}" for line in m.description.splitlines())
    lines.append(f"{_i(1)}measure '{m.name}' = {m.dax}")
    if m.format_string:
        lines.append(f"{_i(2)}formatString: {m.format_string}")
    lines.extend(_render_annotations(m.annotations, indent=2))
    lines.append("")
    return lines


_MEASURES_TABLE_M_EXPR = "let Source = #table({\"_\"}, {{1}}) in Source"


def _build_m_expr_lines(t: PBITable) -> list[str]:
    """Build the M expression as a list of lines for backtick-wrapped output.

    Format matches the canonical Databricks PBI connector pattern that PBI
    Service's data-source detector recognises:

        let
            Source = Databricks.Catalogs(ServerHostname, HTTPPath, [...]),
            Database = Source{[Name="<catalog>", Kind="Database"]}[Data],
            Schema = Database{[Name="<schema>", Kind="Schema"]}[Data],
            Table = Schema{[Name="<table>", Kind="Table"]}[Data]
        in
            Table

    Bare variable names + multi-line form is what the data-source detector
    looks for. Single-line or ``#"_catalog"``-style quoted identifiers fail
    that match and the table shows up as "We could not detect the data
    source information for this table" in PBI Desktop.
    """
    if t.is_measures_table:
        return [_MEASURES_TABLE_M_EXPR]
    if not t.uc_path:
        return [
            'let Source = error "sync_semantics could not resolve a Unity '
            'Catalog path for this table" in Source',
        ]
    catalog, schema, table = t.uc_path.split(".", 2)
    return [
        "let",
        "    Source = Databricks.Catalogs(ServerHostname, HTTPPath, "
        "[Catalog=null, Database=null,",
        '        EnableAutomaticProxyDiscovery=null, EnableQueryResultDownload="1"]),',
        f'    Database = Source{{[Name="{catalog}",Kind="Database"]}}[Data],',
        f'    Schema = Database{{[Name="{schema}",Kind="Schema"]}}[Data],',
        f'    Table = Schema{{[Name="{table}",Kind="Table"]}}[Data]',
        "in",
        "    Table",
    ]


def _render_partition(t: PBITable, params: list[PBIParameter]) -> list[str]:
    """Emit the partition block in the canonical PBI Databricks shape.

    Reference shape (from a working semantic model in the user's workspace):

        partition <table-name> = m
            mode: directQuery
            source = ```
                let
                    Source = Databricks.Catalogs(...)
                    ...
                in
                    Table
                ```

    Partition name == table name (no ``-DBX`` suffix — PBI's data-source
    detection is sensitive to identifier patterns). Source is a triple-
    backtick block; M lines inside live one indentation level below the
    ``source =`` line.
    """
    del params  # M no longer depends on PBIParameter list — connection
    # is wired via the ServerHostname / HTTPPath expressions that
    # `render_expressions_tmdl` emits separately.
    mode_str = (
        "import"
        if t.is_measures_table
        else ("directQuery" if t.storage_mode == "direct_query" else t.storage_mode)
    )
    lines = [f"{_i(1)}partition {_tmdl_name(t.name)} = m"]
    lines.append(f"{_i(2)}mode: {mode_str}")
    m_lines = _build_m_expr_lines(t)
    if len(m_lines) == 1:
        # Single-line M (measures table, error fallback) — inline form
        # is fine; backticks aren't required.
        lines.append(f"{_i(2)}source = {m_lines[0]}")
    else:
        lines.append(f"{_i(2)}source = ```")
        for ml in m_lines:
            lines.append(f"{_i(3)}{ml}")
        lines.append(f"{_i(3)}```")
    lines.append("")
    return lines


def _doc_comment_lines(text: str) -> list[str]:
    """TMDL renders object-level descriptions as `///` doc-comments BEFORE
    the object declaration. `description:` as a property is rejected at the
    table/model level by the Fabric semanticModels API parser.
    """
    return [f"/// {line}" for line in text.splitlines()]


def render_table_tmdl(t: PBITable, params: list[PBIParameter] | None = None) -> str:
    params = params or []
    lines: list[str] = []
    if t.description:
        lines.extend(_doc_comment_lines(t.description))
    lines.append(f"table {_tmdl_name(t.name)}")
    lines.extend(_render_annotations(t.annotations, indent=1))
    lines.append("")
    for c in t.columns:
        lines.extend(_render_column(c))
    for m in t.measures:
        lines.extend(_render_measure(m))
    lines.extend(_render_partition(t, params))
    return "\n".join(lines) + "\n"


def render_expressions_tmdl(params: list[PBIParameter]) -> str:
    """Render model-level M parameters as TMDL `expression` blocks.

    Each block carries the IsParameterQuery meta so Power BI Desktop's
    "Edit Parameters" dialog picks them up on .pbip open. A parameter with no
    value (``default_value is None``) is emitted as ``null`` — a required
    parameter with no saved value is what makes Desktop prompt the user for it
    on open. A quoted string (even ``""``) counts as a saved value and would
    suppress the prompt.
    """
    if not params:
        return ""
    out: list[str] = []
    for p in params:
        if p.default_value is None:
            value_expr = "null"
        else:
            # M string literal escaping: double the quotes inside.
            value_expr = '"' + p.default_value.replace('"', '""') + '"'
        if p.description:
            out.extend(f"/// {line}" for line in p.description.splitlines())
        out.append(
            f"expression {p.name} = {value_expr} meta "
            f'[IsParameterQuery=true, Type="{p.pbi_type}", '
            f"IsParameterQueryRequired=true]"
        )
        out.append("")
    return "\n".join(out) + "\n"


# TMDL expresses cardinality as two ends (fromCardinality / toCardinality) with
# lowercase `one` / `many` — there is no single `cardinality` property (Power BI
# Desktop rejects the project if one is emitted). The parser defaults are
# fromCardinality=many, toCardinality=one (i.e. many-to-one), so only non-default
# ends are written.
_CARDINALITY_ENDS = {
    "one_to_many": ("one", "many"),
    "many_to_one": ("many", "one"),
    "one_to_one": ("one", "one"),
    "many_to_many": ("many", "many"),
}

_CROSS_FILTER_TO_TMDL = {
    "single": "oneDirection",
    "both": "bothDirections",
    "automatic": "automatic",
}


_NAME_NEEDS_QUOTING_RE = re.compile(r"[.=:'\s]")


def _tmdl_name(name: str) -> str:
    """Quote a TMDL identifier only when it contains characters that require it
    (dot, equals, colon, single-quote, or whitespace). Single quotes in the
    name itself are escaped by doubling.
    """
    if _NAME_NEEDS_QUOTING_RE.search(name):
        return "'" + name.replace("'", "''") + "'"
    return name


def render_relationships_tmdl(rels: list[PBIRelationship]) -> str:
    """TMDL relationships use the combined ``fromColumn: Table.Column`` form
    (quoting either part only when its identifier needs it). The separate
    ``fromTable`` / ``toTable`` properties are not in the grammar.
    """
    out: list[str] = []
    for r in rels:
        name = f"{r.from_table}_{','.join(r.from_columns)}_to_{r.to_table}_{','.join(r.to_columns)}"
        from_ref = f"{_tmdl_name(r.from_table)}.{_tmdl_name(r.from_columns[0])}"
        to_ref = f"{_tmdl_name(r.to_table)}.{_tmdl_name(r.to_columns[0])}"
        out.append(f"relationship {_tmdl_name(name)}")
        out.append(f"{_i(1)}fromColumn: {from_ref}")
        out.append(f"{_i(1)}toColumn: {to_ref}")
        from_card, to_card = _CARDINALITY_ENDS.get(r.cardinality, ("many", "one"))
        if from_card != "many":  # many is the fromCardinality default
            out.append(f"{_i(1)}fromCardinality: {from_card}")
        if to_card != "one":  # one is the toCardinality default
            out.append(f"{_i(1)}toCardinality: {to_card}")
        cross = _CROSS_FILTER_TO_TMDL.get(r.cross_filter, r.cross_filter)
        if cross and cross != "oneDirection":  # oneDirection is the default
            out.append(f"{_i(1)}crossFilteringBehavior: {cross}")
        if not r.is_active:
            out.append(f"{_i(1)}isActive: false")
        out.append("")
    return "\n".join(out) + "\n" if out else ""


def render_model_tmdl(model: PBIModel) -> str:
    """Emit model header + perf hints + the `ref table X` ordering declarations.

    Perf hints match the canonical PBI Databricks-published model:
    20-connection pool, 20-way parallelism on refresh and query. Without
    these PBI Service falls back to conservative defaults that can hurt
    query latency at scale.

    The `ref table X` block sets the deterministic table ordering across
    TOM <-> TMDL roundtrips (the Fabric serializer expects them on parity).
    """
    lines: list[str] = []
    if model.description:
        lines.extend(_doc_comment_lines(model.description))
    lines.append(f"model {model.name}")
    lines.append(f"{_i(1)}culture: en-US")
    lines.append(f"{_i(1)}defaultPowerBIDataSourceVersion: powerBI_V3")
    lines.append(f"{_i(1)}dataSourceDefaultMaxConnections: 20")
    lines.append(f"{_i(1)}maxParallelismPerRefresh: 20")
    lines.append(f"{_i(1)}maxParallelismPerQuery: 20")
    lines.extend(_render_annotations(model.annotations, indent=1))
    lines.append("")
    for t in model.tables:
        lines.append(f"ref table {_tmdl_name(t.name)}")
    return "\n".join(lines) + "\n"


def render_database_tmdl(model: PBIModel) -> str:
    """Fabric semanticModels generated by PBI use a bare `database` keyword
    (no name) and compatibility level 1600 (TMDL serializer default).
    """
    return f"database\n{_i(1)}compatibilityLevel: 1600\n"


def tmdl_parts(model: PBIModel) -> dict[str, bytes]:
    """Return the SemanticModel TMDL parts as an in-memory ``{path: bytes}`` map.

    Paths are relative to the SemanticModel root (no leading ``definition/``
    container) — same layout the Fabric REST API expects, and the same
    layout ``write_pbip`` writes to disk under ``<model>.SemanticModel/``.
    """
    parts: dict[str, bytes] = {}
    for t in model.tables:
        parts[f"definition/tables/{t.name}.tmdl"] = render_table_tmdl(
            t, model.parameters,
        ).encode("utf-8")
    parts["definition/model.tmdl"] = render_model_tmdl(model).encode("utf-8")
    parts["definition/database.tmdl"] = render_database_tmdl(model).encode("utf-8")
    parts["definition/relationships.tmdl"] = render_relationships_tmdl(
        model.relationships,
    ).encode("utf-8")
    expressions_tmdl = render_expressions_tmdl(model.parameters)
    if expressions_tmdl:
        parts["definition/expressions.tmdl"] = expressions_tmdl.encode("utf-8")
    return parts


# --- PBIP packaging metadata ------------------------------------------------
#
# The SemanticModel TMDL parts (tmdl_parts) are the same ones the Fabric REST
# publish sends and are already validated. Opening a PBIP in Power BI Desktop
# additionally needs the packaging files below: a semantic-model definition
# (definition.pbism), a report (enhanced-PBIR definition folder), git/platform
# metadata (.platform), and a project entry point (<name>.pbip). Schema-version
# strings track the public microsoft/json-schemas repo and may need bumping to
# match a specific Desktop version.

_SCHEMA_ROOT = "https://developer.microsoft.com/json-schemas/fabric"
_PBIP_SCHEMA = f"{_SCHEMA_ROOT}/pbip/pbipProperties/1.0.0/schema.json"
_PBISM_SCHEMA = f"{_SCHEMA_ROOT}/item/semanticModel/definitionProperties/1.0.0/schema.json"
_PBIR_SCHEMA = f"{_SCHEMA_ROOT}/item/report/definitionProperties/2.0.0/schema.json"
_REPORT_SCHEMA = f"{_SCHEMA_ROOT}/item/report/definition/report/3.3.0/schema.json"
_VERSION_META_SCHEMA = (
    f"{_SCHEMA_ROOT}/item/report/definition/versionMetadata/1.0.0/schema.json"
)
_PAGES_META_SCHEMA = (
    f"{_SCHEMA_ROOT}/item/report/definition/pagesMetadata/1.0.0/schema.json"
)
_PAGE_SCHEMA = f"{_SCHEMA_ROOT}/item/report/definition/page/2.1.0/schema.json"
_PLATFORM_SCHEMA = f"{_SCHEMA_ROOT}/gitIntegration/platformProperties/2.0.0/schema.json"

# Fixed namespace so derived UUIDs / page ids are deterministic across runs
# (a fresh random id every write would churn the .platform files in git).
_DBX2PBI_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")


def _stable_uuid(model_name: str, item: str) -> str:
    return str(uuid.uuid5(_DBX2PBI_NS, f"{model_name}/{item}"))


def _stable_page_id(model_name: str) -> str:
    # Enhanced-PBIR page ids are short lowercase-hex strings.
    return uuid.uuid5(_DBX2PBI_NS, f"{model_name}/page1").hex[:20]


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def _platform(model_name: str, item_type: str) -> dict[str, Any]:
    return {
        "$schema": _PLATFORM_SCHEMA,
        "metadata": {"type": item_type, "displayName": model_name},
        "config": {"version": "2.0", "logicalId": _stable_uuid(model_name, item_type)},
    }


def _write_report_definition(report_dir: Path, model: PBIModel) -> None:
    """Write the enhanced-PBIR report body: one blank page bound to the model."""
    (report_dir / "definition.pbir").write_text(
        json.dumps(
            {
                "$schema": _PBIR_SCHEMA,
                "version": "4.0",
                "datasetReference": {
                    "byPath": {"path": f"../{model.name}.SemanticModel"},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    rdef = report_dir / "definition"
    _write_json(
        rdef / "report.json",
        {
            "$schema": _REPORT_SCHEMA,
            "themeCollection": {
                "baseTheme": {
                    "name": "CY26SU02",
                    "reportVersionAtImport": {
                        "page": "2.1.0",
                        "report": "3.3.0",
                        "visual": "2.9.0",
                    },
                    "type": "SharedResources",
                },
            },
        },
    )
    _write_json(rdef / "version.json", {"$schema": _VERSION_META_SCHEMA, "version": "2.0.0"})
    page_id = _stable_page_id(model.name)
    _write_json(
        rdef / "pages" / "pages.json",
        {"$schema": _PAGES_META_SCHEMA, "pageOrder": [page_id], "activePageName": page_id},
    )
    _write_json(
        rdef / "pages" / page_id / "page.json",
        {
            "$schema": _PAGE_SCHEMA,
            "name": page_id,
            "displayName": "Page 1",
            "displayOption": "FitToPage",
            "height": 720,
            "width": 1280,
        },
    )


def write_pbip(model: PBIModel, *, output_dir: Path) -> Path:
    sem_dir = output_dir / f"{model.name}.SemanticModel"
    for rel_path, content in tmdl_parts(model).items():
        out = sem_dir / rel_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
    # Semantic-model definition + git metadata alongside the TMDL definition/.
    _write_json(
        sem_dir / "definition.pbism",
        {"$schema": _PBISM_SCHEMA, "version": "4.0", "settings": {}},
    )
    _write_json(sem_dir / ".platform", _platform(model.name, "SemanticModel"))

    report_dir = output_dir / f"{model.name}.Report"
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_report_definition(report_dir, model)
    _write_json(report_dir / ".platform", _platform(model.name, "Report"))

    # Project entry point the user opens in Power BI Desktop.
    _write_json(
        output_dir / f"{model.name}.pbip",
        {
            "$schema": _PBIP_SCHEMA,
            "version": "1.0",
            "artifacts": [{"report": {"path": f"{model.name}.Report"}}],
        },
    )
    return output_dir
