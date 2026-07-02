"""Structured error types raised by the engine. Surfaced in SyncReport."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "EngineError",
    "FatalEngineError",
    "StructuredError",
    "SyncConflictError",
    "TranslationError",
]


@dataclass(frozen=True, slots=True)
class StructuredError:
    """User-facing error payload (code/message/suggestion/docs_link)."""

    code: str
    message: str
    suggestion: str
    docs_link: str | None = None


class EngineError(Exception):
    """Base class for recoverable engine errors. Caller decides per-object vs. fatal."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        if cause is not None:
            self.__cause__ = cause


class FatalEngineError(EngineError):
    """Aborts the run. Triggers atomic rollback in writers."""


class TranslationError(EngineError):
    """SQL→DAX translation failed."""

    def __init__(self, message: str, *, measure_name: str | None = None) -> None:
        super().__init__(message)
        self.measure_name = measure_name


class SyncConflictError(EngineError):
    """Another run modified the manifest while this one was building its plan."""

    def __init__(self, message: str, *, winning_run_id: str | None = None) -> None:
        super().__init__(message)
        self.winning_run_id = winning_run_id
