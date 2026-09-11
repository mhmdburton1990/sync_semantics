"""Read a Unity Catalog Metric View and emit a partial DatabricksSemanticIR."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

import yaml

from databricks_to_pbi.ir import (
    Column,
    DatabricksSemanticIR,
    Dimension,
    Measure,
    Relationship,
    SourceRef,
    Table,
    WindowClause,
)
from databricks_to_pbi.workspace import WorkspaceClient

__all__ = ["parse_metric_view_yaml", "read_metric_view"]


def parse_metric_view_yaml(body: str) -> dict[str, Any]:
    data = yaml.safe_load(body)
    if not isinstance(data, dict):
        raise ValueError("metric view definition is not a YAML mapping")
    return data


_VIEW_DEFINITION_LABELS = frozenset({"view text", "view definition"})


def _extract_definition(rows: list[list[str]]) -> str:
    """Pull the YAML body from DESCRIBE EXTENDED output.

    Databricks labels it ``View Text`` in production output; older fixtures
    used ``View Definition``. We accept either.
    """
    for row in rows:
        if row and str(row[0]).strip().lower() in _VIEW_DEFINITION_LABELS:
            return str(row[1])
    raise ValueError(
        "metric view DESCRIBE EXTENDED output has no 'View Text' / "
        "'View Definition' row — is the object actually a METRIC_VIEW?"
    )


def _source_ref(name: str, body: str) -> SourceRef:
    return SourceRef(
        kind="metric_view",
        fully_qualified_name=name,
        object_hash=hashlib.sha256(body.encode("utf-8")).hexdigest()[:16],
        fetched_at=datetime.now(UTC),
    )


_COL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
_EXCLUDE: frozenset[str] = frozenset(
    {
        "SUM", "AVG", "MIN", "MAX", "COUNT", "DISTINCT", "CASE", "WHEN",
        "THEN", "ELSE", "END", "FILTER", "WHERE", "AND", "OR", "NOT", "NULL",
        "DIVIDE", "CALCULATE", "COUNTROWS", "DISTINCTCOUNT", "SUMX",
    }
)


def _build_table(
    uc_path: str,
    src: SourceRef,
    storage_mode: str = "direct_query",
    columns: list[Column] | None = None,
    name: str | None = None,
) -> Table:
    return Table(
        # Joined tables use the metric view's `name:` (the alias) as the
        # canonical identifier — that's what the join's `on:` clauses and
        # dimension expressions refer to. Falling back to the source's last
        # segment for backwards compatibility with `source: <UC path>` tables
        # that have no separate name.
        name=name or uc_path.split(".")[-1],
        uc_path=uc_path,
        sql_definition=None,
        storage_mode=storage_mode,  # type: ignore[arg-type]
        columns=columns or [],
        description=None,
        source=src,
    )


def _build_dimensions(parsed: dict[str, Any]) -> list[Dimension]:
    dims: list[Dimension] = []
    for d in parsed.get("dimensions", []) or []:
        dims.append(
            Dimension(
                name=d["name"],
                expression=d["expr"],
                underlying_columns=[d["expr"]] if "(" not in d["expr"] else [],
                description=d.get("description"),
                hierarchy=None,
            )
        )
    return dims


def _decimal_places(format_block: dict[str, Any]) -> int:
    dp = format_block.get("decimal_places")
    if isinstance(dp, dict):
        places = dp.get("places")
        if isinstance(places, int):
            return places
    if isinstance(dp, int):
        return dp
    return 0


def _format_to_string(fmt: Any) -> str | None:
    """Translate the metric view ``format:`` block to a Power BI format string.

    The YAML form is either a bare string (legacy / our fixture) or a nested
    mapping with ``type``, ``currency_code``, ``decimal_places.places``,
    ``abbreviation`` etc. Produce DAX-compatible format strings for the
    common cases; return None for anything we don't recognise so PBI falls
    back to default formatting.
    """
    if fmt is None:
        return None
    if isinstance(fmt, str):
        return fmt
    if not isinstance(fmt, dict):
        return None

    # Some YAML shapes wrap the type as the dict KEY (e.g. {currency: {...}})
    # — flatten that into {type: currency, ...other}.
    if "type" not in fmt and len(fmt) == 1:
        only_key, only_val = next(iter(fmt.items()))
        if isinstance(only_val, dict):
            fmt = {"type": only_key, **only_val}

    kind = str(fmt.get("type") or "").lower()
    places = _decimal_places(fmt)
    decimals = "." + ("0" * places) if places > 0 else ""

    if kind == "currency":
        code = str(fmt.get("currency_code") or "USD").upper()
        symbol = {"USD": r"\$", "EUR": "€", "GBP": "£"}.get(code, code + " ")
        return f"{symbol}#,0{decimals}"
    if kind == "percentage":
        return f"0{decimals}%"
    if kind == "number":
        return f"#,0{decimals}"
    return None


def _build_measures(parsed: dict[str, Any], src: SourceRef) -> list[Measure]:
    measures: list[Measure] = []
    for m in parsed.get("measures", []) or []:
        # Strip qualified "source." prefix so rules can match bare column names.
        sql = m["expr"].replace("source.", "")
        raw_window = m.get("window")
        window = (
            [
                WindowClause(order=str(w["order"]), range=str(w["range"]))
                for w in raw_window
                if w.get("order") and w.get("range")
            ]
            if isinstance(raw_window, list) and raw_window
            else None
        )
        measures.append(
            Measure(
                name=m["name"],
                sql_expression=sql,
                dependencies=[],
                description=m.get("description") or m.get("comment"),
                format_string=_format_to_string(m.get("format")),
                source=src,
                window=window,
            )
        )
    return measures


def _flatten_joins(joins: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Production metric views nest joins (joins of joins of joins). Flatten."""
    out: list[dict[str, Any]] = []
    for j in joins or []:
        out.append(j)
        out.extend(_flatten_joins(j.get("joins")))
    return out


def _walk_joins_with_parent(
    joins: list[dict[str, Any]] | None, parent: str,
) -> list[tuple[dict[str, Any], str]]:
    """Walk the join tree carrying each join's PARENT table name.

    When the `on:` clause contains an unqualified column reference, the column
    belongs to either the parent table (left side) or the joined-in table
    (right side). Flattening alone loses that context.
    """
    out: list[tuple[dict[str, Any], str]] = []
    for j in joins or []:
        out.append((j, parent))
        sub = j.get("joins") or []
        if sub:
            out.extend(_walk_joins_with_parent(sub, j.get("name") or ""))
    return out


def _host_table_name_from_source(source: str) -> str:
    """Extract the host-table identifier from the metric view's `source:`.

    Mirrors `_main_table_from_source` but only returns the bare table name
    (no UC path or SQL body), so relationship parsing can use it as the
    parent for top-level joins.
    """
    s = source.strip()
    if _source_is_sql(s):
        m = re.search(
            r"\bFROM\s+([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*){0,2})",
            s,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).split(".")[-1]
    return s.split(".")[-1]


def _resolve_join_side(token: str, default_table: str) -> tuple[str, str]:
    """Given one side of a join `on:` clause, return (table, column).

    A join condition connects exactly this side's structural table — the parent
    for the left side, the joined table (its YAML `name` alias) for the right —
    so for a bare column OR a 2-segment ref we use ``default_table``. The 2-segment
    prefix is just the SQL writer's qualifier and is NOT a reliable model table
    name: it may be the ``source`` keyword (= host), the joined table's source
    basename (e.g. ``dim_calendar`` when the alias is ``calendar``), or the alias
    itself — using it verbatim produces relationships that reference non-existent
    columns and Fabric publish rejects them. Only a 3+-segment transitive ref
    (e.g. ``orders.customer.c_name``) names a distinct intermediate table, so we
    take its last-but-one segment.
    """
    parts = token.strip().split(".")
    if len(parts) <= 2:
        return default_table, parts[-1]
    return parts[-2], parts[-1]


def _build_relationships(parsed: dict[str, Any]) -> list[Relationship]:
    rels: list[Relationship] = []
    host = _host_table_name_from_source(str(parsed.get("source") or ""))
    for j, parent_table in _walk_joins_with_parent(parsed.get("joins"), host):
        # YAML 1.1 parses bare `on:` as boolean True, so check both forms.
        on: str = j.get("on") or j.get(True, "") or ""  # type: ignore[call-overload]
        left, _, right = on.partition("=")
        if not (left.strip() and right.strip()):
            continue
        l_tab, l_col = _resolve_join_side(left, parent_table)
        joined_table = j.get("name") or ""
        r_tab, r_col = _resolve_join_side(right, joined_table)
        if not (l_tab and l_col and r_tab and r_col):
            continue
        # `rely.at_most_one_match` is the modern replacement for the legacy
        # `unique: true` flag — both signal a many_to_one cardinality hint.
        unique = bool(j.get("unique")) or bool(
            (j.get("rely") or {}).get("at_most_one_match")
        )
        rels.append(
            Relationship(
                from_table=l_tab,
                from_columns=[l_col],
                to_table=r_tab,
                to_columns=[r_col],
                cardinality="many_to_one" if unique else "many_to_many",
            )
        )
    return rels


_SQL_SOURCE_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


def _source_is_sql(source: str) -> bool:
    return bool(_SQL_SOURCE_RE.match(source))


_FROM_FQN_RE = re.compile(
    r"\bFROM\s+([A-Za-z_][\w]*\.[A-Za-z_][\w]*\.[A-Za-z_][\w]*)",
    re.IGNORECASE,
)


def _main_table_from_source(source: str, fqn: str) -> tuple[str, str | None, str | None]:
    """Return (name, uc_path, sql_definition) for the main table.

    Always resolves a UC path so the M writer can emit a standard
    ``Databricks.Catalogs`` navigation (PBI Service recognises it as a
    Databricks data source). Two source forms are accepted:

    - Bare UC reference: ``source: cat.sch.tab``.
    - SQL: ``source: SELECT ... FROM cat.sch.tab ...``. The FQN in the
      FROM clause is taken as the UC path — any filters / projections /
      joins in the SQL are dropped at the PBI-table level. PBI measures
      and visual filters will reproduce the desired slice on top of the
      raw UC table, which is what the user actually wants for analysis.

    ``sql_definition`` is always returned as ``None`` — the model never
    emits a ``Databricks.Query`` partition source because PBI Service's
    data-source detector rejects it ("We could not detect the data
    source information for this table"). If the SQL can't be parsed for
    a FROM <fqn>, fall back to the metric view's own FQN.
    """
    s = source.strip()
    if not _source_is_sql(s):
        # `source: cat.sch.tab`
        return s.split(".")[-1], s, None
    m = _FROM_FQN_RE.search(s)
    if m:
        uc_path = m.group(1)
        return uc_path.split(".")[-1], uc_path, None
    # SQL without an identifiable cat.sch.tab — fall back to the metric
    # view itself as the source table (the metric view IS a UC object).
    return fqn.split(".")[-1], fqn, None


def _primary_key_columns(client: WorkspaceClient, uc_path: str) -> set[str]:
    """Best-effort: lowercased primary-key column names for a UC table.

    Reads the catalog's ``information_schema``. Returns an empty set on any
    error (e.g. no access, no constraints defined) so key detection never
    breaks a sync — callers treat "no keys" as "fall back to COUNTROWS".
    The join fan-out and case variants in information_schema produce duplicate
    rows, so the result is deduped case-insensitively.
    """
    parts = uc_path.split(".")
    if len(parts) != 3:
        return set()
    catalog, schema, table = parts
    sql = (
        "SELECT kcu.column_name "
        f"FROM {catalog}.information_schema.table_constraints tc "
        f"JOIN {catalog}.information_schema.key_column_usage kcu "
        "ON tc.constraint_name = kcu.constraint_name "
        "AND tc.table_schema = kcu.table_schema "
        "AND tc.table_name = kcu.table_name "
        f"WHERE tc.table_schema = '{schema}' AND tc.table_name = '{table}' "
        "AND tc.constraint_type = 'PRIMARY KEY'"
    )
    try:
        rows = client.run_query(sql)
    except Exception:
        return set()
    return {row[0].lower() for row in rows if row and row[0]}


def _fetch_uc_columns(
    client: WorkspaceClient, uc_path: str,
) -> list[Column]:
    """Best-effort column metadata fetch for a UC table.

    DESCRIBE TABLE on a partitioned table emits the partition column twice
    (once in the regular column list, once under `# Partition Information`).
    Our describe_columns parser stops at the `#` marker, but a similar
    duplication can happen with bucket columns or comment metadata. Dedupe
    here by first-seen so the PBI model never carries two columns with the
    same name (Fabric rejects with `Item ... already exists in the collection`).
    """
    try:
        rows = client.describe_columns(uc_path)
    except Exception:
        return []
    pk_columns = _primary_key_columns(client, uc_path)
    out: list[Column] = []
    seen: set[str] = set()
    for raw_name, dtype in rows:
        # Normalise NAME to lowercase (TMDL/PBI internal consistency) but
        # preserve the ORIGINAL casing as source_column for the
        # DirectQuery SQL the Databricks connector generates. Without
        # this split, TPC-H queries fail with
        # `column 't0.l_orderkey' of the table wasn't found` because the
        # underlying column is actually `L_ORDERKEY`.
        name = raw_name.lower()
        if name in seen:
            continue
        seen.add(name)
        out.append(
            Column(
                name=name,
                source_column=raw_name,
                uc_path=f"{uc_path}.{name}",
                data_type=dtype.upper() if dtype else "STRING",
                is_key=name in pk_columns,
            ),
        )
    return out


def read_metric_view(
    client: WorkspaceClient,
    *,
    fully_qualified_name: str,
) -> DatabricksSemanticIR:
    rows = client.describe_extended(fully_qualified_name)
    body = _extract_definition(rows)
    parsed = parse_metric_view_yaml(body)
    src = _source_ref(fully_qualified_name, body)

    source = str(parsed["source"])
    main_name, main_uc, main_sql = _main_table_from_source(source, fully_qualified_name)

    # Real-table columns: fetch from UC for sourced tables (richer; matches
    # what a hand-built model would have). Fall back to measure-inferred set
    # for SQL-source tables (no underlying single UC table to describe).
    main_columns: list[Column]
    if main_uc:
        main_columns = _fetch_uc_columns(client, main_uc)
    else:
        # SQL-source: infer from measure expressions. Last-resort, low fidelity.
        inferred_cols: set[str] = set()
        for m in parsed.get("measures", []) or []:
            expr = m["expr"].replace("source.", "")
            for word in _COL_RE.findall(expr):
                if word.upper() not in _EXCLUDE and not word.isdigit():
                    inferred_cols.add(word.lower())
        main_columns = [
            Column(name=c, uc_path=None, data_type="STRING")
            for c in sorted(inferred_cols)
        ]
    # For the SQL-source case (TPC-H style `SELECT * FROM <fqn>`), augment
    # the inferred set with the actual columns of the referenced UC table.
    if main_sql and not main_columns:
        # Try parsing the FROM table out of the SQL definition and querying its
        # schema. Captures the common `SELECT * FROM cat.sch.tab` pattern.
        m = re.search(
            r"\bFROM\s+([A-Za-z_][\w]*\.[A-Za-z_][\w]*\.[A-Za-z_][\w]*)",
            main_sql,
            re.IGNORECASE,
        )
        if m:
            main_columns = _fetch_uc_columns(client, m.group(1))

    tables = [
        Table(
            name=main_name,
            uc_path=main_uc,
            sql_definition=main_sql,
            # The working reference model uses directQuery for all tables.
            # Once the M is shaped correctly, PBI Service recognises the
            # data source and the credentials editor appears.
            storage_mode="direct_query",
            columns=main_columns,
            description=None,
            source=src,
        ),
    ]
    for j in _flatten_joins(parsed.get("joins")):
        join_src = j.get("source")
        if not join_src:
            continue  # nested joins on a parent table; no new table to add
        join_columns = _fetch_uc_columns(client, str(join_src))
        tables.append(
            _build_table(
                str(join_src),
                src,
                # Match the working reference model: all Databricks tables
                # use directQuery in the canonical "Publish to Power BI"
                # output.
                storage_mode="direct_query",
                name=j.get("name"),
                columns=join_columns,
            ),
        )

    parts = fully_qualified_name.split(".")
    # Use schema (middle part of catalog.schema.table) as the PBI model name,
    # capitalised so "sales" → "Sales".  Fall back to the last segment.
    model_name = parts[-2].capitalize() if len(parts) >= 3 else parts[-1]

    return DatabricksSemanticIR(
        name=model_name,
        description=None,
        tables=tables,
        dimensions=_build_dimensions(parsed),
        measures=_build_measures(parsed, src),
        relationships=_build_relationships(parsed),
        genie=None,
        sources=[src],
    )
