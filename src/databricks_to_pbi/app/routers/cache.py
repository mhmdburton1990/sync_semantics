"""GET /api/cache/status — translation cache stats."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends

from databricks_to_pbi.app.auth import current_obo_token
from databricks_to_pbi.app.deps import get_uc_volume_root
from databricks_to_pbi.app.models import CacheStatus

__all__ = ["router"]


router = APIRouter(
    prefix="/api/cache",
    tags=["cache"],
    dependencies=[Depends(current_obo_token)],
)


@router.get("/status", response_model=CacheStatus)
def cache_status(
    uc_volume: Path = Depends(get_uc_volume_root),  # noqa: B008
) -> CacheStatus:
    path = uc_volume / "caches" / "sql_to_dax.json"
    if not path.exists():
        return CacheStatus(entries=0, bytes=0, path=str(path))
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    entries = len(parsed.get("entries", {})) if isinstance(parsed, dict) else 0
    return CacheStatus(entries=entries, bytes=len(raw.encode("utf-8")), path=str(path))


@router.delete("", response_model=CacheStatus)
def clear_cache(
    uc_volume: Path = Depends(get_uc_volume_root),  # noqa: B008
) -> CacheStatus:
    """Empty the SQL→DAX translation cache so the next sync recomputes fresh.
    The cache is a single file for the whole volume, so this is global."""
    path = uc_volume / "caches" / "sql_to_dax.json"
    if not path.exists():
        return CacheStatus(entries=0, bytes=0, path=str(path))
    # TranslationCache stores a FLAT {key: {dax,...}} dict, so an empty cache is
    # `{}` — NOT a wrapped {"version":..,"entries":..}, which TranslationCache.load
    # would try to iterate as entries and crash on the int "version" value.
    empty = "{}"
    path.write_text(empty, encoding="utf-8")
    return CacheStatus(entries=0, bytes=len(empty.encode("utf-8")), path=str(path))
