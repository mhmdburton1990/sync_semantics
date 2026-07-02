from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from databricks_to_pbi.history.store import (
    RunHistoryStore,
    history_table_name,
    namespace_from_sources,
)
from databricks_to_pbi.reporting.report import (
    ErrorEntry,
    ObjectOutcome,
    SummaryStats,
    SyncReport,
)
from databricks_to_pbi.sync.manifest import TargetDescriptor


class _CapturingWC:
    """Records (statement, parameters) and returns canned rows."""

    def __init__(self, rows: list[list[Any]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self._rows = rows or []

    def run_query(
        self, statement: str, parameters: dict[str, Any] | None = None,
    ) -> list[list[Any]]:
        self.calls.append((statement, parameters))
        return self._rows


def _report(run_id: str = "r-1") -> SyncReport:
    return SyncReport(
        run_id=run_id,
        started_at=datetime(2026, 6, 11, 9, 0, tzinfo=UTC),
        finished_at=datetime(2026, 6, 11, 9, 1, tzinfo=UTC),
        target=TargetDescriptor(kind="xmla", target_id="ws-1"),
        target_model_name="Sales",
        mode="apply",
        delivery="xmla_create",
        summary=SummaryStats(created=2, updated=1, needs_manual_review=1),
        outcomes=[
            ObjectOutcome(
                object_kind="measure", name="total", action="created",
                source_refs=[], translation_method="rule", warnings=[],
                needs_manual_review=False, diff_preview=None,
            ),
            ObjectOutcome(
                object_kind="measure", name="avg", action="created",
                source_refs=[], translation_method="llm", warnings=[],
                needs_manual_review=False, diff_preview=None,
            ),
        ],
        errors=[],
        fatal_error=None,
        source_inventory=[],
        published_dataset_id="ds-9",
    )


def test_history_table_name_builds_fqn() -> None:
    assert history_table_name("specialists_sessions", "dss_tpch") == (
        "specialists_sessions.dss_tpch.run_history"
    )


def test_namespace_from_sources_takes_first_fqn() -> None:
    assert namespace_from_sources(["specialists_sessions.dss_tpch.tpch_mv"]) == (
        ("specialists_sessions", "dss_tpch")
    )


def test_namespace_from_sources_none_when_not_fqn() -> None:
    assert namespace_from_sources(["dashboard-abc123"]) is None
    assert namespace_from_sources([]) is None


def test_record_apply_creates_table_then_inserts() -> None:
    wc = _CapturingWC()
    store = RunHistoryStore(wc=wc, table="cat.sch.run_history")

    store.record_apply(_report(), run_by="alice@x.com")

    stmts = [c[0] for c in wc.calls]
    assert any("CREATE TABLE IF NOT EXISTS cat.sch.run_history" in s for s in stmts)
    create = next(c[0] for c in wc.calls if "CREATE TABLE" in c[0])
    # Managed UC table: no external LOCATION/path.
    assert "LOCATION" not in create.upper()
    insert = next(c for c in wc.calls if c[0].lstrip().startswith("INSERT"))
    params = insert[1] or {}
    assert params["run_id"] == "r-1"
    assert params["state"] == "published"
    assert params["measures_created"] == "2"
    assert '"rule": 1' in params["method_breakdown"]
    assert '"llm": 1' in params["method_breakdown"]
    assert params["validation_status"] == "not_run"


def test_record_apply_failed_state_when_fatal() -> None:
    wc = _CapturingWC()
    store = RunHistoryStore(wc=wc, table="cat.sch.run_history")
    rep = _report().model_copy(
        update={"fatal_error": ErrorEntry(code="boom", message="bad")},
    )
    store.record_apply(rep, run_by=None)
    insert = next(c for c in wc.calls if c[0].lstrip().startswith("INSERT"))
    assert (insert[1] or {})["state"] == "failed"


def test_list_runs_parses_rows() -> None:
    rows = [
        [
            "r-2", "2026-06-11 09:05:00", "Sales", "published",
            "0", "3", "0", "passed", "3", "0", "1",
        ],
    ]
    wc = _CapturingWC(rows=rows)
    store = RunHistoryStore(wc=wc, table="cat.sch.run_history")

    out = store.list_runs(limit=50)

    assert len(out) == 1
    assert out[0].run_id == "r-2"
    assert out[0].measures_updated == 3
    assert out[0].validation_status == "passed"
    assert out[0].val_skipped == 1
    select = next(c for c in wc.calls if "SELECT" in c[0])
    assert (select[1] or {})["limit"] == "50"
    # LIMIT must cast the (string-bound) param to INT — Databricks rejects a
    # STRING limit expression (INVALID_LIMIT_LIKE_EXPRESSION.DATA_TYPE).
    assert "LIMIT CAST(:limit AS INT)" in select[0]


def test_record_validation_merges_verdict() -> None:
    from databricks_to_pbi.validation.models import (
        MeasureValidation,
        ValidationReport,
        ValidationSummary,
    )

    wc = _CapturingWC()
    store = RunHistoryStore(wc=wc, table="cat.sch.run_history")
    rep = ValidationReport(
        model="Sales", dataset_id="ds-9", workspace_id="ws-1", epsilon=1e-6,
        ran_at=datetime(2026, 6, 11, 10, 0, tzinfo=UTC),
        results=[MeasureValidation(name="total", status="passed")],
        summary=ValidationSummary(passed=1, failed=0, skipped=2),
    )

    store.record_validation("r-1", rep, dimension="region", timeframe="month")

    merge = next(c for c in wc.calls if c[0].lstrip().startswith("MERGE"))
    params = merge[1] or {}
    assert params["run_id"] == "r-1"
    assert params["validation_status"] == "passed"
    assert params["val_skipped"] == "2"
    assert params["val_dimension"] == "region"
    assert params["val_timeframe"] == "month"


def test_get_run_returns_none_when_missing() -> None:
    wc = _CapturingWC(rows=[])
    store = RunHistoryStore(wc=wc, table="cat.sch.run_history")
    assert store.get_run("nope") is None


def test_get_run_parses_detail_row() -> None:
    rows = [[
        "r-1", "2026-06-11 09:00:00", "alice@x.com", "Sales", "xmla_create",
        "published", "passed", '{"run_id":"r-1"}', '{"model":"Sales"}',
        "region", "quarter",
    ]]
    wc = _CapturingWC(rows=rows)
    store = RunHistoryStore(wc=wc, table="cat.sch.run_history")
    detail = store.get_run("r-1")
    assert detail is not None
    assert detail.run_by == "alice@x.com"
    assert detail.delivery == "xmla_create"
    assert detail.validation_json == '{"model":"Sales"}'
    assert detail.val_dimension == "region"
    assert detail.val_timeframe == "quarter"
