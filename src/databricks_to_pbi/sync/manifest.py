"""Persistent sync state: manifests in a UC volume + the in-model annotation half."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from databricks_to_pbi.ir import SourceRef

__all__ = [
    "LockHandle",
    "LockHeldError",
    "Manifest",
    "ManifestEntry",
    "RunHistoryStub",
    "TargetDescriptor",
    "acquire_lock",
    "compute_etag",
    "is_stale_lock",
    "load_manifest",
    "release_lock",
    "save_manifest",
]

CURRENT_SCHEMA_VERSION = 1


class TargetDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["pbip", "pbit", "xmla"]
    target_id: str

    def slug(self) -> str:
        return hashlib.sha256(f"{self.kind}::{self.target_id}".encode()).hexdigest()[:16]


class ManifestEntry(BaseModel):
    target_object_path: str
    source_refs: list[SourceRef]
    object_hash: str
    translation_method: Literal["rule", "cache", "llm", "placeholder", "n/a"] | None
    last_action: Literal["created", "updated", "unchanged", "renamed"]
    last_synced_at: datetime


class RunHistoryStub(BaseModel):
    run_id: str
    finished_at: datetime
    summary: str


class Manifest(BaseModel):
    schema_version: int
    target: TargetDescriptor
    last_run_id: str
    last_synced_at: datetime
    entries: list[ManifestEntry]
    run_history: list[RunHistoryStub]
    etag: str


def compute_etag(entries: list[ManifestEntry]) -> str:
    payload = "|".join(f"{e.target_object_path}:{e.object_hash}" for e in entries)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _manifest_path(target: TargetDescriptor, root: Path) -> Path:
    return root / "manifests" / f"{target.slug()}.json"


def load_manifest(target: TargetDescriptor, *, root: Path) -> Manifest | None:
    p = _manifest_path(target, root)
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    m = Manifest.model_validate(raw)
    if m.schema_version != CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"manifest schema_version {m.schema_version} != supported {CURRENT_SCHEMA_VERSION}"
        )
    return m


def save_manifest(m: Manifest, *, root: Path) -> None:
    p = _manifest_path(m.target, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(m.model_dump_json(indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Sentinel-file advisory lock
# ---------------------------------------------------------------------------


class LockHeldError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class LockHandle:
    path: Path
    run_id: str


def _lock_path(target: TargetDescriptor, root: Path) -> Path:
    return root / "manifests" / f"{target.slug()}.lock"


def is_stale_lock(path: Path, *, max_age: timedelta = timedelta(minutes=30)) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return True
    acquired = datetime.fromisoformat(payload["acquired_at"])
    return datetime.now(UTC) - acquired > max_age


def acquire_lock(target: TargetDescriptor, *, run_id: str, root: Path) -> LockHandle:
    p = _lock_path(target, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and not is_stale_lock(p):
        raise LockHeldError(f"lock already held: {p}")
    payload = {"run_id": run_id, "acquired_at": datetime.now(UTC).isoformat()}
    p.write_text(json.dumps(payload), encoding="utf-8")
    return LockHandle(path=p, run_id=run_id)


def release_lock(handle: LockHandle) -> None:
    if handle.path.exists():
        handle.path.unlink()
