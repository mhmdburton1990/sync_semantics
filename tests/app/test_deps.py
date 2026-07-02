from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from databricks_to_pbi.app.auth import OBO_HEADER
from databricks_to_pbi.app.deps import (
    WAREHOUSE_HEADER,
    get_uc_volume_root,
    get_workspace_client,
    require_warehouse_id,
)
from databricks_to_pbi.workspace import WorkspaceClient


@pytest.fixture
def app_with_dep_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FastAPI:
    monkeypatch.setenv("DBX2PBI_UC_VOLUME", str(tmp_path / "vol"))
    monkeypatch.delenv("DBX2PBI_WAREHOUSE_ID", raising=False)

    app = FastAPI()

    @app.get("/probe")
    def probe(
        wc: WorkspaceClient = Depends(get_workspace_client),  # noqa: B008
        vol: Path = Depends(get_uc_volume_root),  # noqa: B008
    ) -> dict[str, str]:
        return {
            "warehouse": wc.warehouse_id,
            "volume": str(vol),
        }

    @app.get("/sql-only")
    def sql_only(
        wh: str = Depends(require_warehouse_id),
    ) -> dict[str, str]:
        return {"wh": wh}

    return app


def test_workspace_client_uses_header_warehouse(
    app_with_dep_check: FastAPI, tmp_path: Path,
) -> None:
    with patch("databricks_to_pbi.app.deps.SdkWorkspaceClient") as Sdk:
        Sdk.return_value = MagicMock()
        client = TestClient(app_with_dep_check)
        resp = client.get(
            "/probe",
            headers={OBO_HEADER: "tok", WAREHOUSE_HEADER: "wh-from-header"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"warehouse": "wh-from-header", "volume": str(tmp_path / "vol")}


def test_workspace_client_falls_back_to_env_warehouse(
    app_with_dep_check: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DBX2PBI_WAREHOUSE_ID", "wh-from-env")
    with patch("databricks_to_pbi.app.deps.SdkWorkspaceClient") as Sdk:
        Sdk.return_value = MagicMock()
        client = TestClient(app_with_dep_check)
        resp = client.get("/probe", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 200
    assert resp.json()["warehouse"] == "wh-from-env"


def test_workspace_client_empty_when_neither_set(
    app_with_dep_check: FastAPI,
) -> None:
    with patch("databricks_to_pbi.app.deps.SdkWorkspaceClient") as Sdk:
        Sdk.return_value = MagicMock()
        client = TestClient(app_with_dep_check)
        resp = client.get("/probe", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 200
    # Empty warehouse is allowed; SDK-only routes still work, SQL routes 400
    assert resp.json()["warehouse"] == ""


def test_require_warehouse_id_400s_when_missing(
    app_with_dep_check: FastAPI,
) -> None:
    from databricks_to_pbi.app.errors import install_error_handlers
    install_error_handlers(app_with_dep_check)
    client = TestClient(app_with_dep_check)
    resp = client.get("/sql-only", headers={OBO_HEADER: "tok"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "missing_warehouse"


def test_require_warehouse_id_accepts_header(
    app_with_dep_check: FastAPI,
) -> None:
    from databricks_to_pbi.app.errors import install_error_handlers
    install_error_handlers(app_with_dep_check)
    client = TestClient(app_with_dep_check)
    resp = client.get(
        "/sql-only",
        headers={OBO_HEADER: "tok", WAREHOUSE_HEADER: "wh-h"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"wh": "wh-h"}
