"""Shared pytest fixtures for databricks-to-pbi."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_history_ensured_cache() -> None:
    from databricks_to_pbi.history import store as _store
    _store._ensured_tables.clear()


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_uc_volume(tmp_path: Path) -> Path:
    """Mimic a UC volume rooted at tmp_path. Manifests + caches live under here."""
    vol = tmp_path / "uc_volume" / "dbx2pbi"
    vol.mkdir(parents=True)
    (vol / "manifests").mkdir()
    (vol / "caches").mkdir()
    (vol / "reports").mkdir()
    return vol
