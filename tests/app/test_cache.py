from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from databricks_to_pbi.app.auth import OBO_HEADER
from databricks_to_pbi.app.deps import get_uc_volume_root
from databricks_to_pbi.app.main import create_app


@pytest.fixture
def client_with_cache(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    caches = tmp_path / "caches"
    caches.mkdir(parents=True)
    payload = {
        "version": 1,
        "entries": {
            "h1": {"dax": "SUM('A'[x])", "method": "rule"},
            "h2": {"dax": "AVERAGE('A'[x])", "method": "cache"},
        },
    }
    (caches / "sql_to_dax.json").write_text(json.dumps(payload), encoding="utf-8")

    app = create_app()
    app.dependency_overrides[get_uc_volume_root] = lambda: tmp_path
    with TestClient(app) as c:
        yield c, tmp_path


def test_cache_status_reports_entry_count(
    client_with_cache: tuple[TestClient, Path],
) -> None:
    client, _ = client_with_cache
    resp = client.get("/api/cache/status", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["entries"] == 2
    assert body["bytes"] > 0
    assert body["path"].endswith("sql_to_dax.json")


def test_cache_status_when_cache_missing(tmp_path: Path) -> None:
    app = create_app()
    app.dependency_overrides[get_uc_volume_root] = lambda: tmp_path
    with TestClient(app) as client:
        resp = client.get("/api/cache/status", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 200
    assert resp.json()["entries"] == 0


def test_clear_cache_empties_entries(
    client_with_cache: tuple[TestClient, Path],
) -> None:
    client, _ = client_with_cache
    resp = client.request("DELETE", "/api/cache", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 200
    assert resp.json()["entries"] == 0
    again = client.get("/api/cache/status", headers={OBO_HEADER: "tok"})
    assert again.json()["entries"] == 0


def test_clear_cache_writes_a_loadable_empty_cache(
    client_with_cache: tuple[TestClient, Path],
) -> None:
    # Regression: clear must write the flat format TranslationCache.load expects.
    # Writing {"version":..,"entries":..} made load() raise "'int' object is not
    # subscriptable" on the next preview/translate.
    from databricks_to_pbi.translator.cache import TranslationCache

    client, tmp = client_with_cache
    client.request("DELETE", "/api/cache", headers={OBO_HEADER: "tok"})
    cache = TranslationCache.load(tmp / "caches" / "sql_to_dax.json")  # must not raise
    assert cache.get("anything") is None


def test_clear_cache_when_missing_is_ok(tmp_path: Path) -> None:
    app = create_app()
    app.dependency_overrides[get_uc_volume_root] = lambda: tmp_path  # no caches dir
    with TestClient(app) as c:
        resp = c.request("DELETE", "/api/cache", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 200
    assert resp.json()["entries"] == 0
