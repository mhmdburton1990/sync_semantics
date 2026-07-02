"""Published-model side: run DAX via the Power BI executeQueries endpoint."""

from __future__ import annotations

import time
from typing import Any, Protocol

import requests

# executeQueries occasionally returns a transient 5xx ("An error has occurred.");
# retry a couple of times with a short backoff before giving up.
_MAX_RETRIES = 2
_RETRY_BACKOFF_S = 1.5

__all__ = [
    "DaxQueryClient",
    "DaxQueryError",
    "groupby_dax",
    "parse_rows",
    "scalar_dax",
]

_EXECUTE_URL = (
    "https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}"
    "/datasets/{dataset_id}/executeQueries"
)
_MEASURE_ALIAS = "[m]"


class _AuthLike(Protocol):
    def bearer_token(self) -> str: ...


class DaxQueryError(RuntimeError):
    """Raised when executeQueries returns a non-OK response."""


def scalar_dax(measure: str, date_filter: str | None = None) -> str:
    expr = f"CALCULATE([{measure}], {date_filter})" if date_filter else f"[{measure}]"
    return f'EVALUATE ROW("m", {expr})'


def groupby_dax(
    measure: str, dax_table: str, dax_column: str, date_filter: str | None = None,
) -> str:
    # NOTE: names must not contain ']' or "'" — they come from model metadata
    # (Databricks dimension/column names), which never do in practice.
    expr = f"CALCULATE([{measure}], {date_filter})" if date_filter else f"[{measure}]"
    return (
        f"EVALUATE SUMMARIZECOLUMNS('{dax_table}'[{dax_column}], "
        f'"m", {expr})'
    )


def _to_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def parse_rows(
    rows: list[dict[str, Any]], *, dim_key: str | None,
) -> dict[str | None, float | None]:
    out: dict[str | None, float | None] = {}
    for row in rows:
        value = _to_float(row.get(_MEASURE_ALIAS))
        if dim_key is None:
            out[None] = value
        else:
            raw = row.get(dim_key)
            out[None if raw is None else str(raw)] = value
    return out


def _rows_from(body: dict[str, Any]) -> list[dict[str, Any]]:
    results = body.get("results") or []
    if not results:
        return []
    tables = results[0].get("tables") or []
    if not tables:
        return []
    rows: list[dict[str, Any]] = tables[0].get("rows") or []
    return rows


def _explain_execute_error(status_code: int, body: str) -> str:
    """Turn an executeQueries failure into an actionable message.

    A ``DatasetExecuteQueriesError`` on a freshly-published model OFTEN means the
    dataset's Databricks data-source credentials are not authorized in the Power
    BI Service — a one-time manual step. But it's a generic error code that also
    covers transient/capacity issues, so we keep the credentials hint AND surface
    the raw Power BI error so the real cause is visible (not assumed).
    """
    if "DatasetExecuteQueriesError" in body:
        return (
            "Power BI could not query the published dataset. If this persists, its "
            "Databricks data-source credentials are likely not authorized in the "
            "Power BI Service — open the dataset there (Settings → Data source "
            "credentials → Sign in), then re-validate. "
            f"Raw error (HTTP {status_code}): {body[:600]}"
        )
    return f"executeQueries failed: HTTP {status_code}: {body[:1000]}"


class DaxQueryClient:
    def __init__(
        self,
        *,
        workspace_id: str,
        dataset_id: str,
        auth: _AuthLike,
        session: requests.Session | None = None,
        timeout_s: int = 60,
    ) -> None:
        self._url = _EXECUTE_URL.format(workspace_id=workspace_id, dataset_id=dataset_id)
        self._auth = auth
        self._session = session or requests.Session()
        self._timeout = timeout_s

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._auth.bearer_token()}",
            "Content-Type": "application/json",
        }

    def _run(self, dax: str) -> list[dict[str, Any]]:
        payload = {
            "queries": [{"query": dax}],
            "serializerSettings": {"includeNulls": True},
        }
        for attempt in range(_MAX_RETRIES + 1):
            resp = self._session.post(
                self._url, json=payload, headers=self._headers(), timeout=self._timeout,
            )
            if resp.ok:
                return _rows_from(resp.json())
            # Retry transient failures: 5xx, 429 throttling, and the generic
            # DatasetExecuteQueriesError (often a just-published model still
            # warming up or a capacity blip — not always a credentials problem).
            body = resp.text or ""
            transient = (
                resp.status_code >= 500
                or resp.status_code == 429
                or "DatasetExecuteQueriesError" in body
            )
            if transient and attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_S * (attempt + 1))
                continue
            raise DaxQueryError(_explain_execute_error(resp.status_code, body))
        raise DaxQueryError("executeQueries: retries exhausted")  # pragma: no cover

    def scalar(self, measure: str, date_filter: str | None = None) -> float | None:
        rows = self._run(scalar_dax(measure, date_filter))
        return parse_rows(rows, dim_key=None).get(None)

    def by_dim(
        self, measure: str, dax_table: str, dax_column: str,
        date_filter: str | None = None,
    ) -> dict[str | None, float | None]:
        rows = self._run(groupby_dax(measure, dax_table, dax_column, date_filter))
        return parse_rows(rows, dim_key=f"{dax_table}[{dax_column}]")
