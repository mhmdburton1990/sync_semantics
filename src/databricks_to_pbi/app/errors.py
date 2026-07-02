"""Structured error envelope and FastAPI exception handlers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

__all__ = ["AppError", "install_error_handlers"]


_logger = logging.getLogger(__name__)


class AppError(Exception):
    """User-facing error carrying the spec's envelope contract."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        suggestion: str | None = None,
        docs_link: str | None = None,
        status_code: int = 400,
    ) -> None:
        self.code = code
        self.message = message
        self.suggestion = suggestion
        self.docs_link = docs_link
        self.status_code = status_code
        super().__init__(message)

    def to_envelope(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "suggestion": self.suggestion,
            "docs_link": self.docs_link,
        }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_envelope())

    @app.exception_handler(Exception)
    async def _generic_handler(_: Request, exc: Exception) -> JSONResponse:
        _logger.exception("unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "An internal error occurred; check the App logs for run_id.",
                "suggestion": None,
                "docs_link": None,
            },
        )
