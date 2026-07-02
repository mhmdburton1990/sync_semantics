from __future__ import annotations

from pathlib import Path

from databricks_to_pbi.writers.pbi_model import (
    PBIAnnotation,
    PBIColumn,
    PBIMeasure,
    PBIModel,
    PBITable,
)
from databricks_to_pbi.writers.tmdl import render_table_tmdl, write_pbip


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
    assert "set in PBI Desktop" in by_name["ServerHostname"].default_value
    assert "set in PBI Desktop" in by_name["HTTPPath"].default_value
