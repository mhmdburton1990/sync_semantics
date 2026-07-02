"""Concrete Anthropic-backed implementation of the ClaudeClient Protocol."""

from __future__ import annotations

import os
import re
from typing import Any

import anthropic

from databricks_to_pbi.translator.sql_to_dax import ClaudeClient

__all__ = ["AnthropicClaudeClient", "load_from_env"]


_SYSTEM_PROMPT = (
    "You translate Databricks SQL aggregation expressions to Power BI DAX measure expressions.\n"
    "\n"
    "Rules:\n"
    "- Output ONLY the DAX expression — no commentary, no markdown fences.\n"
    "- Qualify columns as 'TableName'[column_name]."
    " The table the measure attaches to is provided.\n"
    "- If the SQL cannot be translated faithfully (window functions, multi-row subqueries,\n"
    "  cross-table CTEs), return EXACTLY `// MANUAL: <one-line reason>`.\n"
    "- Prefer DAX idioms: DIVIDE() for ratios, CALCULATE(... , filter) for conditional sums,\n"
    "  SUMX() for row-by-row.\n"
)


def _build_user_message(
    *,
    sql: str,
    table_context: str,
    columns_by_table: dict[str, list[str]],
    measure_name: str,
) -> str:
    cols = columns_by_table.get(table_context, [])
    other_tables = {t: c for t, c in columns_by_table.items() if t != table_context}
    parts = [
        f"Measure name: {measure_name}",
        f"Host table: {table_context}",
        f"Host table columns: {', '.join(cols) or '(none)'}",
    ]
    if other_tables:
        parts.append("Other tables in scope:")
        for t, c in other_tables.items():
            parts.append(f"  {t}: {', '.join(c)}")
    parts.append("")
    parts.append("SQL to translate:")
    parts.append(sql)
    return "\n".join(parts)


_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$", re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


class AnthropicClaudeClient:
    def __init__(self, *, sdk: Any, model: str = "claude-opus-4-7") -> None:
        self._sdk = sdk
        self._model = model

    def translate(
        self,
        *,
        sql: str,
        table_context: str,
        columns_by_table: dict[str, list[str]],
        measure_name: str,
    ) -> str:
        user_msg = _build_user_message(
            sql=sql,
            table_context=table_context,
            columns_by_table=columns_by_table,
            measure_name=measure_name,
        )
        resp = self._sdk.messages.create(
            model=self._model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content)
        return _strip_fences(text)


# Static check that AnthropicClaudeClient satisfies the ClaudeClient Protocol.
# mypy will error here if the structural type doesn't match.
def _check_protocol_conformance(c: AnthropicClaudeClient) -> ClaudeClient:
    return c


def load_from_env(*, model: str = "claude-opus-4-7") -> AnthropicClaudeClient | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    sdk = anthropic.Anthropic()
    return AnthropicClaudeClient(sdk=sdk, model=model)
