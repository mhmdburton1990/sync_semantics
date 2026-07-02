from __future__ import annotations

from typing import Any

import pytest

from databricks_to_pbi.validation.dax_query import (
    DaxQueryClient,
    DaxQueryError,
    groupby_dax,
    parse_rows,
    scalar_dax,
)


def test_scalar_dax_shape() -> None:
    assert scalar_dax("Total Revenue") == 'EVALUATE ROW("m", [Total Revenue])'


def test_groupby_dax_shape() -> None:
    assert groupby_dax("Total Revenue", "orders", "region") == (
        "EVALUATE SUMMARIZECOLUMNS('orders'[region], \"m\", [Total Revenue])"
    )


def test_parse_rows_extracts_measure_alias() -> None:
    rows = [{"[m]": 100.0}]
    assert parse_rows(rows, dim_key=None) == {None: 100.0}


def test_parse_rows_groupby() -> None:
    rows = [
        {"orders[region]": "EU", "[m]": 60.0},
        {"orders[region]": "US", "[m]": 40.0},
    ]
    assert parse_rows(rows, dim_key="orders[region]") == {"EU": 60.0, "US": 40.0}


class _FakeAuth:
    def bearer_token(self) -> str:
        return "tok"


class _FakeResp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._p = payload
        self.status_code = 200
        self.ok = True

    def json(self) -> dict[str, Any]:
        return self._p


class _FakeSession:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls: list[dict[str, Any]] = []

    def post(
        self, url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: int,
    ) -> _FakeResp:
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResp(self._payload)


def _payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"results": [{"tables": [{"rows": rows}]}]}


def test_client_scalar() -> None:
    sess = _FakeSession(_payload([{"[m]": 250.0}]))
    client = DaxQueryClient(workspace_id="ws", dataset_id="ds", auth=_FakeAuth(), session=sess)  # type: ignore[arg-type]
    assert client.scalar("Rev") == 250.0
    assert "groups/ws/datasets/ds/executeQueries" in sess.calls[0]["url"]
    assert sess.calls[0]["headers"]["Authorization"] == "Bearer tok"


def test_client_by_dim() -> None:
    sess = _FakeSession(_payload([
        {"orders[region]": "EU", "[m]": 60.0},
        {"orders[region]": "US", "[m]": 40.0},
    ]))
    client = DaxQueryClient(workspace_id="ws", dataset_id="ds", auth=_FakeAuth(), session=sess)  # type: ignore[arg-type]
    assert client.by_dim("Rev", "orders", "region") == {"EU": 60.0, "US": 40.0}


class _FakeErrResp:
    def __init__(self) -> None:
        self.ok = False
        self.status_code = 403
        self.text = "forbidden"

    def json(self) -> dict[str, object]:
        return {}


class _FakeErrSession:
    def post(self, url: str, *, json: object, headers: object, timeout: int) -> _FakeErrResp:
        return _FakeErrResp()


def test_client_raises_on_non_ok() -> None:
    client = DaxQueryClient(
        workspace_id="ws", dataset_id="ds", auth=_FakeAuth(),
        session=_FakeErrSession(),  # type: ignore[arg-type]
    )
    with pytest.raises(DaxQueryError):
        client.scalar("Rev")


def test_scalar_dax_with_date_filter() -> None:
    pred = "'orders'[o_orderdate] >= DATE(1997,8,2) && 'orders'[o_orderdate] <= DATE(1998,8,2)"
    assert scalar_dax("Total Revenue", pred) == (
        'EVALUATE ROW("m", CALCULATE([Total Revenue], '
        "'orders'[o_orderdate] >= DATE(1997,8,2) && 'orders'[o_orderdate] <= DATE(1998,8,2)))"
    )


def test_groupby_dax_with_date_filter() -> None:
    pred = "'orders'[o_orderdate] >= DATE(1997,8,2)"
    assert groupby_dax("Total Revenue", "orders", "region", pred) == (
        "EVALUATE SUMMARIZECOLUMNS('orders'[region], "
        '"m", CALCULATE([Total Revenue], '
        "'orders'[o_orderdate] >= DATE(1997,8,2)))"
    )


def test_client_scalar_with_date_filter() -> None:
    pred = "'orders'[o_orderdate] >= DATE(1997,8,2) && 'orders'[o_orderdate] <= DATE(1998,8,2)"
    sess = _FakeSession(_payload([{"[m]": 42.0}]))
    client = DaxQueryClient(workspace_id="ws", dataset_id="ds", auth=_FakeAuth(), session=sess)  # type: ignore[arg-type]
    assert client.scalar("Rev", date_filter=pred) == 42.0
    query_sent = sess.calls[0]["json"]["queries"][0]["query"]
    assert "CALCULATE([Rev], " in query_sent


def test_explain_execute_error_credentials_hint() -> None:
    from databricks_to_pbi.validation.dax_query import _explain_execute_error
    body = '{"error":{"code":"DatasetExecuteQueriesError","pbi.error":{}}}'
    msg = _explain_execute_error(400, body)
    assert "data-source credentials" in msg
    assert "Sign in" in msg


def test_explain_execute_error_generic() -> None:
    from databricks_to_pbi.validation.dax_query import _explain_execute_error
    msg = _explain_execute_error(503, "service unavailable")
    assert "HTTP 503" in msg


def test_client_retries_on_transient_5xx(monkeypatch: object) -> None:
    monkeypatch.setattr("databricks_to_pbi.validation.dax_query.time.sleep", lambda _s: None)  # type: ignore[attr-defined]

    class _Resp:
        def __init__(self, code: int, payload: dict[str, object]) -> None:
            self.status_code = code
            self.ok = code < 400
            self.text = "An error has occurred."
            self._p = payload

        def json(self) -> dict[str, object]:
            return self._p

    seq = [_Resp(500, {}), _Resp(200, _payload([{"[m]": 7.0}]))]

    class _Sess:
        def __init__(self) -> None:
            self.n = 0

        def post(self, url: str, *, json: object, headers: object, timeout: int) -> _Resp:
            r = seq[self.n]
            self.n += 1
            return r

    client = DaxQueryClient(workspace_id="w", dataset_id="d", auth=_FakeAuth(), session=_Sess())  # type: ignore[arg-type]
    assert client.scalar("Rev") == 7.0  # recovered after one 500


def test_explain_execute_error_includes_raw_body() -> None:
    from databricks_to_pbi.validation.dax_query import _explain_execute_error
    body = '{"error":{"code":"DatasetExecuteQueriesError","message":"Resource exceeded"}}'
    msg = _explain_execute_error(400, body)
    assert "data-source credentials" in msg  # keep the actionable hint
    assert "Resource exceeded" in msg         # but ALSO surface the real error


def test_client_retries_on_transient_dataset_execute_error(monkeypatch: object) -> None:
    monkeypatch.setattr("databricks_to_pbi.validation.dax_query.time.sleep", lambda _s: None)  # type: ignore[attr-defined]

    class _Resp:
        def __init__(self, code: int, payload: dict[str, object], text: str) -> None:
            self.status_code = code
            self.ok = code < 400
            self.text = text
            self._p = payload

        def json(self) -> dict[str, object]:
            return self._p

    seq = [
        _Resp(400, {}, '{"error":{"code":"DatasetExecuteQueriesError"}}'),
        _Resp(200, _payload([{"[m]": 9.0}]), "ok"),
    ]

    class _Sess:
        def __init__(self) -> None:
            self.n = 0

        def post(self, url: str, *, json: object, headers: object, timeout: int) -> _Resp:
            r = seq[self.n]
            self.n += 1
            return r

    client = DaxQueryClient(workspace_id="w", dataset_id="d", auth=_FakeAuth(), session=_Sess())  # type: ignore[arg-type]
    assert client.scalar("Rev") == 9.0  # recovered after one transient DatasetExecuteQueriesError
