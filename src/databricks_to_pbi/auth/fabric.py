"""Acquire bearer tokens for the Power BI / Fabric XMLA endpoint."""

from __future__ import annotations

import os
from dataclasses import dataclass

from azure.identity import ClientSecretCredential

__all__ = [
    "FABRIC_API_SCOPE",
    "POWER_BI_SCOPE",
    "FabricAuth",
    "FabricCredentials",
    "NoCredentialsError",
    "acquire_bearer_token",
    "load_credentials_from_env",
]


POWER_BI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
FABRIC_API_SCOPE = "https://api.fabric.microsoft.com/.default"


_POWERBI_SCOPE = POWER_BI_SCOPE


class NoCredentialsError(Exception):
    """Raised when a token is requested without configured credentials."""


@dataclass(frozen=True, slots=True)
class FabricCredentials:
    client_id: str
    client_secret: str
    tenant_id: str


def load_credentials_from_env() -> FabricCredentials | None:
    cid = os.environ.get("FABRIC_SP_CLIENT_ID")
    sec = os.environ.get("FABRIC_SP_CLIENT_SECRET")
    tid = os.environ.get("FABRIC_TENANT_ID")
    if not (cid and sec and tid):
        return None
    return FabricCredentials(client_id=cid, client_secret=sec, tenant_id=tid)


def acquire_bearer_token(
    creds: FabricCredentials, *, scope: str = _POWERBI_SCOPE,
) -> str:
    cred = ClientSecretCredential(
        tenant_id=creds.tenant_id,
        client_id=creds.client_id,
        client_secret=creds.client_secret,
    )
    token = cred.get_token(scope)
    return token.token


class FabricAuth:
    """Holds credentials + caches one bearer token per scope across calls."""

    def __init__(
        self,
        *,
        credentials: FabricCredentials | None,
        scope: str = _POWERBI_SCOPE,
    ) -> None:
        self._creds = credentials
        self._scope = scope
        self._cached: str | None = None

    def bearer_token(self) -> str:
        if self._creds is None:
            raise NoCredentialsError(
                "no Fabric credentials configured; set FABRIC_SP_CLIENT_ID / "
                "FABRIC_SP_CLIENT_SECRET / FABRIC_TENANT_ID"
            )
        if self._cached is None:
            self._cached = acquire_bearer_token(self._creds, scope=self._scope)
        return self._cached
