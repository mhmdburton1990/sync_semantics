from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from databricks_to_pbi.sync.manifest import (
    LockHeldError,
    Manifest,
    ManifestEntry,
    TargetDescriptor,
    acquire_lock,
    is_stale_lock,
    load_manifest,
    release_lock,
    save_manifest,
)


def _entry(name: str = "Measures/Total Sales", hash_: str = "h1") -> ManifestEntry:
    return ManifestEntry(
        target_object_path=name,
        source_refs=[],
        object_hash=hash_,
        translation_method="rule",
        last_action="created",
        last_synced_at=datetime(2026, 5, 26, tzinfo=UTC),
    )


def test_manifest_roundtrip(tmp_path: Path) -> None:
    target = TargetDescriptor(kind="pbip", target_id="/abs/path/SalesModel")
    m = Manifest(
        schema_version=1,
        target=target,
        last_run_id="r1",
        last_synced_at=datetime(2026, 5, 26, tzinfo=UTC),
        entries=[_entry()],
        run_history=[],
        etag="e1",
    )
    save_manifest(m, root=tmp_path)

    reloaded = load_manifest(target, root=tmp_path)
    assert reloaded is not None
    assert reloaded.entries[0].target_object_path == "Measures/Total Sales"
    assert reloaded.etag == "e1"


def test_load_missing_manifest_returns_none(tmp_path: Path) -> None:
    target = TargetDescriptor(kind="pbip", target_id="/nope")
    assert load_manifest(target, root=tmp_path) is None


def test_schema_version_mismatch_raises(tmp_path: Path) -> None:
    target = TargetDescriptor(kind="pbip", target_id="/x")
    m = Manifest(
        schema_version=99,
        target=target,
        last_run_id="r1",
        last_synced_at=datetime(2026, 5, 26, tzinfo=UTC),
        entries=[],
        run_history=[],
        etag="e",
    )
    save_manifest(m, root=tmp_path)
    with pytest.raises(ValueError, match="schema_version"):
        load_manifest(target, root=tmp_path)


def test_acquire_and_release_lock(tmp_path: Path) -> None:
    target = TargetDescriptor(kind="pbip", target_id="/x")
    handle = acquire_lock(target, run_id="r-1", root=tmp_path)
    with pytest.raises(LockHeldError):
        acquire_lock(target, run_id="r-2", root=tmp_path)
    release_lock(handle)
    handle2 = acquire_lock(target, run_id="r-3", root=tmp_path)
    release_lock(handle2)


def test_stale_lock_can_be_taken_over(tmp_path: Path) -> None:
    target = TargetDescriptor(kind="pbip", target_id="/x")
    handle = acquire_lock(target, run_id="r-old", root=tmp_path)
    handle.path.write_text(
        '{"run_id":"r-old","acquired_at":"2020-01-01T00:00:00+00:00"}',
        encoding="utf-8",
    )
    assert is_stale_lock(handle.path, max_age=timedelta(minutes=30))
    handle2 = acquire_lock(target, run_id="r-new", root=tmp_path)
    assert handle2.run_id == "r-new"
    release_lock(handle2)
