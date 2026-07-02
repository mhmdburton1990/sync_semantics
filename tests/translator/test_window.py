from __future__ import annotations

from databricks_to_pbi.ir import WindowClause
from databricks_to_pbi.translator.window import translate_window

DATE = "'calendar'[date]"
INNER = "[total_sales]"


def test_trailing_n_day() -> None:
    w = [WindowClause(order="order_date", range="trailing 7 day inclusive")]
    assert translate_window(INNER, w, DATE) == (
        "CALCULATE([total_sales], DATESINPERIOD('calendar'[date], "
        "MAX('calendar'[date]), -7, DAY))"
    )


def test_cumulative_running_total() -> None:
    w = [WindowClause(order="order_date", range="cumulative")]
    assert translate_window(INNER, w, DATE) == (
        "CALCULATE([total_sales], FILTER(ALL('calendar'[date]), "
        "'calendar'[date] <= MAX('calendar'[date])))"
    )


def test_cumulative_plus_current_year_is_ytd() -> None:
    w = [
        WindowClause(order="order_date", range="cumulative"),
        WindowClause(order="order_year", range="current"),
    ]
    assert translate_window(INNER, w, DATE) == (
        "CALCULATE([total_sales], DATESYTD('calendar'[date]))"
    )


def test_trailing_30_day() -> None:
    w = [WindowClause(order="order_date", range="trailing 30 day inclusive")]
    out = translate_window(INNER, w, DATE) or ""
    assert "DATESINPERIOD('calendar'[date], MAX('calendar'[date]), -30, DAY)" in out


def test_unrecognized_window_returns_none() -> None:
    odd = [WindowClause(order="order_date", range="trailing 3 fortnight")]
    assert translate_window(INNER, odd, DATE) is None
    assert translate_window(INNER, [], DATE) is None
