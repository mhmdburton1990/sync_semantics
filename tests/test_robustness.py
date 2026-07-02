from __future__ import annotations

from pathlib import Path

import pytest

from databricks_to_pbi.ir import (
    Column,
    DatabricksSemanticIR,
)
from databricks_to_pbi.translator.cache import TranslationCache
from databricks_to_pbi.translator.rules import RuleContext, apply_rules
from databricks_to_pbi.translator.sql_to_dax import translate_measure


def test_empty_ir_translates_zero_measures() -> None:
    ir = DatabricksSemanticIR(
        name="x", description=None,
        tables=[], dimensions=[], measures=[], relationships=[],
        genie=None, sources=[],
    )
    assert ir.measures == []


def test_unicode_measure_name_survives_translation(tmp_path: Path) -> None:
    cache = TranslationCache(path=tmp_path / "c.json")
    result = translate_measure(
        sql="SUM(amount)",
        table_context="Sales",
        measure_name="売上合計",
        columns_by_table={"Sales": ["amount"]},
        cache=cache,
        client=None,
    )
    assert result.method == "rule"
    assert "売上合計" not in result.dax


def test_malformed_sql_falls_back_to_placeholder(tmp_path: Path) -> None:
    cache = TranslationCache(path=tmp_path / "c.json")
    result = translate_measure(
        sql="((( SUM",
        table_context="Sales",
        measure_name="bad",
        columns_by_table={"Sales": ["amount"]},
        cache=cache,
        client=None,
    )
    assert result.method == "placeholder"


def test_rule_returns_none_for_empty_string() -> None:
    ctx = RuleContext(table="T", columns_by_table={"T": ["a"]})
    dax, name = apply_rules("", ctx)
    assert dax is None and name is None


@pytest.mark.parametrize(
    "data_type", ["DECIMAL(38,18)", "STRING", "TIMESTAMP", "BIGINT", "BOOLEAN"]
)
def test_column_data_types_are_accepted(data_type: str) -> None:
    Column(name="x", uc_path=None, data_type=data_type)
