from __future__ import annotations

import click

from databricks_to_pbi.cli import sync


def test_sync_has_validate_flag() -> None:
    params = {p.name: p for p in sync.params}
    assert "validate" in params
    opt = params["validate"]
    assert isinstance(opt, click.Option)
    assert opt.is_flag is True
    assert opt.default is False
