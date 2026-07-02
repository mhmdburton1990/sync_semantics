from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from databricks_to_pbi.readers.genie import (
    parse_genie_space,
    read_genie_space,
)


@pytest.fixture
def genie_json(fixtures_dir: Path) -> str:
    return (fixtures_dir / "genie_spaces" / "sales_space.json").read_text(encoding="utf-8")


def test_parse_genie_space_extracts_instructions_and_metrics(genie_json: str) -> None:
    parsed = parse_genie_space(genie_json)
    assert "month-over-month" in parsed["instructions"]
    assert len(parsed["sample_questions"]) == 2
    assert {m["name"] for m in parsed["metric_definitions"]} == {"gross_revenue"}


def test_read_genie_space_populates_ir(genie_json: str) -> None:
    sdk = MagicMock()
    sdk.genie = MagicMock()
    sdk.genie.get_space.return_value = MagicMock(
        as_dict=MagicMock(return_value={"serialized_space": genie_json})
    )

    from databricks_to_pbi.workspace import WorkspaceClient
    wc = WorkspaceClient(sdk_client=sdk, warehouse_id="wh-1")

    ir = read_genie_space(wc, space_id="space-xyz-789")

    assert ir.genie is not None
    assert "month-over-month" in (ir.genie.instructions or "")
    assert len(ir.genie.sample_questions) == 2
    assert len(ir.genie.example_question_sqls) == 1

    # metric_definition → Measure
    measure_names = {m.name for m in ir.measures}
    assert "gross_revenue" in measure_names
    gross = next(m for m in ir.measures if m.name == "gross_revenue")
    assert gross.source.kind == "genie_space"
    assert gross.description == "Pre-discount revenue"

    # linked_tables → synthetic Table entries (no SQL, no columns yet)
    table_paths = {t.uc_path for t in ir.tables}
    assert "main.sales.orders" in table_paths
    assert "main.sales.customers" in table_paths
