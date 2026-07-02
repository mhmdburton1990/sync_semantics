from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from databricks_to_pbi.ir import (
    Column,
    DatabricksSemanticIR,
    Measure,
    SourceRef,
    Table,
)
from databricks_to_pbi.sync.engine import SyncInputs, run_sync
from databricks_to_pbi.sync.manifest import TargetDescriptor
from databricks_to_pbi.translator.cache import TranslationCache


def _ir() -> DatabricksSemanticIR:
    src = SourceRef(
        kind="metric_view",
        fully_qualified_name="main.sales.mv",
        object_hash="h1",
        fetched_at=datetime(2026, 5, 26, tzinfo=UTC),
    )
    return DatabricksSemanticIR(
        name="Sales", description=None,
        tables=[Table(name="Orders", uc_path="main.sales.orders", sql_definition=None,
                      storage_mode="direct_query",
                      columns=[Column(name="amount", uc_path=None, data_type="DOUBLE")],
                      description=None, source=src)],
        dimensions=[],
        measures=[Measure(name="Total Sales", sql_expression="SUM(amount)",
                          dependencies=[], description=None, format_string=None, source=src)],
        relationships=[], genie=None, sources=[src],
    )


def test_preview_run_produces_report_without_writing_files(tmp_path: Path) -> None:
    target = TargetDescriptor(kind="pbip", target_id=str(tmp_path / "out"))
    cache = TranslationCache(path=tmp_path / "uc_volume" / "caches" / "sql_to_dax.json")
    inputs = SyncInputs(ir=_ir(), target=target, mode="preview")

    report = run_sync(
        inputs=inputs, cache=cache, uc_volume_root=tmp_path / "uc_volume", claude=None
    )

    assert not (tmp_path / "out").exists()
    assert report.summary.created == 1
    assert report.mode == "preview"


def test_preview_translates_with_rule_and_caches(tmp_path: Path) -> None:
    target = TargetDescriptor(kind="pbip", target_id=str(tmp_path / "out"))
    cache_path = tmp_path / "uc_volume" / "caches" / "sql_to_dax.json"
    cache = TranslationCache(path=cache_path)
    inputs = SyncInputs(ir=_ir(), target=target, mode="preview")

    report = run_sync(
        inputs=inputs, cache=cache, uc_volume_root=tmp_path / "uc_volume", claude=None
    )
    cache.save()

    assert any(o.translation_method == "rule" for o in report.outcomes)
    assert cache_path.exists()


def test_apply_writes_pbip_and_persists_manifest(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    target = TargetDescriptor(kind="pbip", target_id=str(out_dir))
    cache = TranslationCache(path=tmp_path / "uc_volume" / "caches" / "sql_to_dax.json")
    inputs = SyncInputs(ir=_ir(), target=target, mode="apply")

    report = run_sync(
        inputs=inputs, cache=cache, uc_volume_root=tmp_path / "uc_volume", claude=None
    )

    assert (out_dir / "Sales.SemanticModel" / "definition" / "model.tmdl").exists()
    manifest_files = list((tmp_path / "uc_volume" / "manifests").glob("*.json"))
    assert len(manifest_files) == 1
    assert report.mode == "apply"


def test_second_apply_is_unchanged_when_inputs_identical(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    target = TargetDescriptor(kind="pbip", target_id=str(out_dir))
    cache = TranslationCache(path=tmp_path / "uc_volume" / "caches" / "sql_to_dax.json")

    run_sync(
        inputs=SyncInputs(ir=_ir(), target=target, mode="apply"),
        cache=cache, uc_volume_root=tmp_path / "uc_volume", claude=None,
    )
    report2 = run_sync(
        inputs=SyncInputs(ir=_ir(), target=target, mode="apply"),
        cache=cache, uc_volume_root=tmp_path / "uc_volume", claude=None,
    )
    assert report2.summary.unchanged >= 1
    assert report2.summary.created == 0


def _partial_ir(
    *,
    name: str = "Sales",
    table_name: str = "Orders",
    uc_path: str = "main.sales.orders",
    measure_name: str = "Total Sales",
    measure_sql: str = "SUM(amount)",
    source_fqn: str = "main.sales.mv",
    source_hash: str = "h1",
) -> DatabricksSemanticIR:
    src = SourceRef(
        kind="metric_view",
        fully_qualified_name=source_fqn,
        object_hash=source_hash,
        fetched_at=datetime(2026, 5, 26, tzinfo=UTC),
    )
    return DatabricksSemanticIR(
        name=name,
        description=None,
        tables=[
            Table(
                name=table_name,
                uc_path=uc_path,
                sql_definition=None,
                storage_mode="direct_query",
                columns=[Column(name="amount", uc_path=None, data_type="DOUBLE")],
                description=None,
                source=src,
            )
        ],
        dimensions=[],
        measures=[
            Measure(
                name=measure_name,
                sql_expression=measure_sql,
                dependencies=[],
                description=None,
                format_string=None,
                source=src,
            )
        ],
        relationships=[],
        genie=None,
        sources=[src],
    )


def test_engine_accepts_multiple_partial_irs(tmp_path: Path) -> None:
    from databricks_to_pbi.sync.engine import SyncInputsMulti, run_sync_multi

    out_dir = tmp_path / "out"
    target = TargetDescriptor(kind="pbip", target_id=str(out_dir))
    cache = TranslationCache(path=tmp_path / "uc_volume" / "caches" / "sql_to_dax.json")

    ir_mv = _partial_ir(
        name="MV",
        table_name="Orders",
        uc_path="main.sales.orders",
        source_fqn="main.sales.orders_mv",
        source_hash="h-mv",
    )
    ir_dash = _partial_ir(
        name="Dash",
        table_name="Customers",
        uc_path="main.sales.customers",
        measure_name="Cust Spend",
        source_fqn="dash-abc",
        source_hash="h-dash",
    )

    report = run_sync_multi(
        inputs=SyncInputsMulti(
            partial_irs=[ir_mv, ir_dash],
            target=target,
            mode="apply",
            target_model_name="CombinedSales",
        ),
        cache=cache,
        uc_volume_root=tmp_path / "uc_volume",
        claude=None,
    )

    sem = out_dir / "CombinedSales.SemanticModel" / "definition" / "tables"
    assert (sem / "Orders.tmdl").exists()
    assert (sem / "Customers.tmdl").exists()
    assert report.mode == "apply"


def test_engine_dispatches_pbit_delivery(tmp_path: Path) -> None:
    from databricks_to_pbi.sync.engine import SyncInputsMulti, run_sync_multi

    pbit_path = tmp_path / "out.pbit"
    target = TargetDescriptor(kind="pbit", target_id=str(pbit_path))
    cache = TranslationCache(path=tmp_path / "uc_volume" / "caches" / "sql_to_dax.json")

    report = run_sync_multi(
        inputs=SyncInputsMulti(
            partial_irs=[_partial_ir()],
            target=target,
            mode="apply",
            target_model_name="SalesModel",
        ),
        cache=cache,
        uc_volume_root=tmp_path / "uc_volume",
        claude=None,
    )

    assert pbit_path.exists()
    assert report.delivery == "pbit"


def test_engine_dispatches_xmla_create_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import databricks_to_pbi.sync.engine as engine_mod
    from databricks_to_pbi.sync.engine import SyncInputsMulti, run_sync_multi
    from databricks_to_pbi.writers.fabric_api import FabricApiResult

    target = TargetDescriptor(kind="xmla", target_id="ws-123-guid")
    cache = TranslationCache(path=tmp_path / "uc_volume" / "caches" / "sql_to_dax.json")

    fake_push = MagicMock(
        return_value=FabricApiResult(
            semantic_model_id="sm-1", state="Succeeded", operation_id=None,
        ),
    )
    monkeypatch.setattr(engine_mod, "push_semantic_model", fake_push)
    monkeypatch.setattr(engine_mod, "_build_fabric_api_client", lambda target: MagicMock())

    report = run_sync_multi(
        inputs=SyncInputsMulti(
            partial_irs=[_partial_ir()],
            target=target,
            mode="apply",
            target_model_name="SalesModel",
        ),
        cache=cache,
        uc_volume_root=tmp_path / "uc_volume",
        claude=None,
    )

    fake_push.assert_called_once()
    assert fake_push.call_args.kwargs["overwrite_existing"] is False
    assert fake_push.call_args.kwargs["display_name"] == "SalesModel"
    assert report.delivery == "xmla_create"
    assert report.published_dataset_id == "sm-1"


def test_engine_dispatches_xmla_merge_when_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import databricks_to_pbi.sync.engine as engine_mod
    from databricks_to_pbi.sync.engine import SyncInputsMulti, run_sync_multi
    from databricks_to_pbi.writers.fabric_api import FabricApiResult

    target = TargetDescriptor(kind="xmla", target_id="ws-123-guid")
    cache = TranslationCache(path=tmp_path / "uc_volume" / "caches" / "sql_to_dax.json")

    fake_push = MagicMock(
        return_value=FabricApiResult(
            semantic_model_id="sm-2", state="Succeeded", operation_id=None,
        ),
    )
    monkeypatch.setattr(engine_mod, "push_semantic_model", fake_push)
    monkeypatch.setattr(engine_mod, "_build_fabric_api_client", lambda target: MagicMock())

    report = run_sync_multi(
        inputs=SyncInputsMulti(
            partial_irs=[_partial_ir()],
            target=target,
            mode="apply",
            target_model_name="CombinedSales",
            xmla_merge=True,
        ),
        cache=cache,
        uc_volume_root=tmp_path / "uc_volume",
        claude=None,
    )
    fake_push.assert_called_once()
    assert fake_push.call_args.kwargs["overwrite_existing"] is True
    assert report.delivery == "xmla_merge"
    assert report.published_dataset_id == "sm-2"


def test_exclude_measures_drops_them_from_the_model(tmp_path: Path) -> None:
    from databricks_to_pbi.sync.engine import SyncInputsMulti, run_sync_multi

    out_dir = tmp_path / "out"
    target = TargetDescriptor(kind="pbip", target_id=str(out_dir))
    cache = TranslationCache(path=tmp_path / "uc_volume" / "caches" / "sql_to_dax.json")
    ir_a = _partial_ir(name="A", table_name="Orders", uc_path="main.s.orders",
                       measure_name="Total Sales", source_fqn="main.s.mv", source_hash="ha")
    ir_b = _partial_ir(name="B", table_name="Customers", uc_path="main.s.customers",
                       measure_name="Cust Spend", source_fqn="dash-1", source_hash="hb")

    report = run_sync_multi(
        inputs=SyncInputsMulti(
            partial_irs=[ir_a, ir_b], target=target, mode="apply",
            target_model_name="Combined", exclude_measures=frozenset({"Cust Spend"}),
        ),
        cache=cache, uc_volume_root=tmp_path / "uc_volume", claude=None,
    )
    names = [o.name for o in report.outcomes if o.object_kind == "measure"]
    assert "Total Sales" in names
    assert "Cust Spend" not in names


def test_windowed_measure_wraps_in_time_intelligence(tmp_path: Path) -> None:
    from databricks_to_pbi.ir import Dimension, WindowClause
    from databricks_to_pbi.sync.engine import SyncInputsMulti, run_sync_multi

    src = SourceRef(kind="metric_view", fully_qualified_name="c.s.mv",
                    object_hash="h", fetched_at=datetime(2026, 6, 16, tzinfo=UTC))
    line = Table(name="lineitem", uc_path="c.s.lineitem", sql_definition=None,
                 storage_mode="direct_query",
                 columns=[Column(name="l_extendedprice", uc_path=None, data_type="DOUBLE")],
                 description=None, source=src)
    cal = Table(name="calendar", uc_path="c.s.dim_calendar", sql_definition=None,
                storage_mode="direct_query",
                columns=[Column(name="date", uc_path=None, data_type="DATE")],
                description=None, source=src)
    base = Measure(name="total_sales", sql_expression="SUM(l_extendedprice)",
                   dependencies=[], description=None, format_string=None, source=src)
    win = Measure(name="running_total_sales", sql_expression="MEASURE(total_sales)",
                  dependencies=[], description=None, format_string=None, source=src,
                  window=[WindowClause(order="order_date", range="cumulative")])
    dims = [Dimension(name="order_date", expression="source.calendar.date",
                      underlying_columns=[], description=None, hierarchy=None)]
    ir = DatabricksSemanticIR(name="S", description=None, tables=[line, cal],
                              dimensions=dims, measures=[base, win], relationships=[],
                              genie=None, sources=[src])
    target = TargetDescriptor(kind="pbip", target_id=str(tmp_path / "out"))
    cache = TranslationCache(path=tmp_path / "uc" / "caches" / "sql_to_dax.json")
    report = run_sync_multi(
        inputs=SyncInputsMulti(partial_irs=[ir], target=target, mode="apply",
                               target_model_name="S"),
        cache=cache, uc_volume_root=tmp_path / "uc", claude=None,
    )
    dax = {o.name: o.dax for o in report.outcomes if o.object_kind == "measure"}
    assert dax["running_total_sales"] == (
        "CALCULATE([total_sales], FILTER(ALL('calendar'[date]), "
        "'calendar'[date] <= MAX('calendar'[date])))"
    )
    # base measure unchanged (bare-column SUM → SUM, not SUMX)
    assert dax["total_sales"] == "SUM('lineitem'[l_extendedprice])"
