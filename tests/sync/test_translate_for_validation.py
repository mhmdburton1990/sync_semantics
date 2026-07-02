from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from databricks_to_pbi.ir import (
    Column,
    DatabricksSemanticIR,
    Measure,
    SourceRef,
    Table,
)
from databricks_to_pbi.sync.engine import translate_for_validation
from databricks_to_pbi.translator.cache import TranslationCache


def _src() -> SourceRef:
    return SourceRef(kind="metric_view", fully_qualified_name="main.s.mv",
                     object_hash="h", fetched_at=datetime(2026, 6, 3, tzinfo=UTC))


def test_translate_for_validation_returns_method_per_measure(tmp_path: Path) -> None:
    table = Table(name="orders", uc_path="main.s.orders", sql_definition=None,
                  columns=[Column(name="amount", uc_path=None, data_type="double", role="fact")],
                  description=None, source=_src())
    ir = DatabricksSemanticIR(
        name="sales", description=None, tables=[table], dimensions=[],
        measures=[Measure(name="rev", sql_expression="SUM(amount)", dependencies=[],
                          description=None, format_string=None, source=_src())],
        relationships=[], sources=[_src()],
    )
    cache = TranslationCache(path=tmp_path / "c.json")
    methods = translate_for_validation(ir, cache, None)
    assert set(methods.keys()) == {"rev"}
    assert methods["rev"] in {"rule", "cache", "llm", "placeholder"}
