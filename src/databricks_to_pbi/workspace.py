"""Thin wrapper around databricks-sdk; the only seam through which the engine
talks to Databricks. Tests substitute mocks here."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from typing import Any, Protocol

from databricks.sdk.service.sql import StatementParameterListItem, StatementState

__all__ = ["QueryCanceled", "WorkspaceClient"]

# execute_statement only waits up to this long synchronously; queries that run
# longer (e.g. a cold serverless warehouse computing a metric-view MEASURE())
# come back PENDING with no result, so we poll until a terminal state.
_SYNC_WAIT = "50s"
_POLL_INTERVAL_S = 2.0
_POLL_DEADLINE_S = 300.0
_RUNNING_STATES = frozenset({StatementState.PENDING, StatementState.RUNNING})
_FAILED_STATES = frozenset(
    {StatementState.FAILED, StatementState.CANCELED, StatementState.CLOSED}
)


class QueryCanceled(RuntimeError):
    """Raised when an in-flight statement is cancelled via the cancel hook."""


class _SdkLike(Protocol):
    """Minimal protocol covering the parts of databricks.sdk.WorkspaceClient we use."""

    statement_execution: Any
    lakeview: Any
    genie: Any
    tables: Any


class WorkspaceClient:
    def __init__(self, *, sdk_client: _SdkLike, warehouse_id: str = "") -> None:
        # warehouse_id may be empty for routes that only need SDK pass-through
        # (listing tables/dashboards/spaces). _execute() validates at the point
        # where it's actually needed.
        self._sdk = sdk_client
        self._warehouse_id = warehouse_id
        self._should_cancel: Callable[[], bool] | None = None

    @property
    def warehouse_id(self) -> str:
        return self._warehouse_id

    def set_cancel_check(self, check: Callable[[], bool] | None) -> None:
        """Install a predicate polled while awaiting a statement; when it returns
        True the running statement is cancelled and QueryCanceled is raised."""
        self._should_cancel = check

    def describe_extended(self, fully_qualified_name: str) -> list[list[str]]:
        return self._execute(f"DESCRIBE EXTENDED {fully_qualified_name}")

    def describe_columns(
        self, fully_qualified_name: str,
    ) -> list[tuple[str, str]]:
        """Return ``[(column_name, data_type), ...]`` for a UC table.

        Implemented via ``DESCRIBE TABLE``, which returns column rows followed
        by partition/comment metadata rows. We stop at the first blank-name
        row that marks the metadata section.
        """
        rows = self._execute(f"DESCRIBE TABLE {fully_qualified_name}")
        out: list[tuple[str, str]] = []
        for r in rows:
            if not r:
                break
            name = str(r[0]) if r[0] is not None else ""
            if not name or name.startswith("#"):
                break
            dtype = str(r[1]) if len(r) > 1 and r[1] is not None else ""
            out.append((name, dtype))
        return out

    def run_query(
        self, statement: str, parameters: dict[str, Any] | None = None,
    ) -> list[list[Any]]:
        return self._execute(statement, parameters)

    def _execute(
        self, statement: str, parameters: dict[str, Any] | None = None,
    ) -> list[list[Any]]:
        if not self._warehouse_id:
            raise ValueError(
                "no warehouse_id configured on this WorkspaceClient — "
                "cannot execute SQL"
            )
        kwargs: dict[str, Any] = {}
        if parameters:
            kwargs["parameters"] = [
                StatementParameterListItem(
                    name=k, value=None if v is None else str(v),
                )
                for k, v in parameters.items()
            ]
        resp = self._sdk.statement_execution.execute_statement(
            statement=statement,
            warehouse_id=self._warehouse_id,
            wait_timeout=_SYNC_WAIT,
            **kwargs,
        )
        resp = self._await_terminal(resp)
        result = getattr(resp, "result", None)
        if result is None:
            return []
        return list(result.data_array or [])

    def _await_terminal(self, resp: Any) -> Any:
        """Poll until the statement reaches a terminal state.

        A statement that finishes within the synchronous wait (and every mocked
        response in the tests) already carries a ``result``, so we return it
        untouched. Only a still-running statement (``result is None`` and a
        PENDING/RUNNING status) is polled via ``get_statement``. A FAILED /
        CANCELED / CLOSED statement raises so callers get the real SQL error
        instead of an ``AttributeError`` on a missing result.
        """
        if getattr(resp, "result", None) is not None:
            return resp
        statement_id = getattr(resp, "statement_id", None)
        state = getattr(getattr(resp, "status", None), "state", None)
        if statement_id is None or state is None:
            return resp
        deadline = time.monotonic() + _POLL_DEADLINE_S
        while state in _RUNNING_STATES:
            if self._should_cancel is not None and self._should_cancel():
                # statement may have just finished; cancel anyway and unwind
                with contextlib.suppress(Exception):
                    self._sdk.statement_execution.cancel_execution(statement_id)
                raise QueryCanceled(f"statement {statement_id} canceled by user")
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"statement {statement_id} did not finish within "
                    f"{int(_POLL_DEADLINE_S)}s"
                )
            time.sleep(_POLL_INTERVAL_S)
            resp = self._sdk.statement_execution.get_statement(statement_id)
            state = getattr(getattr(resp, "status", None), "state", None)
        if state in _FAILED_STATES:
            err = getattr(getattr(resp.status, "error", None), "message", None)
            raise RuntimeError(f"statement {statement_id} {state}: {err or 'no detail'}")
        return resp
