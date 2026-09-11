from __future__ import annotations

import json
from pathlib import Path

from databricks_to_pbi.writers.pbi_model import (
    PBIAnnotation,
    PBIColumn,
    PBIMeasure,
    PBIModel,
    PBIRelationship,
    PBITable,
)
from databricks_to_pbi.writers.tmdl import (
    render_relationships_tmdl,
    render_table_tmdl,
    write_pbip,
)


def _rel(cardinality: str, cross_filter: str = "single") -> PBIRelationship:
    return PBIRelationship(
        from_table="orders", from_columns=["k"],
        to_table="dim", to_columns=["k"],
        cardinality=cardinality, cross_filter=cross_filter,  # type: ignore[arg-type]
    )


def test_render_relationships_never_emits_invalid_cardinality_keyword() -> None:
    # TMDL has no `cardinality` property on a relationship; Power BI Desktop
    # rejects the whole project with "cardinality is not a supported property".
    for card in ("many_to_one", "one_to_many", "one_to_one", "many_to_many"):
        out = render_relationships_tmdl([_rel(card)])
        assert "cardinality:" not in out, f"{card} emitted invalid `cardinality:`"


def test_render_relationships_many_to_many_uses_from_to_cardinality() -> None:
    out = render_relationships_tmdl([_rel("many_to_many", cross_filter="both")])
    assert "toCardinality: many" in out
    assert "crossFilteringBehavior: bothDirections" in out


def test_render_relationships_one_to_many_sets_both_cardinalities() -> None:
    out = render_relationships_tmdl([_rel("one_to_many")])
    assert "fromCardinality: one" in out
    assert "toCardinality: many" in out


def test_render_relationships_many_to_one_omits_default_cardinalities() -> None:
    # many-to-one is the TMDL default, so nothing extra should be emitted.
    out = render_relationships_tmdl([_rel("many_to_one")])
    assert "fromCardinality" not in out
    assert "toCardinality" not in out


def test_render_table_tmdl_includes_header_and_columns() -> None:
    t = PBITable(
        name="Orders",
        storage_mode="direct_query",
        uc_path="main.sales.orders",
        sql_definition=None,
        columns=[
            PBIColumn(name="amount", data_type="DECIMAL(18,2)", source_column="amount"),
            PBIColumn(name="status", data_type="STRING", source_column="status"),
        ],
        measures=[],
        description="Sales orders fact table",
        annotations=[
            PBIAnnotation(name="dbx2pbi_source_kind", value="metric_view"),
            PBIAnnotation(name="dbx2pbi_object_hash", value="h1"),
        ],
    )

    tmdl = render_table_tmdl(t)

    # TMDL table description is a /// doc-comment before the table line, not
    # an inline property (the Fabric semanticModels API rejects the property
    # form at the table level).
    assert tmdl.startswith("/// Sales orders fact table\ntable Orders\n")
    assert "    column amount" in tmdl
    assert "        dataType: decimal" in tmdl
    assert "    annotation dbx2pbi_source_kind = metric_view" in tmdl
    assert tmdl.endswith("\n")


def test_render_table_tmdl_emits_measures() -> None:
    t = PBITable(
        name="Orders", storage_mode="direct_query", uc_path="main.sales.orders",
        sql_definition=None, columns=[],
        measures=[
            PBIMeasure(name="Total Sales", dax="SUM('Orders'[amount])", format_string="$#,##0.00")
        ],
        description=None, annotations=[],
    )
    tmdl = render_table_tmdl(t)
    assert "    measure 'Total Sales' = SUM('Orders'[amount])" in tmdl
    assert "        formatString: $#,##0.00" in tmdl


def test_render_table_tmdl_dual_mode_partition() -> None:
    t = PBITable(
        name="Customers", storage_mode="dual", uc_path="main.sales.customers",
        sql_definition=None, columns=[], measures=[], description=None, annotations=[],
    )
    tmdl = render_table_tmdl(t)
    # Partition name matches the table name (no `-DBX` suffix; that pattern
    # breaks PBI's data-source detector).
    assert "    partition Customers = m" in tmdl
    assert "Databricks.Catalogs(ServerHostname, HTTPPath," in tmdl
    assert "mode: dual" in tmdl
    # M is wrapped in triple-backticks so multi-line + bare-identifier
    # form is preserved verbatim (the shape PBI's detector matches).
    assert "source = ```" in tmdl


def test_write_pbip_creates_expected_layout(tmp_path: Path) -> None:
    model = PBIModel(
        name="SalesModel",
        description=None,
        tables=[
            PBITable(
                name="Orders", storage_mode="direct_query", uc_path="main.sales.orders",
                sql_definition=None,
                columns=[],
                measures=[],
                description=None, annotations=[],
            ),
        ],
        relationships=[],
        annotations=[],
    )
    write_pbip(model, output_dir=tmp_path)

    sem = tmp_path / "SalesModel.SemanticModel" / "definition"
    assert (sem / "model.tmdl").exists()
    assert (sem / "database.tmdl").exists()
    assert (sem / "relationships.tmdl").exists()
    assert (sem / "tables" / "Orders.tmdl").exists()
    assert (tmp_path / "SalesModel.Report" / "definition.pbir").exists()


def test_write_pbip_is_idempotent_for_unchanged_input(tmp_path: Path) -> None:
    model = PBIModel(
        name="X", description=None, tables=[], relationships=[], annotations=[],
    )
    model_tmdl = tmp_path / "X.SemanticModel" / "definition" / "model.tmdl"
    write_pbip(model, output_dir=tmp_path)
    first = model_tmdl.read_text(encoding="utf-8")
    write_pbip(model, output_dir=tmp_path)
    second = model_tmdl.read_text(encoding="utf-8")
    assert first == second


def _pbip_model() -> PBIModel:
    return PBIModel(
        name="SalesModel", description=None,
        tables=[
            PBITable(
                name="Orders", storage_mode="direct_query", uc_path="main.sales.orders",
                sql_definition=None, columns=[], measures=[],
                description=None, annotations=[],
            ),
        ],
        relationships=[], annotations=[],
    )


def test_write_pbip_writes_semantic_model_pbism(tmp_path: Path) -> None:
    # Required in <name>.SemanticModel/. Its version marks the model as TMDL
    # (4.x); Desktop won't open a semantic model folder without it.
    write_pbip(_pbip_model(), output_dir=tmp_path)
    pbism = tmp_path / "SalesModel.SemanticModel" / "definition.pbism"
    assert pbism.exists()
    doc = json.loads(pbism.read_text(encoding="utf-8"))
    assert doc["version"].startswith("4.")


def test_write_pbip_writes_top_level_pbip_entry(tmp_path: Path) -> None:
    # The <name>.pbip file is what a user double-clicks; it points at the report.
    write_pbip(_pbip_model(), output_dir=tmp_path)
    entry = tmp_path / "SalesModel.pbip"
    assert entry.exists()
    doc = json.loads(entry.read_text(encoding="utf-8"))
    assert doc["artifacts"][0]["report"]["path"] == "SalesModel.Report"


def test_write_pbip_pbir_is_v4_with_schema_and_bypath(tmp_path: Path) -> None:
    write_pbip(_pbip_model(), output_dir=tmp_path)
    pbir = json.loads(
        (tmp_path / "SalesModel.Report" / "definition.pbir").read_text(encoding="utf-8"),
    )
    assert pbir["version"] == "4.0"
    assert "$schema" in pbir
    assert pbir["datasetReference"]["byPath"]["path"] == "../SalesModel.SemanticModel"


def test_write_pbip_writes_enhanced_pbir_report_body(tmp_path: Path) -> None:
    # Enhanced PBIR keeps the report content under a definition/ folder. Desktop
    # needs a report (with at least one page) to open the project.
    write_pbip(_pbip_model(), output_dir=tmp_path)
    rdef = tmp_path / "SalesModel.Report" / "definition"
    report = json.loads((rdef / "report.json").read_text(encoding="utf-8"))
    assert "$schema" in report
    version = json.loads((rdef / "version.json").read_text(encoding="utf-8"))
    assert "version" in version
    pages = json.loads((rdef / "pages" / "pages.json").read_text(encoding="utf-8"))
    page_id = pages["pageOrder"][0]
    page = json.loads(
        (rdef / "pages" / page_id / "page.json").read_text(encoding="utf-8"),
    )
    assert page["name"] == page_id
    assert page["displayName"]


def test_write_pbip_writes_platform_files_for_both_items(tmp_path: Path) -> None:
    write_pbip(_pbip_model(), output_dir=tmp_path)
    sem_platform = json.loads(
        (tmp_path / "SalesModel.SemanticModel" / ".platform").read_text(encoding="utf-8"),
    )
    rep_platform = json.loads(
        (tmp_path / "SalesModel.Report" / ".platform").read_text(encoding="utf-8"),
    )
    assert sem_platform["metadata"]["type"] == "SemanticModel"
    assert rep_platform["metadata"]["type"] == "Report"
    assert sem_platform["config"]["logicalId"]
    assert rep_platform["config"]["logicalId"]


def test_write_pbip_platform_logical_ids_are_stable(tmp_path: Path) -> None:
    # logicalId must be deterministic so re-running the sync doesn't churn git.
    write_pbip(_pbip_model(), output_dir=tmp_path)
    plat = tmp_path / "SalesModel.SemanticModel" / ".platform"
    first = plat.read_text(encoding="utf-8")
    write_pbip(_pbip_model(), output_dir=tmp_path)
    assert plat.read_text(encoding="utf-8") == first


# ---------------------------------------------------------------------------
# TMDL parameter rendering (WorkspaceHost / HttpPath / CatalogName / SchemaName)
# ---------------------------------------------------------------------------


def test_render_expressions_tmdl_emits_parameter_meta() -> None:
    from databricks_to_pbi.writers.pbi_model import PBIParameter
    from databricks_to_pbi.writers.tmdl import render_expressions_tmdl

    params = [
        PBIParameter(
            name="CatalogName",
            default_value="main",
            description="Unity Catalog catalog name",
        ),
        PBIParameter(name="HttpPath", default_value="/sql/1.0/warehouses/abc"),
    ]
    out = render_expressions_tmdl(params)
    assert 'expression CatalogName = "main" meta [IsParameterQuery=true' in out
    assert 'Type="Text"' in out
    assert "IsParameterQueryRequired=true" in out
    # Description renders as a /// doc-comment before the expression.
    assert "/// Unity Catalog catalog name" in out
    # Second parameter is also present
    assert 'expression HttpPath = "/sql/1.0/warehouses/abc"' in out


def test_render_expressions_tmdl_none_value_emits_null_to_prompt() -> None:
    # A required parameter with no current value renders as `null` (unquoted),
    # which makes Power BI Desktop prompt "Enter parameter values" on open. A
    # placeholder string would count as a saved value and suppress the prompt.
    from databricks_to_pbi.writers.pbi_model import PBIParameter
    from databricks_to_pbi.writers.tmdl import render_expressions_tmdl

    out = render_expressions_tmdl([PBIParameter(name="ServerHostname", default_value=None)])
    assert "expression ServerHostname = null meta [IsParameterQuery=true" in out
    assert "IsParameterQueryRequired=true" in out
    # The value itself must not be quoted (a quoted "" is still a saved value).
    value_part = out.split("meta")[0]
    assert '"' not in value_part


def test_render_expressions_tmdl_empty_when_no_params() -> None:
    from databricks_to_pbi.writers.tmdl import render_expressions_tmdl

    assert render_expressions_tmdl([]) == ""


def test_table_m_expr_parameterizes_connection_but_hardcodes_navigation() -> None:
    """Static-M shape: connection via parameters, navigation via literals.

    PBI Service's "static M" analyzer flags parameter-driven catalog/schema/
    table navigation as a dynamic data source — which blocks Service refresh
    and triggers OnPremiseServiceException at refresh time. Only the
    connection arguments (host, http path) may be parameterised; navigation
    steps must be literal strings with the standard ``Kind="..."`` markers.
    """
    from databricks_to_pbi.writers.pbi_model import PBITable
    from databricks_to_pbi.writers.tmdl import render_table_tmdl

    t = PBITable(
        name="orders",
        storage_mode="direct_query",
        uc_path="main.sales.orders",
        sql_definition=None,
        columns=[],
        measures=[],
        description=None,
    )
    rendered = render_table_tmdl(t)
    # Connection: parameters (named to match the canonical PBI Databricks
    # connector output so the data-source detector recognises it).
    assert "Databricks.Catalogs(ServerHostname, HTTPPath," in rendered
    assert 'EnableQueryResultDownload="1"' in rendered
    # Navigation: literals with Kind markers (no space after comma —
    # matches the working reference exactly).
    assert '[Name="main",Kind="Database"]' in rendered
    assert '[Name="sales",Kind="Schema"]' in rendered
    assert '[Name="orders",Kind="Table"]' in rendered
    # No parameter references in navigation steps.
    assert "Name=CatalogName" not in rendered
    assert "Name=SchemaName" not in rendered


def test_build_pbi_model_emits_default_parameters_from_first_uc_path() -> None:
    from datetime import UTC, datetime

    from databricks_to_pbi.ir import (
        DatabricksSemanticIR,
        Measure,
        SourceRef,
        Table,
    )
    from databricks_to_pbi.writers.pbi_model import build_pbi_model

    src = SourceRef(
        kind="metric_view",
        fully_qualified_name="main.sales.orders_mv",
        object_hash="h1",
        fetched_at=datetime(2026, 5, 28, tzinfo=UTC),
    )
    ir = DatabricksSemanticIR(
        name="Sales",
        description=None,
        tables=[
            Table(
                name="orders",
                uc_path="main.sales.orders",
                sql_definition=None,
                storage_mode="direct_query",
                columns=[],
                description=None,
                source=src,
            ),
        ],
        dimensions=[],
        measures=[
            Measure(
                name="Total",
                sql_expression="SUM(amount)",
                dependencies=[],
                description=None,
                format_string=None,
                source=src,
            ),
        ],
        relationships=[],
        genie=None,
        sources=[src],
    )
    pm = build_pbi_model(
        ir,
        measure_dax={"Total": "SUM('orders'[amount])"},
        synced_at=datetime(2026, 5, 28, tzinfo=UTC),
    )
    by_name = {p.name: p for p in pm.parameters}
    # Parameter names match the canonical PBI Databricks connector output —
    # ServerHostname / HTTPPath — so PBI Service's data-source detector
    # recognises the published model as a Databricks data source.
    assert set(by_name) == {"ServerHostname", "HTTPPath"}
    # No host/http_path supplied -> parameters carry no current value, so Power
    # BI Desktop prompts the user for them on open.
    assert by_name["ServerHostname"].default_value is None
    assert by_name["HTTPPath"].default_value is None
