from __future__ import annotations

from databricks_to_pbi.reporting.report import SyncReport


def test_syncreport_has_published_dataset_id_field() -> None:
    fields = SyncReport.model_fields
    assert "published_dataset_id" in fields
