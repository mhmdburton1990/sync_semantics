"""Compute create/update/unchanged/delete/rename operations from IR vs. manifest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from databricks_to_pbi.ir import Measure
from databricks_to_pbi.sync.manifest import ManifestEntry

__all__ = ["PlannedOperation", "SyncPlan", "compute_measure_plan"]


@dataclass(frozen=True, slots=True)
class PlannedOperation:
    action: Literal["create", "update", "unchanged", "delete", "rename"]
    target_object_path: str
    measure: Measure | None
    prior: ManifestEntry | None
    from_name: str | None = None
    to_name: str | None = None


@dataclass(frozen=True, slots=True)
class SyncPlan:
    ops: list[PlannedOperation]


def _measure_path(name: str) -> str:
    return f"Measures/{name}"


def compute_measure_plan(
    *,
    current: list[Measure],
    prior: list[ManifestEntry],
) -> SyncPlan:
    prior_by_name = {
        e.target_object_path.split("/")[-1]: e
        for e in prior
        if e.target_object_path.startswith("Measures/")
    }
    current_by_name = {m.name: m for m in current}

    ops: list[PlannedOperation] = []
    used_prior: set[str] = set()
    used_current: set[str] = set()

    # Pass 1: exact-name matches
    for name, m in current_by_name.items():
        p = prior_by_name.get(name)
        if p is None:
            continue
        path = _measure_path(name)
        used_prior.add(name)
        used_current.add(name)
        if p.object_hash == m.source.object_hash:
            ops.append(
                PlannedOperation(
                    action="unchanged", target_object_path=path, measure=m, prior=p
                )
            )
        else:
            ops.append(
                PlannedOperation(action="update", target_object_path=path, measure=m, prior=p)
            )

    # Pass 2: leftover currents → rename (hash-match first, then sole-candidate) or create
    leftover_priors = {n: e for n, e in prior_by_name.items() if n not in used_prior}
    unmatched_currents = [(n, m) for n, m in current_by_name.items() if n not in used_current]

    for name, m in unmatched_currents:
        renamed_from = _detect_rename(m, leftover_priors)
        if renamed_from is None and len(unmatched_currents) == 1 and len(leftover_priors) == 1:
            # Sole-candidate heuristic: one unmatched current, one leftover prior → rename
            renamed_from = next(iter(leftover_priors))
        if renamed_from is not None:
            ops.append(
                PlannedOperation(
                    action="rename",
                    target_object_path=_measure_path(name),
                    measure=m,
                    prior=leftover_priors[renamed_from],
                    from_name=renamed_from,
                    to_name=name,
                )
            )
            del leftover_priors[renamed_from]
        else:
            ops.append(
                PlannedOperation(
                    action="create",
                    target_object_path=_measure_path(name),
                    measure=m,
                    prior=None,
                )
            )

    # Pass 3: leftover priors → delete
    for name, p in leftover_priors.items():
        ops.append(
            PlannedOperation(
                action="delete",
                target_object_path=_measure_path(name),
                measure=None,
                prior=p,
            )
        )

    return SyncPlan(ops=ops)


def _detect_rename(m: Measure, leftover_priors: dict[str, ManifestEntry]) -> str | None:
    """High-confidence rename: identical underlying SQL (object_hash) and same source kind."""
    for prior_name, p in leftover_priors.items():
        if p.source_refs and p.source_refs[0].object_hash == m.source.object_hash:
            return prior_name
    return None
