from __future__ import annotations

import pytest

from databricks_to_pbi.errors import (
    EngineError,
    FatalEngineError,
    StructuredError,
    SyncConflictError,
    TranslationError,
)


def test_structured_error_carries_suggestion() -> None:
    err = StructuredError(
        code="XMLA_AUTH_FAILED",
        message="Workspace XMLA endpoint rejected the bearer token.",
        suggestion=(
            "Configure a Fabric SP in App settings or grant PBI connection 'Build' permission."
        ),
        docs_link="https://learn.microsoft.com/power-bi/admin/service-premium-connect-tools",
    )
    assert err.code == "XMLA_AUTH_FAILED"
    assert "Fabric SP" in err.suggestion


def test_engine_error_chain_preserves_cause() -> None:
    cause = ValueError("bad yaml")
    err = EngineError("metric view definition is malformed", cause=cause)
    assert err.__cause__ is cause


def test_translation_error_includes_measure_name() -> None:
    err = TranslationError("Window functions unsupported", measure_name="rolling_avg")
    assert err.measure_name == "rolling_avg"


def test_sync_conflict_error_has_run_id_pointer() -> None:
    err = SyncConflictError("manifest changed since read", winning_run_id="abc-123")
    assert err.winning_run_id == "abc-123"


def test_fatal_engine_error_is_engine_error() -> None:
    err = FatalEngineError("xmla endpoint unreachable")
    assert isinstance(err, EngineError)


@pytest.mark.parametrize(
    "exc_cls",
    [EngineError, FatalEngineError, TranslationError, SyncConflictError],
)
def test_all_engine_errors_are_exceptions(exc_cls: type[Exception]) -> None:
    assert issubclass(exc_cls, Exception)
