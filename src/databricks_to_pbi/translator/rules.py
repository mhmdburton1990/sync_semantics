"""SQL→DAX rule engine. Each rule is a pure function: (sql, ctx) -> dax | None."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

__all__ = [
    "RuleContext",
    "apply_rules",
    "rule_aggx_complex",
    "rule_arithmetic_aggregates",
    "rule_avg",
    "rule_avg_datediff",
    "rule_calculate_case",
    "rule_calculate_case_else",
    "rule_calculate_filter",
    "rule_case_multi_when",
    "rule_coalesce",
    "rule_count",
    "rule_count_distinct",
    "rule_count_star",
    "rule_divide_nullif",
    "rule_lod_aggregate_over_except",
    "rule_lod_over",
    "rule_max",
    "rule_measure_ref",
    "rule_min",
    "rule_sum",
]


# ---------------------------------------------------------------------------
# Column reference handling.
#
# Real metric views often reference columns through joins, e.g.
# `COUNT(DISTINCT orders.o_orderkey)`. We accept either bare (`col`) or dotted
# (`table.col`) references everywhere a column can appear; `RuleContext.qualify`
# generates the right DAX form for each.
# ---------------------------------------------------------------------------

# Matches `col` OR `table.col`. Captured as a single group.
_COL_REF = r"(?:[A-Za-z_]\w*\.)?[A-Za-z_]\w*"


@dataclass(frozen=True, slots=True)
class RuleContext:
    table: str
    columns_by_table: dict[str, list[str]]

    def qualify(self, ref: str) -> str:
        """Quote a column reference into DAX form.

        - `col`        → `'host_table'[col]` (checked against host columns list)
        - `table.col`  → `'table'[col]`       (no existence check; we usually
                                              don't know the joined table's cols)
        """
        if "." in ref:
            table, _, col = ref.partition(".")
            return f"'{table}'[{col}]"
        cols = self.columns_by_table.get(self.table, [])
        if cols and ref not in cols:
            raise ValueError(f"column {ref!r} not found on table {self.table!r}")
        return f"'{self.table}'[{ref}]"


# ---------------------------------------------------------------------------
# Simple single-column aggregates: SUM/AVG/MIN/MAX/COUNT/COUNT(DISTINCT)
# ---------------------------------------------------------------------------

_AGG_RE = {
    "sum": re.compile(rf"^\s*SUM\s*\(\s*({_COL_REF})\s*\)\s*$", re.IGNORECASE),
    "avg": re.compile(rf"^\s*AVG\s*\(\s*({_COL_REF})\s*\)\s*$", re.IGNORECASE),
    "min": re.compile(rf"^\s*MIN\s*\(\s*({_COL_REF})\s*\)\s*$", re.IGNORECASE),
    "max": re.compile(rf"^\s*MAX\s*\(\s*({_COL_REF})\s*\)\s*$", re.IGNORECASE),
    "count": re.compile(rf"^\s*COUNT\s*\(\s*({_COL_REF})\s*\)\s*$", re.IGNORECASE),
    "count_star": re.compile(r"^\s*COUNT\s*\(\s*\*\s*\)\s*$", re.IGNORECASE),
    "count_distinct": re.compile(
        rf"^\s*COUNT\s*\(\s*DISTINCT\s+({_COL_REF})\s*\)\s*$", re.IGNORECASE
    ),
}


def _simple_agg(sql: str, ctx: RuleContext, key: str, dax_fn: str) -> str | None:
    m = _AGG_RE[key].match(sql)
    if not m:
        return None
    return f"{dax_fn}({ctx.qualify(m.group(1))})"


def rule_sum(sql: str, ctx: RuleContext) -> str | None:
    return _simple_agg(sql, ctx, "sum", "SUM")


def rule_avg(sql: str, ctx: RuleContext) -> str | None:
    return _simple_agg(sql, ctx, "avg", "AVERAGE")


def rule_min(sql: str, ctx: RuleContext) -> str | None:
    return _simple_agg(sql, ctx, "min", "MIN")


def rule_max(sql: str, ctx: RuleContext) -> str | None:
    return _simple_agg(sql, ctx, "max", "MAX")


def rule_count(sql: str, ctx: RuleContext) -> str | None:
    return _simple_agg(sql, ctx, "count", "COUNT")


def rule_count_star(sql: str, ctx: RuleContext) -> str | None:
    if not _AGG_RE["count_star"].match(sql):
        return None
    return f"COUNTROWS('{ctx.table}')"


def rule_count_distinct(sql: str, ctx: RuleContext) -> str | None:
    m = _AGG_RE["count_distinct"].match(sql)
    if not m:
        return None
    return f"DISTINCTCOUNT({ctx.qualify(m.group(1))})"


# ---------------------------------------------------------------------------
# Row-context expression translator.
#
# Used by everything that emits SUMX / AVERAGEX / MINX / MAXX / SUMMARIZE —
# anything that takes a row-context expression. Performs three jobs:
#   1. Replaces `col` and `table.col` identifiers with DAX `'table'[col]`.
#   2. Translates SQL math wrappers (ABS, ROUND, CEIL, FLOOR, GREATEST,
#      LEAST) to their DAX equivalents.
#   3. Maps SQL `NULL` to DAX `BLANK()` and SQL string concat `||` to DAX `&`.
# ---------------------------------------------------------------------------

# Identifiers we must NOT requalify as columns when they appear bare.
_NON_COLUMN_TOKENS = frozenset({
    "NULL", "BLANK", "TRUE", "FALSE",
    "AND", "OR", "NOT", "IN", "IS", "LIKE", "BETWEEN",
    "CASE", "WHEN", "THEN", "ELSE", "END",
    # Functions whose names we leave intact (translated separately).
    "ABS", "ROUND", "CEILING", "FLOOR", "MAX", "MIN", "DATEDIFF", "YEAR",
    "MONTH", "DAY", "QUARTER", "WEEK", "DATE", "TIME",
})


_IDENT_RE = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\b")


def _qualify_in_expr(expr: str, ctx: RuleContext) -> str:
    """Substitute identifiers and translate row-context idioms into DAX.

    The substitution is regex-driven so it's pragmatic, not a full parser —
    it works for column refs, dotted refs, arithmetic, parens, numeric
    literals, NULL, and the math wrappers below. SQL string literals
    inside ``'…'`` are left alone.
    """
    # SQL string concat `||` → DAX `&`
    expr = re.sub(r"\|\|", " & ", expr)

    # Math wrappers — name and arg shapes differ from DAX
    expr = re.sub(r"\bCEIL\b", "CEILING", expr, flags=re.IGNORECASE)
    expr = re.sub(r"\bGREATEST\b", "MAX", expr, flags=re.IGNORECASE)
    expr = re.sub(r"\bLEAST\b", "MIN", expr, flags=re.IGNORECASE)

    # NULL → BLANK()
    expr = re.sub(r"\bNULL\b", "BLANK()", expr, flags=re.IGNORECASE)

    # Replace identifiers with qualified DAX form. We walk the string and
    # skip identifiers that fall inside a single-quoted string literal.
    out: list[str] = []
    i = 0
    n = len(expr)
    in_string = False
    while i < n:
        ch = expr[i]
        if in_string:
            out.append(ch)
            if ch == "'":
                # `''` is an escape (literal apostrophe); skip the next char too.
                if i + 1 < n and expr[i + 1] == "'":
                    out.append(expr[i + 1])
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if ch == "'":
            in_string = True
            out.append(ch)
            i += 1
            continue
        m = _IDENT_RE.match(expr, i)
        if m and m.start() == i:
            ident = m.group(1)
            up = ident.upper()
            if up in _NON_COLUMN_TOKENS:
                out.append(ident)
            elif "." in ident:
                table, _, col = ident.partition(".")
                out.append(f"'{table}'[{col}]")
            else:
                cols = ctx.columns_by_table.get(ctx.table, [])
                if cols and ident in cols:
                    out.append(f"'{ctx.table}'[{ident}]")
                else:
                    out.append(ident)
            i = m.end()
            continue
        out.append(ch)
        i += 1
    # DAX CEILING / FLOOR require an explicit significance argument.
    result = "".join(out)
    result = re.sub(
        r"\bCEILING\s*\(\s*([^,)]+?)\s*\)", r"CEILING(\1, 1)", result,
    )
    return re.sub(
        r"\bFLOOR\s*\(\s*([^,)]+?)\s*\)", r"FLOOR(\1, 1)", result,
    )


# ---------------------------------------------------------------------------
# SUM/AVG/MIN/MAX of a complex expression → SUMX / AVERAGEX / MINX / MAXX.
#
# Subsumes the old SUM(a*b), SUM(a*(1-b)), SUM(a*(1-b)*c) rules: anything
# beyond a bare column inside the aggregate now goes through one path.
# ---------------------------------------------------------------------------

_AGG_TO_X = {"SUM": "SUMX", "AVG": "AVERAGEX", "MIN": "MINX", "MAX": "MAXX"}


def _matched_paren(s: str, open_idx: int) -> int:
    """Return the index of the ``)`` that closes the ``(`` at ``open_idx``.

    Paren-/string-aware. Returns -1 if unbalanced.
    """
    depth = 0
    in_string = False
    i = open_idx
    n = len(s)
    while i < n:
        ch = s[i]
        if in_string:
            if ch == "'":
                if i + 1 < n and s[i + 1] == "'":
                    i += 2
                    continue
                in_string = False
        elif ch == "'":
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def rule_aggx_complex(sql: str, ctx: RuleContext) -> str | None:
    """``SUM(<expr>)`` → ``SUMX('t', <translated-expr>)``, and friends.

    Falls through to None when:
      - the wrapping aggregate doesn't span the whole expression
        (e.g. ``SUM(a) - LAG(SUM(a), 1) OVER ()`` — the SUM is just one term)
      - the inner is a bare column reference (handled by rule_sum / rule_avg)
      - the inner is just ``*`` (handled by rule_count_star)
      - the inner is ``DISTINCT col`` (handled by rule_count_distinct)
      - the inner contains a top-level FILTER (handled by rule_calculate_filter)
    """
    sql = sql.strip()
    m = re.match(r"^(SUM|AVG|MIN|MAX)\s*\(", sql, re.IGNORECASE)
    if not m:
        return None
    agg = m.group(1).upper()
    open_idx = m.end() - 1
    close_idx = _matched_paren(sql, open_idx)
    if close_idx == -1:
        return None
    # The aggregate must wrap the entire expression, not just the first term.
    if sql[close_idx + 1:].strip():
        return None
    inner = sql[open_idx + 1: close_idx].strip()

    if re.fullmatch(_COL_REF, inner):
        return None  # bare column → rule_sum / rule_avg handles it
    if inner == "*":
        return None  # COUNT(*) is on a different rule
    if re.match(r"^DISTINCT\b", inner, re.IGNORECASE):
        return None  # COUNT(DISTINCT col)
    if re.search(r"\bFILTER\s*\(", inner, re.IGNORECASE):
        return None  # FILTER goes through rule_calculate_filter

    translated = _qualify_in_expr(inner, ctx)
    if translated == inner:
        # No substitution happened → probably nothing the engine recognises.
        return None
    return f"{_AGG_TO_X[agg]}('{ctx.table}', {translated})"


# ---------------------------------------------------------------------------
# MEASURE(...) cross-references: DAX uses [measure_name] directly.
# ---------------------------------------------------------------------------

_MEASURE = r"MEASURE\s*\(\s*([A-Za-z_]\w*)\s*\)"
_MEASURE_REF_ONLY = re.compile(rf"^\s*{_MEASURE}\s*$", re.IGNORECASE)
_DIVIDE_NULLIF_GENERIC = re.compile(
    r"^\s*(?P<num>.+?)\s*/\s*NULLIF\s*\(\s*(?P<den>.+?)\s*,\s*0\s*\)\s*$",
    re.IGNORECASE | re.DOTALL,
)


def rule_measure_ref(sql: str, _: RuleContext) -> str | None:
    """MEASURE(name) → [name]"""
    m = _MEASURE_REF_ONLY.match(sql)
    return f"[{m.group(1)}]" if m else None


def rule_divide_nullif(sql: str, ctx: RuleContext) -> str | None:
    """``<num> / NULLIF(<den>, 0)`` → ``DIVIDE(<dax-num>, <dax-den>)``.

    DAX ``DIVIDE`` natively returns BLANK on a zero/null denominator, so the
    NULLIF guard is unnecessary on the PBI side. Numerator and denominator
    each go through the rule engine recursively, so this works for
    MEASURE(a) / NULLIF(MEASURE(b), 0), SUM(a) / NULLIF(SUM(b), 0), etc.
    """
    m = _DIVIDE_NULLIF_GENERIC.match(sql)
    if not m:
        return None
    num_dax, _ = apply_rules(m.group("num").strip(), ctx)
    den_dax, _ = apply_rules(m.group("den").strip(), ctx)
    if num_dax is None or den_dax is None:
        return None
    return f"DIVIDE({num_dax}, {den_dax})"


# ---------------------------------------------------------------------------
# Generic arithmetic on aggregates: ``<agg> [+-*/] <agg>``.
#
# Recursively translates each side via apply_rules, so any combination of
# rule-supported aggregates composes for free. Subsumes the old:
#   SUM(a) / SUM(b)        → DIVIDE
#   SUM(a) / COUNT(*)      → DIVIDE
#   MEASURE(a) +-*/ MEASURE(b)
#   SUM(a*(1-b)) / SUM(c)  (weighted ratios)
#   SUM(revenue) - SUM(cost)
# ---------------------------------------------------------------------------


def _find_top_level_binary_op(s: str, ops: tuple[str, ...]) -> int | None:
    """Return the index of the RIGHTMOST top-level occurrence of any of ``ops``.

    Top-level means: paren depth 0, outside string literals. Skips a leading
    unary ``-`` or one right after another operator / open paren. Returns
    ``None`` if no such op exists.
    """
    depth = 0
    in_string = False
    last: int | None = None
    n = len(s)
    i = 0
    while i < n:
        ch = s[i]
        if in_string:
            if ch == "'":
                if i + 1 < n and s[i + 1] == "'":
                    i += 2
                    continue
                in_string = False
        elif ch == "'":
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and ch in ops:
            # Skip unary +/- (i.e. preceded by nothing or by another op/paren).
            if ch in {"+", "-"}:
                j = i - 1
                while j >= 0 and s[j].isspace():
                    j -= 1
                if j < 0 or s[j] in {"(", "+", "-", "*", "/", ","}:
                    i += 1
                    continue
            last = i
        i += 1
    return last


def _split_at(s: str, idx: int) -> tuple[str, str]:
    return s[:idx].strip(), s[idx + 1:].strip()


def rule_arithmetic_aggregates(sql: str, ctx: RuleContext) -> str | None:
    """``<agg-expr> OP <agg-expr>`` where each side translates via the rules.

    Tried after specific patterns (FILTER, CASE, NULLIF). The split honours
    SQL precedence: ``+`` / ``-`` first (lowest precedence), then ``*`` / ``/``.
    Always splits at the rightmost top-level op so chains are left-associative.
    """
    sql = sql.strip()
    for op_set in (("+", "-"), ("*", "/")):
        idx = _find_top_level_binary_op(sql, op_set)
        if idx is None:
            continue
        left_sql, right_sql = _split_at(sql, idx)
        if not left_sql or not right_sql:
            return None
        left_dax, _ = apply_rules(left_sql, ctx)
        right_dax, _ = apply_rules(right_sql, ctx)
        if left_dax is None or right_dax is None:
            return None
        op = sql[idx]
        if op == "/":
            return f"DIVIDE({left_dax}, {right_dax})"
        return f"{left_dax} {op} {right_dax}"
    return None


# ---------------------------------------------------------------------------
# COALESCE / IFNULL wrapping an aggregate
# ---------------------------------------------------------------------------


def _split_args_top_level(s: str) -> list[str]:
    """Split function arguments at top-level commas."""
    parts: list[str] = []
    depth = 0
    in_string = False
    last = 0
    for i, ch in enumerate(s):
        if in_string:
            if ch == "'":
                if i + 1 < len(s) and s[i + 1] == "'":
                    continue
                in_string = False
        elif ch == "'":
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(s[last:i].strip())
            last = i + 1
    parts.append(s[last:].strip())
    return parts


_COALESCE_RE = re.compile(
    r"^\s*(?:COALESCE|IFNULL)\s*\(\s*(?P<args>.+)\)\s*$", re.IGNORECASE | re.DOTALL,
)
_NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def rule_coalesce(sql: str, ctx: RuleContext) -> str | None:
    """``COALESCE(<agg>, …, <default>)`` and ``IFNULL(<agg>, <default>)``.

    Each argument either translates via the rule engine (typical case: an
    aggregate) or is a numeric literal we pass through. The output uses DAX
    ``COALESCE`` which behaves identically.
    """
    m = _COALESCE_RE.match(sql)
    if not m:
        return None
    args = _split_args_top_level(m.group("args"))
    if not args or any(not a for a in args):
        return None
    out: list[str] = []
    for arg in args:
        if _NUMERIC_RE.match(arg):
            out.append(arg)
            continue
        # Bare string literal — pass through as DAX string
        if arg.startswith("'") and arg.endswith("'"):
            out.append(_quote_lit(arg[1:-1]))
            continue
        dax, _ = apply_rules(arg, ctx)
        if dax is None:
            return None
        out.append(dax)
    return f"COALESCE({', '.join(out)})"


# ---------------------------------------------------------------------------
# AVG(DATEDIFF(a, b)) → AVERAGEX with DAX DATEDIFF (needs explicit unit).
# ---------------------------------------------------------------------------

_AVG_DATEDIFF = re.compile(
    rf"^\s*AVG\s*\(\s*DATEDIFF\s*\(\s*({_COL_REF})\s*,\s*({_COL_REF})\s*\)\s*\)\s*$",
    re.IGNORECASE,
)


def rule_avg_datediff(sql: str, ctx: RuleContext) -> str | None:
    """SQL: AVG(DATEDIFF(end, start))
    DAX:  AVERAGEX('t', DATEDIFF('t'[start], 't'[end], DAY))

    SQL DATEDIFF(end, start) returns end - start in days; DAX DATEDIFF takes
    (start, end, unit) — note the argument order swap.
    """
    m = _AVG_DATEDIFF.match(sql)
    if not m:
        return None
    end_col = ctx.qualify(m.group(1))
    start_col = ctx.qualify(m.group(2))
    return f"AVERAGEX('{ctx.table}', DATEDIFF({start_col}, {end_col}, DAY))"


# ---------------------------------------------------------------------------
# Level of Detail (LOD) — AI/BI dashboards expose two flavours:
#
#   1. "Fixed" LOD via scalar window function:
#        <AGG>(<expr>) OVER ()                              → all rows
#        <AGG>(<expr>) OVER (PARTITION BY col1, col2, ...)  → partition by N dims
#      Removes filter context except the listed partition columns.
#      DAX: CALCULATE(<inner>, ALL('t'))
#           CALCULATE(<inner>, ALLEXCEPT('t', 't'[col1], 't'[col2], ...))
#
#   2. "Coarser" LOD via aggregate window:
#        <AGG_EXPR> AGGREGATE OVER (PARTITION BY * EXCEPT (col1, ...))
#      Inherits the visualization's current group-by but DROPS the EXCEPT cols.
#      DAX: CALCULATE(<inner>, ALL('t'[col1]), ALL('t'[col2]), ...)
#
# Docs: https://docs.databricks.com/aws/en/dashboards/manage/data-modeling/
#       custom-calculations/level-of-detail
# ---------------------------------------------------------------------------

_LOD_OVER_RE = re.compile(
    r"^\s*(?P<inner>.+?)\s+OVER\s*\(\s*(?P<over_body>.*?)\s*\)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_LOD_AGGREGATE_OVER_EXCEPT_RE = re.compile(
    r"^\s*(?P<inner>.+?)\s+AGGREGATE\s+OVER\s*\("
    r"\s*PARTITION\s+BY\s+\*\s+EXCEPT\s*\(\s*(?P<cols>[^()]+?)\s*\)\s*"
    r"\)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_PARTITION_BY_RE = re.compile(
    r"^\s*PARTITION\s+BY\s+(?P<cols>.+?)\s*$", re.IGNORECASE | re.DOTALL,
)


def _qualified_col_list(cols_csv: str, ctx: RuleContext) -> list[str] | None:
    """Parse a comma-separated list of column refs into qualified DAX form.

    Each item must look like a column reference (bare or dotted). Returns
    ``None`` if any item is something other than a column.
    """
    items = [c.strip() for c in cols_csv.split(",") if c.strip()]
    if not items:
        return None
    out: list[str] = []
    for item in items:
        if not re.fullmatch(_COL_REF, item):
            return None
        if "." in item:
            table, _, col = item.partition(".")
            out.append(f"'{table}'[{col}]")
        else:
            out.append(f"'{ctx.table}'[{item}]")
    return out


def rule_lod_aggregate_over_except(sql: str, ctx: RuleContext) -> str | None:
    """``<agg> AGGREGATE OVER (PARTITION BY * EXCEPT (col1, col2, …))``
    → ``CALCULATE(<inner>, ALL('t'[col1]), ALL('t'[col2]), …)``.

    Drops the listed columns from filter context; the visualization's other
    group-by columns continue to filter the measure.
    """
    m = _LOD_AGGREGATE_OVER_EXCEPT_RE.match(sql)
    if not m:
        return None
    inner_sql = m.group("inner").strip()
    inner_dax, _ = apply_rules(inner_sql, ctx)
    if inner_dax is None:
        return None
    cols = _qualified_col_list(m.group("cols"), ctx)
    if cols is None:
        return None
    all_clauses = ", ".join(f"ALL({c})" for c in cols)
    return f"CALCULATE({inner_dax}, {all_clauses})"


def rule_lod_over(sql: str, ctx: RuleContext) -> str | None:
    """Fixed LOD: ``<agg>(<expr>) OVER (PARTITION BY cols)`` or ``OVER ()``
    → ``CALCULATE(<inner>, ALLEXCEPT('t', cols))`` / ``CALCULATE(<inner>, ALL('t'))``.

    Note: must be tried AFTER rule_lod_aggregate_over_except (which has a more
    specific ``AGGREGATE OVER`` marker) — otherwise this rule would consume
    `<inner> AGGREGATE OVER (...)` thinking ``AGGREGATE`` is part of the inner.
    """
    m = _LOD_OVER_RE.match(sql)
    if not m:
        return None
    inner_sql = m.group("inner").strip()
    # Don't consume the `AGGREGATE OVER` form — that's the sibling rule's job.
    if inner_sql.upper().endswith(" AGGREGATE"):
        return None
    body = m.group("over_body").strip()

    inner_dax, _ = apply_rules(inner_sql, ctx)
    if inner_dax is None:
        return None

    if not body:
        # OVER () — strip all filters from the host table.
        return f"CALCULATE({inner_dax}, ALL('{ctx.table}'))"

    pb = _PARTITION_BY_RE.match(body)
    if not pb:
        return None  # ORDER BY / window frames aren't LOD patterns
    cols = _qualified_col_list(pb.group("cols"), ctx)
    if cols is None:
        return None
    return f"CALCULATE({inner_dax}, ALLEXCEPT('{ctx.table}', {', '.join(cols)}))"


# ---------------------------------------------------------------------------
# FILTER (WHERE ...) — translate to CALCULATE.
#
# One generic handler: recursively translate whatever aggregate sits inside
# `<agg-expr> FILTER (WHERE cond)`, then wrap in CALCULATE(inner, cond). That
# means anything the rule engine knows how to translate (SUM, AVG, COUNT(*),
# COUNT(DISTINCT col), SUM(a*b), SUM(a*(1-b)), …) automatically supports a
# FILTER clause too.
# ---------------------------------------------------------------------------

_FILTER_RE = re.compile(
    r"^\s*(?P<inner>.+?)\s+FILTER\s*\(\s*WHERE\s+(?P<cond>.+)\)\s*$",
    re.IGNORECASE | re.DOTALL,
)


# ---------------------------------------------------------------------------
# Condition parsers used by both FILTER and CASE WHEN rules.
#
# The translator is a small recursive descent: top-level OR > AND > parens,
# falling through to atomic patterns (NULL / IN / LIKE / comparison).
# ---------------------------------------------------------------------------

# String literals: ` 'foo' ` (escapes via doubled quote `''` are passed through).
_STR_LIT = r"'(?:[^']|'')*'"


def _quote_lit(lit: str) -> str:
    """SQL string literal → DAX literal (single quotes → double; unescape ``''``)."""
    return '"' + lit.replace("''", "'").replace('"', '""') + '"'


# IS [NOT] NULL  →  ISBLANK / NOT(ISBLANK)
_COND_IS_NULL = re.compile(
    rf"^\s*({_COL_REF})\s+IS\s+(NOT\s+)?NULL\s*$", re.IGNORECASE,
)

# [NOT] IN ('a', 'b', ...)
_COND_IN = re.compile(
    rf"^\s*({_COL_REF})\s+(NOT\s+)?IN\s*\(\s*((?:{_STR_LIT}\s*,\s*)*{_STR_LIT})\s*\)\s*$",
    re.IGNORECASE,
)

# LIKE 'pat'  /  LIKE 'pat%'  /  LIKE '%pat'  /  LIKE '%pat%'
_COND_LIKE = re.compile(
    rf"^\s*({_COL_REF})\s+(NOT\s+)?LIKE\s+({_STR_LIT})\s*$", re.IGNORECASE,
)

# col OP 'string'   for OP in {=, !=, <>}
_COND_OP_STR = re.compile(
    rf"^\s*({_COL_REF})\s*(=|!=|<>)\s*({_STR_LIT})\s*$",
)

# col OP num        for OP in {=, !=, <>, >, <, >=, <=}
_COND_OP_NUM = re.compile(
    rf"^\s*({_COL_REF})\s*(=|!=|<>|>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$",
)


def _strip_outer_parens(s: str) -> str:
    """Remove a balanced enclosing pair of parens — but only if they truly wrap
    the whole expression (not e.g. ``(a) AND (b)``)."""
    if not (s.startswith("(") and s.endswith(")")):
        return s
    depth = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and i != len(s) - 1:
                return s
    return s[1:-1].strip()


def _split_top_level(s: str, keyword: str) -> list[str]:
    """Split on ``keyword`` (case-insensitive whole word) at paren depth 0,
    skipping characters inside string literals."""
    parts: list[str] = []
    last = 0
    depth = 0
    in_string = False
    kw_lower = keyword.lower()
    n = len(s)
    i = 0
    while i < n:
        ch = s[i]
        if in_string:
            if ch == "'":
                # Doubled '' is an escape, not a terminator
                if i + 1 < n and s[i + 1] == "'":
                    i += 2
                    continue
                in_string = False
        elif ch == "'":
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and ch.isalpha():
            # Word-boundary match on the keyword
            end = i + len(keyword)
            if (
                end <= n
                and s[i:end].lower() == kw_lower
                and (i == 0 or not (s[i - 1].isalnum() or s[i - 1] == "_"))
                and (end == n or not (s[end].isalnum() or s[end] == "_"))
            ):
                parts.append(s[last:i].strip())
                last = end
                i = end
                continue
        i += 1
    parts.append(s[last:].strip())
    return parts


def _translate_atomic(cond: str, ctx: RuleContext) -> str | None:
    """Translate a single (non-composite) condition."""
    cond = cond.strip()
    if not cond:
        return None

    # IS [NOT] NULL
    m = _COND_IS_NULL.match(cond)
    if m:
        col, negated = m.group(1), m.group(2)
        inner = f"ISBLANK({ctx.qualify(col)})"
        return f"NOT({inner})" if negated else inner

    # [NOT] IN (...)
    m = _COND_IN.match(cond)
    if m:
        col, negated, literals_csv = m.group(1), m.group(2), m.group(3)
        items = re.findall(_STR_LIT, literals_csv)
        formatted = ", ".join(_quote_lit(it[1:-1]) for it in items)
        expr = f"{ctx.qualify(col)} IN {{{formatted}}}"
        return f"NOT({expr})" if negated else expr

    # [NOT] LIKE 'pat'
    m = _COND_LIKE.match(cond)
    if m:
        col, negated, lit_raw = m.group(1), m.group(2), m.group(3)
        pattern = lit_raw[1:-1].replace("''", "'")
        col_dax = ctx.qualify(col)
        has_prefix = pattern.startswith("%")
        has_suffix = pattern.endswith("%")
        inner_pat = pattern.strip("%")
        if "%" in inner_pat or "_" in inner_pat:
            # Mid-string wildcards or single-char wildcards aren't supported by
            # the simple translation. Let the rule engine fall through.
            return None
        if has_prefix and has_suffix:
            inner = f'CONTAINSSTRING({col_dax}, "{inner_pat}")'
        elif has_suffix:
            inner = f'STARTSWITH({col_dax}, "{inner_pat}")'
        elif has_prefix:
            inner = f'ENDSWITH({col_dax}, "{inner_pat}")'
        else:
            inner = f'{col_dax} = "{inner_pat}"'
        return f"NOT({inner})" if negated else inner

    # col OP 'string'
    m = _COND_OP_STR.match(cond)
    if m:
        col, op, lit_raw = m.group(1), m.group(2), m.group(3)
        dax_op = "<>" if op in {"!=", "<>"} else "="
        return f"{ctx.qualify(col)} {dax_op} {_quote_lit(lit_raw[1:-1])}"

    # col OP num
    m = _COND_OP_NUM.match(cond)
    if m:
        col, op, num = m.group(1), m.group(2), m.group(3)
        dax_op = "<>" if op in {"!=", "<>"} else op
        return f"{ctx.qualify(col)} {dax_op} {num}"

    return None


def _translate_condition(cond: str, ctx: RuleContext) -> str | None:
    """Translate an SQL WHERE-style condition to a DAX boolean expression.

    Supports boolean composition via AND / OR (DAX `&&` / `||`), parenthesised
    sub-expressions, and atomic comparisons (=, !=, <>, >, <, >=, <=, IN,
    NOT IN, LIKE, IS NULL, IS NOT NULL).
    """
    cond = _strip_outer_parens(cond.strip())
    if not cond:
        return None

    # Top-level OR (lowest precedence).
    parts = _split_top_level(cond, "OR")
    if len(parts) > 1:
        translated = [_translate_condition(p, ctx) for p in parts]
        if any(t is None for t in translated):
            return None
        return " || ".join(f"({t})" for t in translated)

    # Then AND.
    parts = _split_top_level(cond, "AND")
    if len(parts) > 1:
        translated = [_translate_condition(p, ctx) for p in parts]
        if any(t is None for t in translated):
            return None
        return " && ".join(f"({t})" for t in translated)

    return _translate_atomic(cond, ctx)


def rule_calculate_filter(sql: str, ctx: RuleContext) -> str | None:
    """``<agg> FILTER (WHERE cond)`` → ``CALCULATE(<dax-agg>, <dax-cond>)``.

    Works for any inner aggregate the rule engine already supports —
    SUM(col), SUM(a*b), SUM(a*(1-b)), AVG(col), COUNT(*), COUNT(col),
    COUNT(DISTINCT col), MIN/MAX, etc. Falls through to None if the
    inner pattern isn't recognised.
    """
    m = _FILTER_RE.match(sql)
    if not m:
        return None
    inner_sql = m.group("inner").strip()
    inner_dax, _ = apply_rules(inner_sql, ctx)
    if inner_dax is None:
        return None
    dax_cond = _translate_condition(m.group("cond"), ctx)
    if dax_cond is None:
        return None
    return f"CALCULATE({inner_dax}, {dax_cond})"


# ---------------------------------------------------------------------------
# CASE WHEN ...
#
# Single-WHEN with a bare column THEN col END (with optional ELSE 0 / NULL)
# keeps producing the cleaner `CALCULATE(SUM(...), cond)`. Multi-WHEN or
# branches with arithmetic / non-column THEN values use
# `<AGG>X('t', SWITCH(TRUE(), cond1, expr1, cond2, expr2, …, else_expr))`.
# ---------------------------------------------------------------------------

_CASE_RE = re.compile(
    rf"^\s*SUM\s*\(\s*CASE\s+WHEN\s+(?P<cond>.+?)\s+THEN\s+(?P<col>{_COL_REF})\s+END\s*\)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CASE_ELSE_RE = re.compile(
    rf"^\s*SUM\s*\(\s*CASE\s+WHEN\s+(?P<cond>.+?)\s+THEN\s+(?P<col>{_COL_REF})"
    rf"\s+ELSE\s+(?P<elseval>-?\d+(?:\.\d+)?|NULL)\s+END\s*\)\s*$",
    re.IGNORECASE | re.DOTALL,
)


def rule_calculate_case(sql: str, ctx: RuleContext) -> str | None:
    m = _CASE_RE.match(sql)
    if not m:
        return None
    dax_col = ctx.qualify(m.group("col"))
    dax_cond = _translate_condition(m.group("cond"), ctx)
    if dax_cond is None:
        return None
    return f"CALCULATE(SUM({dax_col}), {dax_cond})"


def rule_calculate_case_else(sql: str, ctx: RuleContext) -> str | None:
    m = _CASE_ELSE_RE.match(sql)
    if not m:
        return None
    elseval = m.group("elseval").upper()
    if elseval not in {"0", "0.0", "NULL"}:
        return None
    dax_col = ctx.qualify(m.group("col"))
    dax_cond = _translate_condition(m.group("cond"), ctx)
    if dax_cond is None:
        return None
    return f"CALCULATE(SUM({dax_col}), {dax_cond})"


# Multi-WHEN: any number of WHEN/THEN pairs, optional ELSE.
_CASE_MULTI_OUTER = re.compile(
    r"^\s*(?P<agg>SUM|AVG|MIN|MAX)\s*\(\s*CASE\s+(?P<branches>.+?)\s+END\s*\)\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _parse_case_branches(branches: str) -> tuple[list[tuple[str, str]], str | None] | None:
    """Split a CASE body into (cond, then_expr) pairs + optional ELSE.

    Returns ``None`` if the body doesn't parse cleanly.
    """
    parts = re.split(r"\s+WHEN\s+", " " + branches, flags=re.IGNORECASE)
    if len(parts) < 2 or parts[0].strip():
        return None  # first split must be empty (text before first WHEN)
    pairs: list[tuple[str, str]] = []
    else_expr: str | None = None
    for branch in parts[1:]:
        m = re.match(r"(?P<cond>.+?)\s+THEN\s+(?P<rest>.+)", branch, re.IGNORECASE | re.DOTALL)
        if not m:
            return None
        cond = m.group("cond").strip()
        rest = m.group("rest").strip()
        else_m = re.search(r"\s+ELSE\s+(?P<else_expr>.+)$", rest, re.IGNORECASE | re.DOTALL)
        if else_m:
            then_expr = rest[: else_m.start()].strip()
            else_expr = else_m.group("else_expr").strip()
        else:
            then_expr = rest
        pairs.append((cond, then_expr))
    return pairs, else_expr


def rule_case_multi_when(sql: str, ctx: RuleContext) -> str | None:
    """Multi-branch CASE wrapped in SUM/AVG/MIN/MAX.

    Emits ``<AGG>X('t', SWITCH(TRUE(), <cond1>, <then1>, …, <else>))`` so each
    branch's THEN expression evaluates in row context.
    """
    m = _CASE_MULTI_OUTER.match(sql)
    if not m:
        return None
    parsed = _parse_case_branches(m.group("branches"))
    if parsed is None:
        return None
    pairs, else_expr = parsed
    if not pairs:
        return None

    switch_args: list[str] = []
    for cond, then_expr in pairs:
        cond_dax = _translate_condition(cond, ctx)
        if cond_dax is None:
            return None
        then_dax = _qualify_in_expr(then_expr, ctx)
        switch_args.append(cond_dax)
        switch_args.append(then_dax)
    if else_expr is not None:
        switch_args.append(_qualify_in_expr(else_expr, ctx))

    agg = m.group("agg").upper()
    aggx = _AGG_TO_X[agg]
    inner = f"SWITCH(TRUE(), {', '.join(switch_args)})"
    return f"{aggx}('{ctx.table}', {inner})"


# ---------------------------------------------------------------------------
# Rule order: more-specific rules first so they get a shot before the simple
# single-column ones match anything (e.g. rule_measure_arithmetic before any
# bare MEASURE() that the dotted-col rules might accidentally match).
# ---------------------------------------------------------------------------

_RULES: list[tuple[str, Callable[[str, RuleContext], str | None]]] = [
    # Level of Detail (AI/BI dashboard syntax). Tried FIRST because both
    # patterns wrap a recognised inner aggregate but add filter-context
    # semantics that subsequent rules don't see.
    # AGGREGATE OVER goes before OVER so the more-specific marker wins.
    ("rule_lod_aggregate_over_except", rule_lod_aggregate_over_except),
    ("rule_lod_over", rule_lod_over),
    # FILTER (WHERE) — generic handler that recurses into the inner aggregate.
    ("rule_calculate_filter", rule_calculate_filter),
    # CASE WHEN — single-WHEN forms first (cleaner CALCULATE output),
    # then multi-WHEN (SUMX + SWITCH).
    ("rule_calculate_case_else", rule_calculate_case_else),
    ("rule_calculate_case", rule_calculate_case),
    ("rule_case_multi_when", rule_case_multi_when),
    # COALESCE / IFNULL wrapping aggregates.
    ("rule_coalesce", rule_coalesce),
    # `<x> / NULLIF(<y>, 0)` is a special arithmetic form — match BEFORE
    # the generic arithmetic so NULLIF is recognised as no-op for DIVIDE.
    ("rule_divide_nullif", rule_divide_nullif),
    # Generic `<agg> [+-*/] <agg>` — recursively translates each side.
    ("rule_arithmetic_aggregates", rule_arithmetic_aggregates),
    # MEASURE(name) — bare cross-reference.
    ("rule_measure_ref", rule_measure_ref),
    # AVG(DATEDIFF(...)) — specific shape that needs argument-order swap.
    ("rule_avg_datediff", rule_avg_datediff),
    # SUM/AVG/MIN/MAX of any non-bare expression → SUMX / AVGX / MINX / MAXX.
    # Subsumes the old SUM(a*b), SUM(a*(1-b)), SUM(a*(1-b)*c) rules and also
    # handles math wrappers (ROUND, ABS, CEILING, FLOOR, GREATEST, LEAST).
    ("rule_aggx_complex", rule_aggx_complex),
    # Single-column aggregates (distinct before count, count before sum).
    ("rule_count_distinct", rule_count_distinct),
    ("rule_count_star", rule_count_star),
    ("rule_count", rule_count),
    ("rule_sum", rule_sum),
    ("rule_avg", rule_avg),
    ("rule_min", rule_min),
    ("rule_max", rule_max),
]


def apply_rules(sql: str, ctx: RuleContext) -> tuple[str | None, str | None]:
    for name, fn in _RULES:
        try:
            dax = fn(sql, ctx)
        except ValueError:
            # A column referenced by name isn't on the host table — that rule
            # can't apply; try the next one.
            continue
        if dax is not None:
            return dax, name
    return None, None
