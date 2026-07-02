"""sync_semantics CLI (Databricks → Power BI direction)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from databricks_to_pbi.auth.fabric import NoCredentialsError
from databricks_to_pbi.ir import DatabricksSemanticIR
from databricks_to_pbi.readers.dashboard import read_dashboard
from databricks_to_pbi.readers.genie import read_genie_space
from databricks_to_pbi.readers.metric_view import read_metric_view
from databricks_to_pbi.reporting.html import write_html
from databricks_to_pbi.reporting.markdown import write_markdown
from databricks_to_pbi.reporting.report import write_json
from databricks_to_pbi.sync.engine import (
    SyncInputsMulti,
    run_sync_multi,
    translate_for_validation,
)
from databricks_to_pbi.sync.manifest import TargetDescriptor
from databricks_to_pbi.sync.merge import merge_irs
from databricks_to_pbi.translator.cache import TranslationCache
from databricks_to_pbi.translator.claude_client import load_from_env as _load_claude_client
from databricks_to_pbi.validation.runner import (
    ValidationContext,
    default_dax_factory,
    run_validation,
)
from databricks_to_pbi.workspace import WorkspaceClient

__all__ = ["main"]


def _make_sdk_client() -> Any:
    from databricks.sdk import WorkspaceClient as SdkWorkspaceClient

    return SdkWorkspaceClient()


@click.group()
def main() -> None:
    """Sync Databricks semantic layer into Power BI."""


@main.command()
@click.option("--metric-view", "metric_views", multiple=True, default=())
@click.option("--dashboard", "dashboards", multiple=True, default=())
@click.option("--genie-space", "genie_spaces", multiple=True, default=())
@click.option("--warehouse-id", required=True, help="SQL warehouse ID for UC reads.")
@click.option("--model-name", required=True, help="Target Power BI semantic model name.")
@click.option("--uc-volume", required=True, type=click.Path(), help="UC volume root for state.")
@click.option("--target-pbip", type=click.Path(), help="Output PBIP folder.")
@click.option("--target-pbit", type=click.Path(), help="Output .pbit template path.")
@click.option("--target-xmla", type=str, help="Fabric workspace name/ID for XMLA delivery.")
@click.option("--xmla-merge", is_flag=True, default=False, help="Use XMLA merge mode.")
@click.option(
    "--validate",
    is_flag=True,
    default=False,
    help="After an XMLA publish, validate published DAX against Databricks MEASURE().",
)
@click.option(
    "--preview/--apply",
    default=True,
    help="Preview shows the plan; apply writes files.",
)
def sync(
    metric_views: tuple[str, ...],
    dashboards: tuple[str, ...],
    genie_spaces: tuple[str, ...],
    warehouse_id: str,
    model_name: str,
    uc_volume: str,
    target_pbip: str | None,
    target_pbit: str | None,
    target_xmla: str | None,
    xmla_merge: bool,
    validate: bool,
    preview: bool,
) -> None:
    """Read one-or-more Databricks sources -> emit a Power BI semantic model."""
    if not (metric_views or dashboards or genie_spaces):
        raise click.UsageError(
            "at least one of --metric-view / --dashboard / --genie-space is required"
        )
    targets = [t for t in (target_pbip, target_pbit, target_xmla) if t]
    if len(targets) != 1:
        raise click.UsageError(
            "exactly one of --target-pbip / --target-pbit / --target-xmla is required"
        )

    if target_pbip:
        target = TargetDescriptor(kind="pbip", target_id=target_pbip)
    elif target_pbit:
        target = TargetDescriptor(kind="pbit", target_id=target_pbit)
    else:
        target = TargetDescriptor(kind="xmla", target_id=target_xmla or "")

    sdk = _make_sdk_client()
    wc = WorkspaceClient(sdk_client=sdk, warehouse_id=warehouse_id)

    partial_irs: list[DatabricksSemanticIR] = []
    for mv in metric_views:
        partial_irs.append(read_metric_view(wc, fully_qualified_name=mv))
    for d in dashboards:
        partial_irs.append(read_dashboard(wc, dashboard_id=d))
    for g in genie_spaces:
        partial_irs.append(read_genie_space(wc, space_id=g))

    cache_path = Path(uc_volume) / "caches" / "sql_to_dax.json"
    cache = TranslationCache.load(cache_path)

    claude = _load_claude_client()
    _print_llm_banner(claude=claude, partial_irs=partial_irs)

    try:
        report = run_sync_multi(
            inputs=SyncInputsMulti(
                partial_irs=partial_irs,
                target=target,
                mode="preview" if preview else "apply",
                target_model_name=model_name,
                xmla_merge=xmla_merge,
            ),
            cache=cache,
            uc_volume_root=Path(uc_volume),
            claude=claude,
        )
    except NoCredentialsError as e:
        raise click.ClickException(
            f"Fabric credentials missing: {e}. Set FABRIC_SP_CLIENT_ID / "
            "FABRIC_SP_CLIENT_SECRET / FABRIC_TENANT_ID before using --target-xmla."
        ) from e

    cache.save()

    write_json(report, root=Path(uc_volume))
    write_markdown(report, root=Path(uc_volume))
    write_html(report, root=Path(uc_volume))

    click.echo(
        f"Run {report.run_id}: created={report.summary.created}, "
        f"updated={report.summary.updated}, unchanged={report.summary.unchanged}, "
        f"manual_review={report.summary.needs_manual_review}"
    )
    _print_manual_review_list(report)

    if (
        validate
        and report.delivery in ("xmla_create", "xmla_merge")
        and report.published_dataset_id
    ):
        _run_cli_validation(
            partial_irs=partial_irs,
            cache=cache,
            claude=claude,
            wc=wc,
            target=target,
            model_name=model_name,
            dataset_id=report.published_dataset_id,
        )


def _print_llm_banner(
    *,
    claude: object | None,
    partial_irs: list[DatabricksSemanticIR],
) -> None:
    if claude is not None:
        return
    has_measures = any(len(ir.measures) > 0 for ir in partial_irs)
    if not has_measures:
        return
    click.echo(
        "WARN  ANTHROPIC_API_KEY not set - LLM fallback disabled.\n"
        "   Measures the rule engine can't translate will get a "
        "// MANUAL: placeholder and be listed at the end of this run.",
    )


def _run_cli_validation(
    *,
    partial_irs: list[DatabricksSemanticIR],
    cache: TranslationCache,
    claude: Any,
    wc: WorkspaceClient,
    target: TargetDescriptor,
    model_name: str,
    dataset_id: str,
) -> None:
    from datetime import UTC, datetime

    merged = merge_irs(partial_irs, target_name=model_name, description=None)
    methods = translate_for_validation(merged, cache, claude)
    workspace_id = target.target_id.partition("::")[0]
    validation = run_validation(
        ValidationContext(
            ir=merged,
            methods=methods,
            wc=wc,
            dataset_id=dataset_id,
            workspace_id=workspace_id,
            model=model_name,
            ran_at=datetime.now(UTC),
            dax_client_factory=default_dax_factory(
                workspace_id=workspace_id, dataset_id=dataset_id,
            ),
        )
    )
    s = validation.summary
    click.echo(
        f"Validation: {s.passed} passed, {s.failed} failed, {s.skipped} skipped"
    )
    marks = {"passed": "PASS", "failed": "FAIL", "skipped": "SKIP"}
    for r in validation.results:
        suffix = f" - {r.skip_reason}" if r.skip_reason else ""
        click.echo(f"  [{marks[r.status]}] {r.name}{suffix}")


def _print_manual_review_list(report: object) -> None:
    outcomes = getattr(report, "outcomes", []) or []
    needs_review = [o for o in outcomes if getattr(o, "needs_manual_review", False)]
    if not needs_review:
        return
    click.echo("")
    click.echo("Manual review required for these measures:")
    for o in needs_review:
        warnings = getattr(o, "warnings", []) or []
        suffix = f" - {warnings[0]}" if warnings else ""
        click.echo(f"  - {o.name}{suffix}")
    click.echo(
        "\nSet ANTHROPIC_API_KEY and re-run to translate the remaining measures "
        "with Claude, or hand-edit the DAX in the generated PBIP/TMDL.",
    )
