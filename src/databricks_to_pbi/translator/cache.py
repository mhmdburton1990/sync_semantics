"""On-disk JSON cache for translated DAX, keyed by sha256(sql)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

__all__ = ["TranslationCache", "TranslationEntry", "cache_key"]

_VALID_METHODS: set[str] = {"rule", "cache", "llm", "placeholder"}


@dataclass(frozen=True, slots=True)
class TranslationEntry:
    dax: str
    method: Literal["rule", "cache", "llm", "placeholder"]
    warnings: list[str]


def cache_key(*, table: str, measure_name: str, sql: str) -> str:
    h = hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]
    return f"{table}::{measure_name}::{h}"


class TranslationCache:
    def __init__(
        self,
        *,
        path: Path,
        entries: dict[str, TranslationEntry] | None = None,
    ) -> None:
        self.path = path
        self._entries: dict[str, TranslationEntry] = dict(entries) if entries else {}

    @classmethod
    def load(cls, path: Path) -> TranslationCache:
        if not path.exists():
            return cls(path=path)
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        entries = {
            k: TranslationEntry(
                dax=str(v["dax"]),
                method=v["method"],
                warnings=list(v.get("warnings", [])),
            )
            # Skip anything that isn't a well-formed entry so a malformed cache
            # file degrades to a partial/empty cache instead of crashing every
            # translate/preview (e.g. a stray scalar from a bad clear).
            for k, v in raw.items()
            if isinstance(v, dict) and "dax" in v and "method" in v
        }
        return cls(path=path, entries=entries)

    def get(self, key: str) -> TranslationEntry | None:
        return self._entries.get(key)

    def set(
        self,
        key: str,
        *,
        dax: str,
        method: Literal["rule", "cache", "llm", "placeholder"],
        warnings: list[str],
    ) -> None:
        if method not in _VALID_METHODS:
            raise ValueError(f"invalid method: {method}")
        self._entries[key] = TranslationEntry(dax=dax, method=method, warnings=list(warnings))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {k: asdict(v) for k, v in self._entries.items()}
        self.path.write_text(json.dumps(serializable, indent=2, sort_keys=True), encoding="utf-8")
