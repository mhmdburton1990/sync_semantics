"""RunHistoryStore — persist one row per migration in a UC Delta table.

The store is the only seam between run history and Databricks; it talks to a
single Delta table through an engine ``WorkspaceClient`` using parameterized
SQL. Apply inserts a row; validation MERGEs its verdict into the same row.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from databricks_to_pbi.reporting.report import SyncReport
from databricks_to_pbi.validation.models import ValidationReport

__all__ = [
    "HISTORY_TABLE_BASENAME",
    "SCHEMA_VERSION",
    "RunDetailRow",
    "RunHistoryStore",
    "RunListRow",
    "history_table_name",
    "namespace_from_sources",
]

# Run history lives in the SAME catalog AND schema as the migrated source, so it
# inherits that namespace's governance and the schema is guaranteed to exist
# (we create the table, never the schema).
HISTORY_TABLE_BASENAME = "run_history"
SCHEMA_VERSION = 1

_ensured_tables: set[str] = set()


def history_table_name(catalog: str, schema: str) -> str:
    """Fully-qualified run_history table in ``catalog.schema``."""
    return f"{catalog}.{schema}.{HISTORY_TABLE_BASENAME}"


def namespace_from_sources(source_ids: Iterable[str]) -> tuple[str, str] | None:
    """First source whose id is a UC fully-qualified name (``cat.schema.obj``)
    yields its ``(catalog, schema)``. Non-FQN sources (e.g. dashboard ids)
    yield ``None``."""
    for sid in source_ids:
        parts = sid.split(".")
        if len(parts) >= 3 and all(parts):
            return parts[0], parts[1]
    return None


class _WCLike(Protocol):
    def run_query(
        self, statement: str, parameters: dict[str, Any] | None = None,
    ) -> list[list[Any]]: ...


@dataclass(frozen=True, slots=True)
class RunListRow:
    run_id: str
    created_at: datetime
    model_name: str | None
    state: str
    measures_created: int
    measures_updated: int
    needs_manual_review: int
    validation_status: str
    val_passed: int
    val_failed: int
    val_skipped: int


@dataclass(frozen=True, slots=True)
class RunDetailRow:
    run_id: str
    created_at: datetime
    run_by: str | None
    model_name: str | None
    delivery: str
    state: str
    validation_status: str
    report_json: str | None
    validation_json: str | None
    val_dimension: str | None = None
    val_timeframe: str | None = None


_CREATE_COLS = """(
    run_id STRING,
    created_at TIMESTAMP,
    run_by STRING,
    model_name STRING,
    delivery STRING,
    state STRING,
    workspace_id STRING,
    dataset_id STRING,
    measures_created INT,
    measures_updated INT,
    needs_manual_review INT,
    method_breakdown STRING,
    validation_status STRING,
    val_passed INT,
    val_failed INT,
    val_skipped INT,
    val_dimension STRING,
    val_timeframe STRING,
    validated_at TIMESTAMP,
    report_json STRING,
    validation_json STRING,
    schema_version INT
)"""

_LIST_COLS = (
    "run_id, created_at, model_name, state, measures_created, "
    "measures_updated, needs_manual_review, validation_status, "
    "val_passed, val_failed, val_skipped"
)


def _to_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _to_dt(v: Any) -> datetime:
    return datetime.fromisoformat(str(v))


def _derive_state(report: SyncReport) -> str:
    if report.fatal_error is not None:
        return "failed"
    if report.delivery in ("xmla_create", "xmla_merge"):
        return "published" if report.published_dataset_id else "published_failed"
    return "exported"


def _method_breakdown(report: SyncReport) -> str:
    counts: Counter[str] = Counter(
        o.translation_method or "n/a"
        for o in report.outcomes
        if o.object_kind == "measure"
    )
    return json.dumps(dict(sorted(counts.items())))


class RunHistoryStore:
    def __init__(self, *, wc: _WCLike, table: str) -> None:
        self._wc = wc
        self._table = table

    def ensure_table(self) -> None:
        if self._table in _ensured_tables:
            return
        # UC managed Delta table: no LOCATION, so Unity Catalog owns storage
        # and lifecycle. Do not add an external path here.
        self._wc.run_query(
            f"CREATE TABLE IF NOT EXISTS {self._table} {_CREATE_COLS} USING DELTA"
        )
        _ensured_tables.add(self._table)

    def record_apply(self, report: SyncReport, *, run_by: str | None) -> None:
        self.ensure_table()
        params: dict[str, Any] = {
            "run_id": report.run_id,
            "created_at": report.started_at.isoformat(),
            "run_by": run_by,
            "model_name": report.target_model_name,
            "delivery": report.delivery,
            "state": _derive_state(report),
            "workspace_id": report.target.target_id,
            "dataset_id": report.published_dataset_id,
            "measures_created": str(report.summary.created),
            "measures_updated": str(report.summary.updated),
            "needs_manual_review": str(report.summary.needs_manual_review),
            "method_breakdown": _method_breakdown(report),
            "validation_status": "not_run",
            "report_json": report.model_dump_json(),
            "schema_version": str(SCHEMA_VERSION),
        }
        self._wc.run_query(
            f"""INSERT INTO {self._table} (
                run_id, created_at, run_by, model_name, delivery, state,
                workspace_id, dataset_id, measures_created, measures_updated,
                needs_manual_review, method_breakdown, validation_status,
                val_passed, val_failed, val_skipped, val_dimension,
                val_timeframe, validated_at, report_json, validation_json,
                schema_version
            ) VALUES (
                :run_id, CAST(:created_at AS TIMESTAMP), :run_by, :model_name,
                :delivery, :state, :workspace_id, :dataset_id,
                CAST(:measures_created AS INT), CAST(:measures_updated AS INT),
                CAST(:needs_manual_review AS INT), :method_breakdown,
                :validation_status, 0, 0, 0, NULL, NULL, NULL, :report_json,
                NULL, CAST(:schema_version AS INT)
            )""",
            params,
        )

    def record_validation(
        self,
        run_id: str,
        report: ValidationReport,
        *,
        dimension: str | None,
        timeframe: str,
    ) -> None:
        self.ensure_table()
        s = report.summary
        if s.failed > 0:
            status = "failed"
        elif s.passed > 0:
            status = "passed"
        else:
            status = "partial"
        params: dict[str, Any] = {
            "run_id": run_id,
            "validation_status": status,
            "val_passed": str(s.passed),
            "val_failed": str(s.failed),
            "val_skipped": str(s.skipped),
            "val_dimension": dimension,
            "val_timeframe": timeframe,
            "validated_at": report.ran_at.isoformat(),
            "validation_json": report.model_dump_json(),
        }
        self._wc.run_query(
            f"""MERGE INTO {self._table} t
            USING (SELECT :run_id AS run_id) s
            ON t.run_id = s.run_id
            WHEN MATCHED THEN UPDATE SET
                validation_status = :validation_status,
                val_passed = CAST(:val_passed AS INT),
                val_failed = CAST(:val_failed AS INT),
                val_skipped = CAST(:val_skipped AS INT),
                val_dimension = :val_dimension,
                val_timeframe = :val_timeframe,
                validated_at = CAST(:validated_at AS TIMESTAMP),
                validation_json = :validation_json""",
            params,
        )

    def list_runs(self, limit: int = 100) -> list[RunListRow]:
        self.ensure_table()
        rows = self._wc.run_query(
            f"SELECT {_LIST_COLS} FROM {self._table} "
            "ORDER BY created_at DESC LIMIT CAST(:limit AS INT)",
            {"limit": str(limit)},
        )
        return [self._list_row(r) for r in rows]

    def get_run(self, run_id: str) -> RunDetailRow | None:
        self.ensure_table()
        rows = self._wc.run_query(
            "SELECT run_id, created_at, run_by, model_name, delivery, state, "
            "validation_status, report_json, validation_json, val_dimension, "
            f"val_timeframe FROM {self._table} "
            "WHERE run_id = :run_id LIMIT 1",
            {"run_id": run_id},
        )
        if not rows:
            return None
        r = rows[0]
        return RunDetailRow(
            run_id=str(r[0]),
            created_at=_to_dt(r[1]),
            run_by=None if r[2] is None else str(r[2]),
            model_name=None if r[3] is None else str(r[3]),
            delivery=str(r[4]),
            state=str(r[5]),
            validation_status=str(r[6]),
            report_json=None if r[7] is None else str(r[7]),
            validation_json=None if r[8] is None else str(r[8]),
            val_dimension=None if r[9] is None else str(r[9]),
            val_timeframe=None if r[10] is None else str(r[10]),
        )

    @staticmethod
    def _list_row(r: Sequence[Any]) -> RunListRow:
        return RunListRow(
            run_id=str(r[0]),
            created_at=_to_dt(r[1]),
            model_name=None if r[2] is None else str(r[2]),
            state=str(r[3]),
            measures_created=_to_int(r[4]),
            measures_updated=_to_int(r[5]),
            needs_manual_review=_to_int(r[6]),
            validation_status=str(r[7]),
            val_passed=_to_int(r[8]),
            val_failed=_to_int(r[9]),
            val_skipped=_to_int(r[10]),
        )
