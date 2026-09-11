"""Target IR mirroring TMDL's structure. All writers serialize from PBIModel."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from pydantic import BaseModel

from databricks_to_pbi.ir import DatabricksSemanticIR, SourceRef, Table

__all__ = [
    "PBIAnnotation",
    "PBIColumn",
    "PBIMeasure",
    "PBIModel",
    "PBIParameter",
    "PBIRelationship",
    "PBITable",
    "build_pbi_model",
]


class PBIAnnotation(BaseModel):
    name: str
    value: str


class PBIColumn(BaseModel):
    name: str
    data_type: str
    source_column: str
    description: str | None = None
    is_hidden: bool = False
    annotations: list[PBIAnnotation] = []


class PBIMeasure(BaseModel):
    name: str
    dax: str
    description: str | None = None
    format_string: str | None = None
    annotations: list[PBIAnnotation] = []


class PBITable(BaseModel):
    name: str
    storage_mode: Literal["direct_query", "dual", "import"]
    uc_path: str | None
    sql_definition: str | None
    columns: list[PBIColumn]
    measures: list[PBIMeasure]
    description: str | None
    annotations: list[PBIAnnotation] = []
    # Tables that exist purely to host measures (the "Measures" home table
    # pattern) emit a constant single-row partition instead of a Databricks
    # source. The TMDL writer picks the right M expression based on this.
    is_measures_table: bool = False


class PBIRelationship(BaseModel):
    from_table: str
    from_columns: list[str]
    to_table: str
    to_columns: list[str]
    cardinality: Literal["one_to_many", "many_to_one", "one_to_one", "many_to_many"]
    is_active: bool = True
    cross_filter: Literal["single", "both"] = "single"


class PBIParameter(BaseModel):
    """A model-level M parameter rendered as a TMDL `expression` block.

    On `.pbip` open, Power BI Desktop prompts the user to fill these in via
    the "Edit Parameters" dialog, so generated models stay portable across
    workspaces/warehouses/catalogs/schemas.
    """

    name: str                  # M identifier; appears in partition expressions
    # Current value baked into the parameter. When None, the parameter is left
    # with no value so Power BI Desktop prompts the user for it on open (used
    # for PBIP/.pbit deliveries); a string is used for direct XMLA publishes so
    # the Service model refreshes without a manual Edit-Parameters step.
    default_value: str | None = None
    description: str | None = None
    pbi_type: Literal["Text", "Number", "Logical"] = "Text"


class PBIModel(BaseModel):
    name: str
    description: str | None
    tables: list[PBITable]
    relationships: list[PBIRelationship]
    annotations: list[PBIAnnotation] = []
    parameters: list[PBIParameter] = []


def _src_annotations(src: SourceRef, synced_at: datetime) -> list[PBIAnnotation]:
    return [
        PBIAnnotation(name="dbx2pbi_source_kind", value=src.kind),
        PBIAnnotation(name="dbx2pbi_source_id", value=src.fully_qualified_name),
        PBIAnnotation(name="dbx2pbi_object_hash", value=src.object_hash),
        PBIAnnotation(name="dbx2pbi_synced_at", value=synced_at.isoformat()),
    ]


def _build_columns(t: Table) -> list[PBIColumn]:
    return [
        PBIColumn(
            name=c.name,
            data_type=c.data_type,
            # Use the IR's original-casing source_column when populated;
            # otherwise fall back to `name` for backwards compatibility
            # with synthetic/test fixtures that don't carry casing info.
            source_column=c.source_column or c.name,
            description=c.description,
        )
        for c in t.columns
    ]


# "Measures" is a reserved string in Analysis Services / TOM and cannot be
# used as a table name (Fabric returns Dataset_Import_FailedToImportDataset).
# Leading underscore is the long-standing PBI convention for a synthetic
# measures-home table — sorts to the top of the Fields pane in PBI Desktop.
_MEASURES_TABLE_NAME = "_Measures"


def _build_measures_table(
    ir: DatabricksSemanticIR,
    measure_dax: dict[str, str],
    synced_at: datetime,
) -> PBITable | None:
    """Build the synthetic Measures-home table.

    Standard PBI pattern: measures live on a dedicated empty table, not on a
    fact table. The table holds a single hidden dummy column and a constant
    single-row partition (no Databricks connection needed for it).
    """
    if not ir.measures:
        return None
    measures: list[PBIMeasure] = []
    for m in ir.measures:
        if m.name not in measure_dax:
            raise KeyError(f"DAX for measure {m.name!r} not provided to build_pbi_model")
        measures.append(
            PBIMeasure(
                name=m.name,
                dax=measure_dax[m.name],
                description=m.description,
                format_string=m.format_string,
                annotations=_src_annotations(m.source, synced_at),
            )
        )
    # Use the first measure's source annotations for the table itself so
    # ownership tracking still flows through manifest diffs.
    src_for_table = ir.measures[0].source
    return PBITable(
        name=_MEASURES_TABLE_NAME,
        storage_mode="import",
        uc_path=None,
        sql_definition=None,
        columns=[
            PBIColumn(
                name="_",
                data_type="INT",
                source_column="_",
                description=None,
                is_hidden=True,
            ),
        ],
        measures=measures,
        description="Synthetic table that holds all model measures.",
        annotations=[
            *_src_annotations(src_for_table, synced_at),
            PBIAnnotation(name="dbx2pbi_synthetic", value="measures_table"),
        ],
        is_measures_table=True,
    )


_DEFAULT_PARAMETER_DESCRIPTIONS = {
    "ServerHostname": "Databricks workspace hostname (no scheme, e.g. adb-xxx.azuredatabricks.net)",
    "HTTPPath": "SQL warehouse HTTP path (e.g. /sql/1.0/warehouses/<id>)",
}


def _build_parameters(
    ir: DatabricksSemanticIR,
    *,
    workspace_host: str | None = None,
    http_path: str | None = None,
) -> list[PBIParameter]:
    """Derive connection parameters from the IR + runtime context.

    Only WorkspaceHost + HttpPath are parameters. Catalog + Schema + Table
    names are baked literally into each table's M expression — Power BI
    Service's "static M" analyzer flags parameter-driven navigation steps
    as a dynamic data source, blocking Service refresh and causing the
    OnPremiseServiceException refresh failure mode.

    Callers pass the runtime workspace_host + http_path so the published
    model refreshes without any post-publish Edit-Parameters step.
    """
    del ir  # IR may still inform future params; currently unused.
    # Parameter names match the canonical PBI Databricks connector
    # output (ServerHostname / HTTPPath). PBI's data-source detector
    # looks for these specific names; renaming them breaks the match.
    return [
        PBIParameter(
            name="ServerHostname",
            default_value=workspace_host,
            description=_DEFAULT_PARAMETER_DESCRIPTIONS["ServerHostname"],
        ),
        PBIParameter(
            name="HTTPPath",
            default_value=http_path,
            description=_DEFAULT_PARAMETER_DESCRIPTIONS["HTTPPath"],
        ),
    ]


def _columns_referenced_by_relationships(
    ir: DatabricksSemanticIR,
) -> dict[str, set[str]]:
    """Return {table_name: {column_name, ...}} listing every column that
    appears on either end of a relationship.

    Required because Fabric's reference resolver rejects the model when a
    relationship's from/to column isn't declared on its table — even if
    the column does exist in the underlying source. Our column inference
    only picks up identifiers referenced by measures/dimensions, so join
    keys (e.g. `lineitem.l_orderkey`) are otherwise missing.
    """
    out: dict[str, set[str]] = {}
    for r in ir.relationships:
        out.setdefault(r.from_table, set()).update(r.from_columns)
        out.setdefault(r.to_table, set()).update(r.to_columns)
    return out


def _build_columns_with_join_keys(
    t: Table, join_keys: set[str],
) -> list[PBIColumn]:
    """Materialise the table's columns from the IR, then append any
    relationship-endpoint join keys that the column list doesn't already
    cover. Dedup is case-INSENSITIVE because Fabric TMDL treats column
    names case-insensitively (matches what Databricks UC does), so two
    differently-cased entries trip the ``Item already exists`` check.
    """
    raw = _build_columns(t)
    out: list[PBIColumn] = []
    seen_lower: set[str] = set()
    for c in raw:
        if c.name.lower() in seen_lower:
            continue
        seen_lower.add(c.name.lower())
        out.append(c)
    for key in sorted(join_keys):
        if key and key.lower() not in seen_lower:
            seen_lower.add(key.lower())
            out.append(
                PBIColumn(
                    name=key,
                    data_type="string",
                    source_column=key,
                    is_hidden=True,
                ),
            )
    return out


def build_pbi_model(
    ir: DatabricksSemanticIR,
    *,
    measure_dax: dict[str, str],
    synced_at: datetime,
    workspace_host: str | None = None,
    http_path: str | None = None,
    storage_mode_overrides: dict[str, str] | None = None,
) -> PBIModel:
    # Data tables get NO measures — they all move to the dedicated table below.
    rel_cols_by_table = _columns_referenced_by_relationships(ir)
    overrides = storage_mode_overrides or {}
    _allowed_modes = {"import", "direct_query", "dual"}

    def _resolve_mode(t: Table) -> str:
        override = overrides.get(t.name)
        if override and override in _allowed_modes:
            return override
        return t.storage_mode

    pbi_tables = [
        PBITable(
            name=t.name,
            storage_mode=cast(
                Literal["direct_query", "dual", "import"], _resolve_mode(t),
            ),
            uc_path=t.uc_path,
            sql_definition=t.sql_definition,
            columns=_build_columns_with_join_keys(
                t, rel_cols_by_table.get(t.name, set()),
            ),
            measures=[],
            description=t.description,
            annotations=_src_annotations(t.source, synced_at),
        )
        for t in ir.tables
    ]
    measures_table = _build_measures_table(ir, measure_dax, synced_at)
    if measures_table is not None:
        pbi_tables.append(measures_table)
    pbi_rels = [
        PBIRelationship(
            from_table=r.from_table,
            from_columns=r.from_columns,
            to_table=r.to_table,
            to_columns=r.to_columns,
            cardinality=r.cardinality,
            is_active=r.is_active,
            cross_filter=r.cross_filter,
        )
        for r in ir.relationships
    ]
    return PBIModel(
        name=ir.name,
        description=ir.description,
        tables=pbi_tables,
        relationships=pbi_rels,
        parameters=_build_parameters(
            ir, workspace_host=workspace_host, http_path=http_path,
        ),
    )
