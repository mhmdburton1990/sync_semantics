"""Fabric / Power BI workspace discovery via the Fabric SP credentials.

The UC POWER_BI connection in the customer's workspace is `credential_type:
OAUTH_U2M` — a per-user refresh token that Databricks holds server-side
and does NOT expose via SDK. That means an external client (this App) can't
extract those credentials to publish via XMLA on the user's behalf.

Workaround: the App reads a dedicated Fabric AAD service principal's
credentials (FABRIC_SP_CLIENT_ID/CLIENT_SECRET/FABRIC_TENANT_ID) — injected
at deploy time via `app.yaml` `valueFrom:` references — and uses that SP to
list the Power BI workspaces it has "Build" access to. The user picks one
from a dropdown; that workspace name becomes `target_id` for the XMLA push.

The UC POWER_BI connection still appears in the picker as a sanity check
(confirms the customer has at least one PBI connection registered + tenant
XMLA writes enabled at the metastore level), but it's not the auth source.
"""

from __future__ import annotations

import requests
from azure.core.exceptions import ClientAuthenticationError
from fastapi import APIRouter, Depends

from databricks_to_pbi.app.auth import current_obo_token
from databricks_to_pbi.app.errors import AppError
from databricks_to_pbi.app.models import FabricWorkspaceSummary
from databricks_to_pbi.auth.fabric import (
    FabricAuth,
    NoCredentialsError,
    load_credentials_from_env,
)

__all__ = ["router"]


router = APIRouter(
    prefix="/api/fabric",
    tags=["fabric"],
    # OBO required so anonymous traffic can't probe the endpoint — but auth
    # to PBI itself is from the Fabric SP, not from the user.
    dependencies=[Depends(current_obo_token)],
)


_GROUPS_URL = "https://api.powerbi.com/v1.0/myorg/groups"


@router.get("/workspaces", response_model=list[FabricWorkspaceSummary])
def list_workspaces() -> list[FabricWorkspaceSummary]:
    """Power BI workspaces the Fabric SP has access to (Build / Member / Admin).

    Returns an empty list if the App isn't configured with FABRIC_SP_* env
    vars — the frontend then falls back to a free-text workspace name.
    """
    creds = load_credentials_from_env()
    if creds is None:
        raise AppError(
            code="fabric_sp_not_configured",
            message="The App is not configured with Fabric SP credentials.",
            suggestion=(
                "Set FABRIC_SP_CLIENT_ID, FABRIC_SP_CLIENT_SECRET, and "
                "FABRIC_TENANT_ID via app.yaml `valueFrom:` references to "
                "Databricks secrets, then redeploy."
            ),
            status_code=400,
        )

    auth = FabricAuth(credentials=creds)
    try:
        bearer = auth.bearer_token()
    except NoCredentialsError as exc:
        raise AppError(
            code="fabric_sp_not_configured",
            message=str(exc),
            status_code=400,
        ) from exc
    except ClientAuthenticationError as exc:
        # Azure AD rejected the SP credentials before we ever reach Power BI —
        # most often an expired/rotated client secret (AADSTS7000222) or a
        # wrong client_id/tenant_id. Surface Azure's own message so the cause
        # is visible in the UI instead of collapsing into a bare 500.
        raise AppError(
            code="fabric_sp_unauthorized",
            message="Fabric SP credentials were rejected by Azure AD.",
            suggestion=(str(exc) or "")[:500],
            status_code=502,
        ) from exc

    resp = requests.get(
        _GROUPS_URL,
        headers={"Authorization": f"Bearer {bearer}"},
        timeout=30,
    )
    if resp.status_code == 401:
        raise AppError(
            code="fabric_sp_unauthorized",
            message="Fabric SP credentials are invalid or expired.",
            suggestion="Verify the client_id, secret, and tenant_id values.",
            status_code=502,
        )
    if resp.status_code == 403:
        raise AppError(
            code="fabric_sp_forbidden",
            message="Fabric SP isn't authorized to list Power BI workspaces.",
            suggestion=(
                "In the Fabric admin portal, enable 'Service principals can "
                "use Fabric APIs' and grant the SP at least 'Contributor' "
                "on the target workspaces."
            ),
            status_code=502,
        )
    if not resp.ok:
        raise AppError(
            code="fabric_api_error",
            message=f"Power BI API returned {resp.status_code}.",
            suggestion=resp.text[:300] if resp.text else None,
            status_code=502,
        )

    body = resp.json()
    out: list[FabricWorkspaceSummary] = []
    for g in body.get("value", []):
        out.append(
            FabricWorkspaceSummary(
                id=str(g["id"]),
                name=str(g["name"]),
                is_dedicated_capacity=bool(g.get("isOnDedicatedCapacity", False)),
                capacity_id=g.get("capacityId"),
            )
        )
    return out
