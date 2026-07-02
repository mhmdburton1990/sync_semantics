"""Liveness probe + Prometheus metrics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response

from databricks_to_pbi import __version__
from databricks_to_pbi.app.observability import CONTENT_TYPE_LATEST, render_metrics

__all__ = ["router"]


router = APIRouter()


@router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/metrics")
def metrics() -> Response:
    return Response(content=render_metrics(), media_type=CONTENT_TYPE_LATEST)
