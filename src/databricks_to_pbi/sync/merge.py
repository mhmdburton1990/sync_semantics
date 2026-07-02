"""Merge multiple partial IRs (one per reader invocation) into one IR.

Precedence for collisions (highest fidelity first):
  metric_view > dashboard > genie_space
"""

from __future__ import annotations

from databricks_to_pbi.ir import (
    DatabricksSemanticIR,
    GenieAnnotation,
    Measure,
    Relationship,
    SourceRef,
    Table,
)

__all__ = ["merge_irs"]


_KIND_PRIORITY: dict[str, int] = {
    "metric_view": 0,
    "dashboard": 1,
    "genie_space": 2,
}


def _priority(s: SourceRef) -> int:
    return _KIND_PRIORITY.get(s.kind, 99)


def _merge_tables(irs: list[DatabricksSemanticIR]) -> list[Table]:
    """Merge tables while preserving first-seen order.

    The engine's `_translate_all` uses ``ir.tables[0]`` as the host table
    for measure qualification — so the *first* table of the first IR (which
    the readers consistently set to the main fact table) must remain first.
    Tables with ``uc_path=None`` (e.g. a metric view whose ``source:`` is a
    SQL string) keep their original slot via object-identity keys.
    """
    by_key: dict[tuple[str, str], Table] = {}
    order: list[tuple[str, str]] = []
    for ir in irs:
        for t in ir.tables:
            key = ("nouc", str(id(t))) if t.uc_path is None else ("uc", t.uc_path)
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = t
                order.append(key)
            elif t.uc_path is not None and _priority(t.source) < _priority(existing.source):
                # Higher-fidelity replacement; same slot.
                by_key[key] = t
    return [by_key[k] for k in order]


def _merge_measures(irs: list[DatabricksSemanticIR]) -> list[Measure]:
    by_name: dict[str, Measure] = {}
    for ir in irs:
        for m in ir.measures:
            existing = by_name.get(m.name)
            if existing is None or _priority(m.source) < _priority(existing.source):
                by_name[m.name] = m
    return list(by_name.values())


def _merge_relationships(irs: list[DatabricksSemanticIR]) -> list[Relationship]:
    seen: set[tuple[str, tuple[str, ...], str, tuple[str, ...]]] = set()
    out: list[Relationship] = []
    for ir in irs:
        for r in ir.relationships:
            key = (r.from_table, tuple(r.from_columns), r.to_table, tuple(r.to_columns))
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
    return out


def _merge_genie(irs: list[DatabricksSemanticIR]) -> GenieAnnotation | None:
    for ir in irs:
        if ir.genie is not None:
            return ir.genie
    return None


def _merge_sources(irs: list[DatabricksSemanticIR]) -> list[SourceRef]:
    seen: set[tuple[str, str]] = set()
    out: list[SourceRef] = []

    def _add(s: SourceRef) -> None:
        key = (s.fully_qualified_name, s.object_hash)
        if key not in seen:
            seen.add(key)
            out.append(s)

    for ir in irs:
        for s in ir.sources:
            _add(s)
        for t in ir.tables:
            _add(t.source)
        for m in ir.measures:
            _add(m.source)
    return out


def merge_irs(
    irs: list[DatabricksSemanticIR],
    *,
    target_name: str,
    description: str | None = None,
) -> DatabricksSemanticIR:
    if not irs:
        return DatabricksSemanticIR(
            name=target_name, description=description,
            tables=[], dimensions=[], measures=[], relationships=[],
            genie=None, sources=[],
        )
    return DatabricksSemanticIR(
        name=target_name,
        description=description,
        tables=_merge_tables(irs),
        dimensions=[d for ir in irs for d in ir.dimensions],
        measures=_merge_measures(irs),
        relationships=_merge_relationships(irs),
        genie=_merge_genie(irs),
        sources=_merge_sources(irs),
    )
