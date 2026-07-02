from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.sql import StatementState

from databricks_to_pbi.workspace import WorkspaceClient


def test_get_table_definition_delegates_to_sdk() -> None:
    fake_sdk = MagicMock()
    fake_sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(data_array=[["col_name", "data_type", "comment"]])
    )
    wc = WorkspaceClient(sdk_client=fake_sdk, warehouse_id="wh-1")

    wc.describe_extended("main.sales.metrics_view")

    fake_sdk.statement_execution.execute_statement.assert_called_once()
    call = fake_sdk.statement_execution.execute_statement.call_args
    assert "DESCRIBE EXTENDED" in call.kwargs["statement"]
    assert "main.sales.metrics_view" in call.kwargs["statement"]


def test_describe_extended_returns_rows() -> None:
    fake_sdk = MagicMock()
    fake_sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(data_array=[["a", "1"], ["b", "2"]])
    )
    wc = WorkspaceClient(sdk_client=fake_sdk, warehouse_id="wh-1")
    rows = wc.describe_extended("x.y.z")
    assert rows == [["a", "1"], ["b", "2"]]


def test_run_query_returns_rows() -> None:
    fake_sdk = MagicMock()
    fake_sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(data_array=[[1, 2, 3]])
    )
    wc = WorkspaceClient(sdk_client=fake_sdk, warehouse_id="wh-1")
    rows = wc.run_query("SELECT 1, 2, 3")
    assert rows == [[1, 2, 3]]


def test_empty_warehouse_id_allowed_at_construction() -> None:
    # SDK-only call sites (list tables/dashboards/spaces) build a WorkspaceClient
    # without a warehouse. The constructor accepts this; only _execute raises.
    fake_sdk = MagicMock()
    wc = WorkspaceClient(sdk_client=fake_sdk, warehouse_id="")
    assert wc.warehouse_id == ""


def test_execute_raises_when_warehouse_id_empty() -> None:
    fake_sdk = MagicMock()
    wc = WorkspaceClient(sdk_client=fake_sdk, warehouse_id="")
    with pytest.raises(ValueError, match="warehouse_id"):
        wc.run_query("SELECT 1")


def test_run_query_polls_pending_statement_until_succeeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # execute_statement returns PENDING with no result (slow query exceeded the
    # synchronous wait); _execute must poll get_statement until it completes.
    monkeypatch.setattr("databricks_to_pbi.workspace.time.sleep", lambda _s: None)
    fake_sdk = MagicMock()
    fake_sdk.statement_execution.execute_statement.return_value = MagicMock(
        statement_id="stmt-1",
        result=None,
        status=MagicMock(state=StatementState.PENDING),
    )
    fake_sdk.statement_execution.get_statement.side_effect = [
        MagicMock(result=None, status=MagicMock(state=StatementState.RUNNING)),
        MagicMock(
            result=MagicMock(data_array=[[42]]),
            status=MagicMock(state=StatementState.SUCCEEDED),
        ),
    ]
    wc = WorkspaceClient(sdk_client=fake_sdk, warehouse_id="wh-1")

    rows = wc.run_query("SELECT MEASURE(`m`) FROM v")

    assert rows == [[42]]
    assert fake_sdk.statement_execution.get_statement.call_count == 2


def test_run_query_raises_on_failed_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("databricks_to_pbi.workspace.time.sleep", lambda _s: None)
    fake_sdk = MagicMock()
    fake_sdk.statement_execution.execute_statement.return_value = MagicMock(
        statement_id="stmt-2",
        result=None,
        status=MagicMock(state=StatementState.PENDING),
    )
    fake_sdk.statement_execution.get_statement.return_value = MagicMock(
        result=None,
        status=MagicMock(
            state=StatementState.FAILED,
            error=MagicMock(message="syntax error near MEASURE"),
        ),
    )
    wc = WorkspaceClient(sdk_client=fake_sdk, warehouse_id="wh-1")

    with pytest.raises(RuntimeError, match="syntax error near MEASURE"):
        wc.run_query("SELECT MEASURE(`bad`) FROM v")


def test_run_query_cancels_in_flight_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from databricks_to_pbi.workspace import QueryCanceled

    monkeypatch.setattr("databricks_to_pbi.workspace.time.sleep", lambda _s: None)
    fake_sdk = MagicMock()
    fake_sdk.statement_execution.execute_statement.return_value = MagicMock(
        statement_id="stmt-9", result=None,
        status=MagicMock(state=StatementState.PENDING),
    )
    fake_sdk.statement_execution.get_statement.return_value = MagicMock(
        result=None, status=MagicMock(state=StatementState.RUNNING),
    )
    wc = WorkspaceClient(sdk_client=fake_sdk, warehouse_id="wh-1")
    wc.set_cancel_check(lambda: True)  # cancel requested immediately

    with pytest.raises(QueryCanceled):
        wc.run_query("SELECT MEASURE(`m`) FROM v")
    fake_sdk.statement_execution.cancel_execution.assert_called_once_with("stmt-9")


def test_run_query_cancel_swallows_cancel_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from databricks_to_pbi.workspace import QueryCanceled

    monkeypatch.setattr("databricks_to_pbi.workspace.time.sleep", lambda _s: None)
    fake_sdk = MagicMock()
    fake_sdk.statement_execution.execute_statement.return_value = MagicMock(
        statement_id="stmt-x", result=None,
        status=MagicMock(state=StatementState.PENDING),
    )
    fake_sdk.statement_execution.get_statement.return_value = MagicMock(
        result=None, status=MagicMock(state=StatementState.RUNNING),
    )
    fake_sdk.statement_execution.cancel_execution.side_effect = RuntimeError("already done")
    wc = WorkspaceClient(sdk_client=fake_sdk, warehouse_id="wh-1")
    wc.set_cancel_check(lambda: True)

    with pytest.raises(QueryCanceled):  # cancel_execution error swallowed, still cancels
        wc.run_query("SELECT 1")


def test_run_query_passes_named_parameters() -> None:
    from unittest.mock import MagicMock

    from databricks_to_pbi.workspace import WorkspaceClient

    sdk = MagicMock()
    sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(data_array=[["ok"]]),
    )
    wc = WorkspaceClient(sdk_client=sdk, warehouse_id="wh-1")

    wc.run_query("SELECT :a AS a", parameters={"a": "hello", "b": None})

    kwargs = sdk.statement_execution.execute_statement.call_args.kwargs
    params = kwargs["parameters"]
    assert {p.name: p.value for p in params} == {"a": "hello", "b": None}


def test_run_query_without_parameters_omits_kwarg() -> None:
    from unittest.mock import MagicMock

    from databricks_to_pbi.workspace import WorkspaceClient

    sdk = MagicMock()
    sdk.statement_execution.execute_statement.return_value = MagicMock(
        result=MagicMock(data_array=[]),
    )
    wc = WorkspaceClient(sdk_client=sdk, warehouse_id="wh-1")

    wc.run_query("SELECT 1")

    kwargs = sdk.statement_execution.execute_statement.call_args.kwargs
    assert "parameters" not in kwargs
