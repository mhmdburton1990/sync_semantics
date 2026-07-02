from __future__ import annotations

from pathlib import Path

import pytest

from databricks_to_pbi.translator.cache import TranslationCache, cache_key


def test_cache_key_is_stable_for_same_inputs() -> None:
    k1 = cache_key(table="Sales", measure_name="Total", sql="SUM(amount)")
    k2 = cache_key(table="Sales", measure_name="Total", sql="SUM(amount)")
    assert k1 == k2


def test_cache_key_changes_when_sql_changes() -> None:
    k1 = cache_key(table="Sales", measure_name="Total", sql="SUM(amount)")
    k2 = cache_key(table="Sales", measure_name="Total", sql="SUM(net_amount)")
    assert k1 != k2


def test_cache_roundtrip_persists_entries(tmp_path: Path) -> None:
    cache_file = tmp_path / "sql_to_dax.json"
    cache = TranslationCache(path=cache_file)
    cache.set("Sales::Total::deadbeef", dax="SUM('Sales'[amount])", method="rule", warnings=[])
    cache.save()

    reloaded = TranslationCache.load(cache_file)
    entry = reloaded.get("Sales::Total::deadbeef")
    assert entry is not None
    assert entry.dax == "SUM('Sales'[amount])"
    assert entry.method == "rule"
    assert entry.warnings == []


def test_cache_missing_key_returns_none(tmp_path: Path) -> None:
    cache = TranslationCache(path=tmp_path / "x.json")
    assert cache.get("nope") is None


def test_cache_load_from_missing_file_returns_empty(tmp_path: Path) -> None:
    cache = TranslationCache.load(tmp_path / "absent.json")
    assert cache.get("any") is None


def test_cache_rejects_invalid_method(tmp_path: Path) -> None:
    cache = TranslationCache(path=tmp_path / "c.json")
    with pytest.raises(ValueError):
        cache.set("k", dax="x", method="invented", warnings=[])  # type: ignore[arg-type]


def test_load_ignores_malformed_non_dict_entries(tmp_path: Path) -> None:
    # A corrupt/unexpected cache shape (e.g. a stray scalar like an old
    # {"version": 1, ...} wrapper) must not crash load() — skip non-entry values.
    import json

    p = tmp_path / "sql_to_dax.json"
    p.write_text(json.dumps({
        "version": 1,  # stray scalar — must be ignored, not crash
        "t::good::abc": {"dax": "[x]", "method": "rule", "warnings": []},
    }), encoding="utf-8")
    cache = TranslationCache.load(p)
    assert cache.get("t::good::abc") is not None
    assert cache.get("t::good::abc").dax == "[x]"
