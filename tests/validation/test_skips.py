from __future__ import annotations

from databricks_to_pbi.validation.skips import classify_skip


def test_dax_credentials_error_is_credentials_category() -> None:
    exc = RuntimeError("DatasetExecuteQueriesError: credentials not signed in")
    cat, hint, side = classify_skip(exc, side="dax", dim=None)
    assert cat == "credentials_not_signed_in"
    assert "Data source credentials" in hint
    assert side == "dax"


def test_dax_missing_dim_column_is_dim_not_found() -> None:
    exc = RuntimeError("Cannot find table or column 'region'")
    cat, hint, _side = classify_skip(exc, side="dax", dim="region")
    assert cat == "dim_not_found"
    assert "region" in hint


def test_dax_other_error_is_dax_error() -> None:
    cat, _hint, side = classify_skip(RuntimeError("boom"), side="dax", dim=None)
    assert cat == "dax_error"
    assert side == "dax"


def test_source_error_is_source_sql_error() -> None:
    cat, _hint, side = classify_skip(
        RuntimeError("metric view blew up"), side="source_sql", dim=None,
    )
    assert cat == "source_sql_error"
    assert side == "source_sql"


def test_dax_generic_column_error_is_not_dim_not_found() -> None:
    # A generic DAX error that merely mentions "column" must NOT be
    # mislabeled as a missing dimension.
    exc = RuntimeError("The column 'Amount' is of type Integer and cannot be summed")
    cat, _hint, side = classify_skip(exc, side="dax", dim="region")
    assert cat == "dax_error"
    assert side == "dax"


def test_dax_named_dim_in_error_is_dim_not_found() -> None:
    exc = RuntimeError("Query (1, 9) The value for 'region' cannot be determined")
    cat, hint, _side = classify_skip(exc, side="dax", dim="region")
    assert cat == "dim_not_found"
    assert "region" in hint
