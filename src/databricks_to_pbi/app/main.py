"""FastAPI application factory + uvicorn entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from databricks_to_pbi.app.errors import install_error_handlers
from databricks_to_pbi.app.observability import configure_logging
from databricks_to_pbi.app.routers import (
    cache,
    fabric,
    health,
    history,
    sources,
    sync,
    warehouses,
)
from databricks_to_pbi.app.static import mount_frontend

__all__ = ["create_app"]


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="sync_semantics",
        description=(
            "Sync Databricks semantic layer into a Power BI semantic model "
            "(part of sync_semantics: PBI <-> Databricks two-way sync)."
        ),
        version="0.3.0",
    )
    install_error_handlers(app)
    app.include_router(cache.router)
    app.include_router(fabric.router)
    app.include_router(health.router)
    app.include_router(history.router)
    app.include_router(sources.router)
    app.include_router(sync.router)
    app.include_router(warehouses.router)
    mount_frontend(app)
    return app


app = create_app()
