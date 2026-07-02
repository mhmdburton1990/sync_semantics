from __future__ import annotations

from datetime import UTC, datetime

from databricks_to_pbi.ir import Measure, SourceRef
from databricks_to_pbi.sync.diff import (
    compute_measure_plan,
)
from databricks_to_pbi.sync.manifest import ManifestEntry


def _src(name: str = "main.sales.mv1", h: str = "h1") -> SourceRef:
    return SourceRef(
        kind="metric_view",
        fully_qualified_name=name,
        object_hash=h,
        fetched_at=datetime(2026, 5, 26, tzinfo=UTC),
    )


def _measure(name: str, sql: str, src: SourceRef) -> Measure:
    return Measure(
        name=name,
        sql_expression=sql,
        dependencies=[],
        description=None,
        format_string=None,
        source=src,
    )


def _prior(name: str, h: str) -> ManifestEntry:
    return ManifestEntry(
        target_object_path=f"Measures/{name}",
        source_refs=[_src(h=h)],
        object_hash=h,
        translation_method="rule",
        last_action="created",
        last_synced_at=datetime(2026, 5, 26, tzinfo=UTC),
    )


def test_new_measure_yields_create() -> None:
    plan = compute_measure_plan(
        current=[_measure("Total", "SUM(amount)", _src(h="hA"))],
        prior=[],
    )
    assert plan.ops[0].action == "create"


def test_unchanged_measure_yields_unchanged() -> None:
    plan = compute_measure_plan(
        current=[_measure("Total", "SUM(amount)", _src(h="hA"))],
        prior=[_prior("Total", "hA")],
    )
    assert plan.ops[0].action == "unchanged"


def test_changed_hash_yields_update() -> None:
    plan = compute_measure_plan(
        current=[_measure("Total", "SUM(net_amount)", _src(h="hB"))],
        prior=[_prior("Total", "hA")],
    )
    assert plan.ops[0].action == "update"


def test_disappeared_measure_yields_delete() -> None:
    plan = compute_measure_plan(
        current=[],
        prior=[_prior("Total", "hA")],
    )
    assert plan.ops[0].action == "delete"


def test_high_confidence_rename_detected() -> None:
    plan = compute_measure_plan(
        current=[_measure("TotalSales", "SUM(amount)", _src(h="hA"))],
        prior=[_prior("Total", "hOLD")],
    )
    assert plan.ops[0].action == "rename"
    assert plan.ops[0].from_name == "Total"
    assert plan.ops[0].to_name == "TotalSales"
