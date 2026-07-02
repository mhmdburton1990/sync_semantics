from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import responses
from click.testing import CliRunner

from databricks_to_pbi.cli import main


@responses.activate
def test_xmla_delivery_pushes_tmdl_via_fabric_api(
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: engine generates TMDL parts and POSTs them to the Fabric
    semanticModels endpoint.

    The endpoint responds 201 Created synchronously for small models — the
    LRO path is covered in fabric_api unit tests.
    """
    monkeypatch.setenv("FABRIC_SP_CLIENT_ID", "c")
    monkeypatch.setenv("FABRIC_SP_CLIENT_SECRET", "s")
    monkeypatch.setenv("FABRIC_TENANT_ID", "t")

    with patch("databricks_to_pbi.auth.fabric.ClientSecretCredential") as CSC:
        fake_cred = MagicMock()
        fake_token = MagicMock()
        fake_token.token = "fake-fabric-token"
        fake_cred.get_token.return_value = fake_token
        CSC.return_value = fake_cred

        workspace_id = "ws-99-guid"
        list_url = (
            f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}"
            f"/semanticModels"
        )
        # First call: list existing models (none) → POST creates a new one.
        responses.add(
            responses.GET,
            list_url,
            json={"value": []},
            status=200,
        )
        responses.add(
            responses.POST,
            list_url,
            json={"id": "sm-new", "displayName": "Sales"},
            status=201,
        )

        mv_body = (fixtures_dir / "metric_views" / "sales_simple.yaml").read_text()
        sdk = MagicMock()
        sdk.statement_execution.execute_statement.return_value = MagicMock(
            result=MagicMock(data_array=[["View Definition", mv_body, ""]]),
        )
        monkeypatch.setattr("databricks_to_pbi.cli._make_sdk_client", lambda: sdk)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "sync",
                "--metric-view", "main.sales.orders_mv",
                "--warehouse-id", "wh-1",
                "--model-name", "Sales",
                "--target-xmla", workspace_id,
                "--uc-volume", str(tmp_path / "uc_volume"),
                "--apply",
            ],
        )
    assert result.exit_code == 0, result.output

    posts = [c for c in responses.calls if c.request.method == "POST"]
    assert len(posts) == 1
    post = posts[0].request
    assert post.headers["Authorization"] == "Bearer fake-fabric-token"
    assert post.headers["Content-Type"] == "application/json"
    body = post.body
    assert body is not None
    body_str = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    assert '"displayName": "Sales"' in body_str
    assert '"definition"' in body_str
    # Each part is base64 — the marker "InlineBase64" must appear repeatedly.
    assert body_str.count('"InlineBase64"') >= 3
    # And the FabricAuth token-acquire used the Fabric scope, not PBI.
    fake_cred.get_token.assert_called_with(
        "https://api.fabric.microsoft.com/.default",
    )
