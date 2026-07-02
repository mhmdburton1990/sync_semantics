from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from databricks_to_pbi.translator.cache import TranslationCache
from databricks_to_pbi.translator.sql_to_dax import (
    ClaudeClient,
    translate_measure,
)


def _columns() -> dict[str, list[str]]:
    return {"Sales": ["amount", "net_amount", "status", "customer_id"]}


def test_rule_path_used_for_simple_sum(tmp_path: Path) -> None:
    cache = TranslationCache(path=tmp_path / "c.json")
    result = translate_measure(
        sql="SUM(amount)",
        table_context="Sales",
        measure_name="Total Sales",
        columns_by_table=_columns(),
        cache=cache,
        client=None,
    )
    assert result.method == "rule"
    assert result.dax == "SUM('Sales'[amount])"


def test_cache_hit_skips_rules(tmp_path: Path) -> None:
    import hashlib
    cache = TranslationCache(path=tmp_path / "c.json")
    cache.set(
        "Sales::Total Sales::" + hashlib.sha256(b"SUM(amount)").hexdigest()[:16],
        dax="SUM('Sales'[amount])",
        method="rule",
        warnings=[],
    )
    result = translate_measure(
        sql="SUM(amount)",
        table_context="Sales",
        measure_name="Total Sales",
        columns_by_table=_columns(),
        cache=cache,
        client=None,
    )
    assert result.method == "cache"


def test_placeholder_when_no_rule_and_no_client(tmp_path: Path) -> None:
    cache = TranslationCache(path=tmp_path / "c.json")
    result = translate_measure(
        sql="LAG(amount, 1) OVER (ORDER BY order_date)",
        table_context="Sales",
        measure_name="Prev Day Sales",
        columns_by_table=_columns(),
        cache=cache,
        client=None,
    )
    assert result.method == "placeholder"
    assert "MANUAL" in result.dax
    assert any("requires manual review" in w for w in result.warnings)


def test_llm_fallback_invoked_when_client_provided(tmp_path: Path) -> None:
    cache = TranslationCache(path=tmp_path / "c.json")
    client = MagicMock(spec=ClaudeClient)
    client.translate.return_value = "CALCULATE(SUM('Sales'[amount]), 'Sales'[status] = \"prior\")"

    result = translate_measure(
        sql="SUM(amount) - LAG(SUM(amount), 1) OVER ()",
        table_context="Sales",
        measure_name="Sales Delta",
        columns_by_table=_columns(),
        cache=cache,
        client=client,
    )
    client.translate.assert_called_once()
    assert result.method == "llm"
    assert "CALCULATE" in result.dax
