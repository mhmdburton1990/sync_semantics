from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from databricks_to_pbi.auth.fabric import (
    FabricAuth,
    FabricCredentials,
    NoCredentialsError,
    acquire_bearer_token,
    load_credentials_from_env,
)


def test_load_credentials_from_env_returns_none_without_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k in ("FABRIC_SP_CLIENT_ID", "FABRIC_SP_CLIENT_SECRET", "FABRIC_TENANT_ID"):
        monkeypatch.delenv(k, raising=False)
    assert load_credentials_from_env() is None


def test_load_credentials_from_env_returns_creds_when_all_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FABRIC_SP_CLIENT_ID", "cid")
    monkeypatch.setenv("FABRIC_SP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("FABRIC_TENANT_ID", "tid")
    creds = load_credentials_from_env()
    assert creds is not None
    assert creds.client_id == "cid"
    assert creds.tenant_id == "tid"


def test_acquire_bearer_token_calls_azure_identity() -> None:
    fake_cred_client = MagicMock()
    fake_token = MagicMock()
    fake_token.token = "fake-bearer-xyz"
    fake_cred_client.get_token.return_value = fake_token

    with patch("databricks_to_pbi.auth.fabric.ClientSecretCredential") as CSC:
        CSC.return_value = fake_cred_client
        creds = FabricCredentials(client_id="cid", client_secret="s", tenant_id="tid")
        token = acquire_bearer_token(creds)

    CSC.assert_called_once_with(tenant_id="tid", client_id="cid", client_secret="s")
    fake_cred_client.get_token.assert_called_once_with("https://analysis.windows.net/powerbi/api/.default")
    assert token == "fake-bearer-xyz"


def test_fabric_auth_no_credentials_raises() -> None:
    auth = FabricAuth(credentials=None)
    with pytest.raises(NoCredentialsError):
        auth.bearer_token()


def test_fabric_auth_caches_token() -> None:
    creds = FabricCredentials(client_id="c", client_secret="s", tenant_id="t")
    with patch("databricks_to_pbi.auth.fabric.acquire_bearer_token", return_value="tok-1") as ab:
        auth = FabricAuth(credentials=creds)
        t1 = auth.bearer_token()
        t2 = auth.bearer_token()
    assert t1 == "tok-1" == t2
    assert ab.call_count == 1
