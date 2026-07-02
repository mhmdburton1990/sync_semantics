"""Sync engine orchestration. Preview and apply paths."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from databricks_to_pbi.auth.fabric import (
    FABRIC_API_SCOPE,
    FabricAuth,
    load_credentials_from_env,
)
from databricks_to_pbi.ir import DatabricksSemanticIR
from databricks_to_pbi.reporting.report import (
    ObjectOutcome,
    SummaryStats,
    SyncReport,
    TableInfo,
)
from databricks_to_pbi.sync.diff import SyncPlan, compute_measure_plan
from databricks_to_pbi.sync.manifest import (
    Manifest,
    ManifestEntry,
    TargetDescriptor,
    compute_etag,
    load_manifest,
    save_manifest,
)
from databricks_to_pbi.sync.merge import merge_irs
from databricks_to_pbi.translator.cache import TranslationCache
from databricks_to_pbi.translator.sql_to_dax import (
    ClaudeClient,
    TranslationResult,
    translate_measure,
)
from databricks_to_pbi.translator.window import translate_window
from databricks_to_pbi.writers.fabric_api import FabricApiClient, push_semantic_model
from databricks_to_pbi.writers.pbi_model import build_pbi_model
from databricks_to_pbi.writers.pbit import write_pbit
from databricks_to_pbi.writers.tmdl import write_pbip

__all__ = [
    "SyncInputs",
    "SyncInputsMulti",
    "run_sync",
    "run_sync_multi",
    "translate_for_validation",
]


_ACTION_MAP: dict[str, Literal["created", "updated", "unchanged", "renamed"]] = {
    "create": "created",
    "update": "updated",
    "unchanged": "unchanged",
    "rename": "renamed",
}


@dataclass(frozen=True, slots=True)
class SyncInputs:
    ir: DatabricksSemanticIR
    target: TargetDescriptor
    mode: Literal["preview", "apply"]


@dataclass(frozen=True, slots=True)
class SyncInputsMulti:
    partial_irs: list[DatabricksSemanticIR]
    target: TargetDescriptor
    mode: Literal["preview", "apply"]
    target_model_name: str
    target_model_description: str | None = None
    xmla_merge: bool = False
    # Optional Databricks connection context — when populated, these become
    # the default values of the published model's WorkspaceHost / HttpPath
    # parameters so the model is refreshable without any post-publish edits.
    workspace_host: str | None = None
    http_path: str | None = None
    # Per-table storage-mode overrides keyed by table name. Lets the user
    # mix DirectQuery (live, fact tables) and Dual / Import (cached,
    # dimension tables) on a single model. PBI Service won't let users
    # change storage mode after publish, so we have to write it correctly
    # the first time. Tables not in the map use the reader's default.
    storage_mode_overrides: dict[str, str] = field(default_factory=dict)
    # Measure names to drop from the merged model before building (Apply only;
    # Preview shows all). No dependency cascade — only the named measures go.
    exclude_measures: frozenset[str] = field(default_factory=frozenset)


def _build_fabric_api_client(target: TargetDescriptor) -> FabricApiClient:
    """Build the Fabric REST API client.

    ``target.target_id`` is the workspace GUID. Auth is the Fabric SP via
    env-injected secrets (FABRIC_SP_*) but with the Fabric API scope
    (``api.fabric.microsoft.com/.default``), not the Power BI scope.
    """
    workspace_id, _, _ = target.target_id.partition("::")
    creds = load_credentials_from_env()
    auth = FabricAuth(credentials=creds, scope=FABRIC_API_SCOPE)
    return FabricApiClient(workspace_id=workspace_id, auth=auth)


def _dispatch_apply(
    *,
    target: TargetDescriptor,
    pbi_model: Any,
    target_model_name: str,
    xmla_merge: bool = False,
) -> tuple[str, str | None]:
    if target.kind == "pbip":
        write_pbip(pbi_model, output_dir=Path(target.target_id))
        return "pbip", None
    if target.kind == "pbit":
        write_pbit(pbi_model, output_path=Path(target.target_id))
        return "pbit", None
    if target.kind == "xmla":
        # XMLA delivery goes through the Fabric REST semanticModels API,
        # which accepts the TMDL parts we already emit for PBIP. The
        # "merge" flag is repurposed here: True → overwrite an existing
        # model with the same displayName, False → abort if one exists
        # (the safe default for first-publish flows).
        client = _build_fabric_api_client(target)
        result = push_semantic_model(
            client,
            model=pbi_model,
            display_name=target_model_name,
            overwrite_existing=xmla_merge,
        )
        label = "xmla_merge" if xmla_merge else "xmla_create"
        return label, result.semantic_model_id or None
    raise ValueError(f"unsupported target.kind: {target.kind}")


def _columns_by_table(ir: DatabricksSemanticIR) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for t in ir.tables:
        out[t.name] = [c.name for c in t.columns]
    return out


def _window_date_ref(ir: DatabricksSemanticIR, order_dim: str) -> str | None:
    """Resolve a window's ``order`` dimension name to its DAX ``'table'[column]``.
    Dimension expressions keep the ``source.`` prefix and use dotted
    ``table.column`` form (e.g. ``source.calendar.date`` → ``'calendar'[date]``)."""
    dim = next((d for d in ir.dimensions if d.name == order_dim), None)
    if dim is None:
        return None
    expr = dim.expression.replace("source.", "")
    if "." not in expr:
        return None  # not a joined date column we can target
    table, _, col = expr.partition(".")
    return f"'{table}'[{col}]"


def _translate_all(
    ir: DatabricksSemanticIR,
    cache: TranslationCache,
    claude: ClaudeClient | None,
) -> tuple[dict[str, str], dict[str, str], dict[str, list[str]]]:
    cols = _columns_by_table(ir)
    translations: dict[str, str] = {}
    methods: dict[str, str] = {}
    warnings_by_name: dict[str, list[str]] = {}
    for m in ir.measures:
        host = ir.tables[0].name if ir.tables else ""
        result = translate_measure(
            sql=m.sql_expression,
            table_context=host,
            measure_name=m.name,
            columns_by_table=cols,
            cache=cache,
            client=claude,
        )
        if m.window:
            date_ref = _window_date_ref(ir, m.window[0].order)
            wrapped = (
                translate_window(result.dax, m.window, date_ref)
                if date_ref and result.method in ("rule", "cache")
                else None
            )
            if wrapped is not None:
                result = TranslationResult(dax=wrapped, method="rule", warnings=[])
            else:
                # Never ship the window-less DAX; fall back to manual review.
                result = TranslationResult(
                    dax="// MANUAL: windowed measure — unrecognized window spec",
                    method="placeholder",
                    warnings=[f"{m.name}: windowed measure not translated (unrecognized window)"],
                )
        translations[m.name] = result.dax
        methods[m.name] = result.method
        warnings_by_name[m.name] = list(result.warnings)
    return translations, methods, warnings_by_name


def _summarize(plan: SyncPlan) -> SummaryStats:
    s = SummaryStats()
    for op in plan.ops:
        if op.action == "create":
            s.created += 1
        elif op.action == "update":
            s.updated += 1
        elif op.action == "unchanged":
            s.unchanged += 1
        elif op.action == "delete":
            s.deleted += 1
        elif op.action == "rename":
            s.renamed += 1
    return s


def _run_sync_inner(
    *,
    ir: DatabricksSemanticIR,
    target: TargetDescriptor,
    mode: Literal["preview", "apply"],
    cache: TranslationCache,
    uc_volume_root: Path,
    claude: ClaudeClient | None,
    xmla_merge: bool = False,
    workspace_host: str | None = None,
    http_path: str | None = None,
    storage_mode_overrides: dict[str, str] | None = None,
) -> SyncReport:
    run_id = str(uuid.uuid4())
    started = datetime.now(UTC)

    prior = load_manifest(target, root=uc_volume_root)
    prior_entries = prior.entries if prior else []

    plan = compute_measure_plan(current=ir.measures, prior=prior_entries)

    translations, methods, warnings_by_name = _translate_all(ir, cache, claude)

    outcomes: list[ObjectOutcome] = []
    for op in plan.ops:
        if op.action == "delete":
            outcomes.append(
                ObjectOutcome(
                    object_kind="measure",
                    name=op.target_object_path.split("/")[-1],
                    action="deleted",
                    source_refs=[],
                    translation_method=None,
                    warnings=[],
                    needs_manual_review=False,
                    diff_preview=None,
                )
            )
            continue
        m = op.measure
        if m is None:
            continue
        method = methods.get(m.name, "placeholder")
        warnings = warnings_by_name.get(m.name, [])
        needs_review = method == "placeholder" or any(
            "manual review" in w.lower() for w in warnings
        )
        outcomes.append(
            ObjectOutcome(
                object_kind="measure",
                name=m.name,
                action=_ACTION_MAP[op.action],
                source_refs=[m.source],
                translation_method=cast(
                    Literal["rule", "cache", "llm", "placeholder", "n/a"] | None, method
                ),
                warnings=warnings,
                needs_manual_review=needs_review,
                diff_preview=None,
                sql_expression=m.sql_expression,
                dax=translations.get(m.name),
            )
        )

    summary = _summarize(plan)
    summary.needs_manual_review = sum(1 for o in outcomes if o.needs_manual_review)

    delivery: Literal["xmla_create", "xmla_merge", "pbip", "pbit"] = "pbip"
    published_dataset_id: str | None = None
    if mode == "apply":
        pbi = build_pbi_model(
            ir,
            measure_dax=translations,
            synced_at=started,
            workspace_host=workspace_host,
            http_path=http_path,
            storage_mode_overrides=storage_mode_overrides or {},
        )
        delivery_label, published_dataset_id = _dispatch_apply(
            target=target,
            pbi_model=pbi,
            target_model_name=pbi.name,
            xmla_merge=xmla_merge,
        )
        delivery = cast(
            Literal["xmla_create", "xmla_merge", "pbip", "pbit"],
            delivery_label,
        )
        new_entries = [
            ManifestEntry(
                target_object_path=f"Measures/{m.name}",
                source_refs=[m.source],
                object_hash=m.source.object_hash,
                translation_method=cast(
                    Literal["rule", "cache", "llm", "placeholder", "n/a"] | None,
                    methods.get(m.name, "rule"),
                ),
                last_action="created",
                last_synced_at=started,
            )
            for m in ir.measures
        ]
        manifest = Manifest(
            schema_version=1,
            target=target,
            last_run_id=run_id,
            last_synced_at=started,
            entries=new_entries,
            run_history=[],
            etag=compute_etag(new_entries),
        )
        save_manifest(manifest, root=uc_volume_root)

    finished = datetime.now(UTC)
    return SyncReport(
        run_id=run_id,
        started_at=started,
        finished_at=finished,
        target=target,
        target_model_name=ir.name,
        mode=mode,
        delivery=delivery,
        summary=summary,
        outcomes=outcomes,
        errors=[],
        fatal_error=None,
        source_inventory=list(ir.sources),
        # Apply any user-supplied storage-mode override so the Preview UI
        # reflects exactly what the next Apply call would publish.
        tables=[
            TableInfo(
                name=t.name,
                storage_mode=cast(
                    Literal["import", "direct_query", "dual"],
                    (storage_mode_overrides or {}).get(t.name, t.storage_mode),
                ),
                uc_path=t.uc_path,
                column_count=len(t.columns),
            )
            for t in ir.tables
        ],
        published_dataset_id=published_dataset_id,
    )


def run_sync(
    *,
    inputs: SyncInputs,
    cache: TranslationCache,
    uc_volume_root: Path,
    claude: ClaudeClient | None,
) -> SyncReport:
    return _run_sync_inner(
        ir=inputs.ir,
        target=inputs.target,
        mode=inputs.mode,
        cache=cache,
        uc_volume_root=uc_volume_root,
        claude=claude,
        xmla_merge=False,
    )


def run_sync_multi(
    *,
    inputs: SyncInputsMulti,
    cache: TranslationCache,
    uc_volume_root: Path,
    claude: ClaudeClient | None,
) -> SyncReport:
    merged_ir = merge_irs(
        inputs.partial_irs,
        target_name=inputs.target_model_name,
        description=inputs.target_model_description,
    )
    if inputs.exclude_measures:
        merged_ir = merged_ir.model_copy(update={
            "measures": [m for m in merged_ir.measures if m.name not in inputs.exclude_measures],
        })
    return _run_sync_inner(
        ir=merged_ir,
        target=inputs.target,
        mode=inputs.mode,
        cache=cache,
        uc_volume_root=uc_volume_root,
        claude=claude,
        xmla_merge=inputs.xmla_merge,
        workspace_host=inputs.workspace_host,
        http_path=inputs.http_path,
        storage_mode_overrides=inputs.storage_mode_overrides,
    )


def translate_for_validation(
    ir: DatabricksSemanticIR, cache: TranslationCache, claude: ClaudeClient | None,
) -> dict[str, str]:
    """Return {measure_name: method} for an already-merged IR (used by the
    App's post-publish validation, which needs methods without re-running apply)."""
    _translations, methods, _warnings = _translate_all(ir, cache, claude)
    return methods
