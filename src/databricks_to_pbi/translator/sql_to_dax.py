"""Translate a SQL measure expression to DAX.

Pipeline:
  1. Compute cache key. If cache hit → return (method='cache').
  2. Apply rules. If a rule matches → cache + return (method='rule').
  3. If a Claude client is provided → call LLM, cache, return (method='llm').
  4. Else return placeholder with warnings; do NOT cache (so a later run with
     a client populates cleanly).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from databricks_to_pbi.translator.cache import TranslationCache, cache_key
from databricks_to_pbi.translator.rules import RuleContext, apply_rules

__all__ = ["ClaudeClient", "TranslationResult", "translate_measure"]


class ClaudeClient(Protocol):
    def translate(
        self,
        *,
        sql: str,
        table_context: str,
        columns_by_table: dict[str, list[str]],
        measure_name: str,
    ) -> str:
        ...


@dataclass(frozen=True, slots=True)
class TranslationResult:
    dax: str
    method: Literal["rule", "cache", "llm", "placeholder"]
    warnings: list[str]


_PLACEHOLDER_DAX = "// MANUAL: rule-set did not match; LLM unavailable"


def translate_measure(
    *,
    sql: str,
    table_context: str,
    measure_name: str,
    columns_by_table: dict[str, list[str]],
    cache: TranslationCache,
    client: ClaudeClient | None,
    keys_by_table: dict[str, str] | None = None,
    dimensions: dict[str, str] | None = None,
) -> TranslationResult:
    key = cache_key(table=table_context, measure_name=measure_name, sql=sql)

    cached = cache.get(key)
    if cached is not None:
        return TranslationResult(dax=cached.dax, method="cache", warnings=list(cached.warnings))

    ctx = RuleContext(
        table=table_context,
        columns_by_table=columns_by_table,
        keys_by_table=keys_by_table or {},
        dimensions=dimensions or {},
    )
    dax, _rule_name = apply_rules(sql, ctx)
    if dax is not None:
        cache.set(key, dax=dax, method="rule", warnings=[])
        return TranslationResult(dax=dax, method="rule", warnings=[])

    if client is not None:
        dax_llm = client.translate(
            sql=sql,
            table_context=table_context,
            columns_by_table=columns_by_table,
            measure_name=measure_name,
        )
        if dax_llm.strip().startswith("// MANUAL"):
            warnings = [f"{measure_name}: LLM returned a manual-review marker"]
            cache.set(key, dax=dax_llm, method="llm", warnings=warnings)
            return TranslationResult(dax=dax_llm, method="llm", warnings=warnings)
        cache.set(key, dax=dax_llm, method="llm", warnings=[])
        return TranslationResult(dax=dax_llm, method="llm", warnings=[])

    warnings = [f"{measure_name}: SQL→DAX requires manual review"]
    return TranslationResult(dax=_PLACEHOLDER_DAX, method="placeholder", warnings=warnings)
