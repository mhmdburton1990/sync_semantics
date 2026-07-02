"""Publish a PBIModel to a Fabric workspace via the Fabric REST API.

The Fabric semanticModels API accepts the TMDL parts our PBIP writer already
emits, so this is the cleanest write path on Linux:

    POST https://api.fabric.microsoft.com/v1/workspaces/{wsId}/semanticModels
    Body: {
      "displayName": "<name>",
      "definition": {
        "parts": [
          { "path": "definition.pbism",      "payload": "<base64>", "payloadType": "InlineBase64" },
          { "path": "definition/database.tmdl",   ... },
          { "path": "definition/model.tmdl",      ... },
          { "path": "definition/tables/<T>.tmdl", ... },
          ...
        ]
      }
    }

The endpoint returns either 201 Created (with the new model in the body) or
202 Accepted (a long-running operation; `Location` header points to the
operation status, `Retry-After` gives the suggested poll interval). We poll
the LRO until it reaches a terminal state.

Auth scope: `https://api.fabric.microsoft.com/.default` — distinct from the
Power BI scope, so the Fabric `FabricAuth` instance must be built with
``scope=FABRIC_API_SCOPE``.

Required setup on the customer side:
- Same Fabric SP from `auth/fabric.py`. Make sure tenant setting
  "Service principals can use Fabric APIs" is enabled.
- SP needs Contributor on the target workspace.
- Workspace must be on Premium/Fabric capacity for semantic-model writes.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any

import requests

from databricks_to_pbi.auth.fabric import FabricAuth
from databricks_to_pbi.writers.pbi_model import PBIModel
from databricks_to_pbi.writers.tmdl import tmdl_parts

__all__ = [
    "FabricApiClient",
    "FabricApiResult",
    "push_semantic_model",
]


_SEMANTIC_MODELS_URL = (
    "https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/semanticModels"
)
_SEMANTIC_MODEL_UPDATE_URL = _SEMANTIC_MODELS_URL + "/{model_id}/updateDefinition"
_LIST_URL = _SEMANTIC_MODELS_URL


_PBISM_HEADER: dict[str, Any] = {"version": "4.0", "settings": {}}


@dataclass(frozen=True, slots=True)
class FabricApiResult:
    semantic_model_id: str
    state: str  # "Succeeded" (created or updated)
    operation_id: str | None  # set when the request was async


def _encode_part(path: str, content: bytes) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(content).decode("ascii"),
        "payloadType": "InlineBase64",
    }


def _build_definition_parts(model: PBIModel) -> list[dict[str, str]]:
    parts: list[dict[str, str]] = [
        _encode_part("definition.pbism", json.dumps(_PBISM_HEADER).encode("utf-8")),
    ]
    for path, content in tmdl_parts(model).items():
        parts.append(_encode_part(path, content))
    return parts


class FabricApiClient:
    def __init__(
        self,
        *,
        workspace_id: str,
        auth: FabricAuth,
        session: requests.Session | None = None,
        poll_interval_s: float = 2.0,
        poll_timeout_s: float = 300.0,
    ) -> None:
        if not workspace_id:
            raise ValueError("workspace_id is required")
        self._workspace_id = workspace_id
        self._auth = auth
        self._session = session or requests.Session()
        self._poll_interval = poll_interval_s
        self._poll_timeout = poll_timeout_s

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._auth.bearer_token()}",
            "Content-Type": "application/json",
        }

    def find_by_display_name(self, display_name: str) -> str | None:
        """Return the id of the existing model with that displayName, if any."""
        url = _LIST_URL.format(workspace_id=self._workspace_id)
        resp = self._session.get(url, headers=self._headers(), timeout=30)
        if not resp.ok:
            raise RuntimeError(
                f"Fabric list semanticModels failed: HTTP {resp.status_code}: "
                f"{resp.text[:600]}"
            )
        for item in resp.json().get("value", []):
            if str(item.get("displayName")) == display_name:
                return str(item["id"])
        return None

    def create(self, *, display_name: str, model: PBIModel) -> FabricApiResult:
        url = _SEMANTIC_MODELS_URL.format(workspace_id=self._workspace_id)
        body = {
            "displayName": display_name,
            "definition": {"parts": _build_definition_parts(model)},
        }
        resp = self._session.post(
            url, json=body, headers=self._headers(), timeout=120,
        )
        return self._handle_create_response(resp)

    def update(
        self, *, semantic_model_id: str, model: PBIModel,
    ) -> FabricApiResult:
        url = _SEMANTIC_MODEL_UPDATE_URL.format(
            workspace_id=self._workspace_id, model_id=semantic_model_id,
        )
        body = {"definition": {"parts": _build_definition_parts(model)}}
        resp = self._session.post(
            url, json=body, headers=self._headers(), timeout=120,
        )
        if resp.status_code == 200 or resp.status_code == 201:
            return FabricApiResult(
                semantic_model_id=semantic_model_id,
                state="Succeeded",
                operation_id=None,
            )
        if resp.status_code == 202:
            op_id = self._poll_operation(resp)
            return FabricApiResult(
                semantic_model_id=semantic_model_id,
                state="Succeeded",
                operation_id=op_id,
            )
        raise RuntimeError(
            f"Fabric updateDefinition failed: HTTP {resp.status_code}: "
            f"{resp.text[:600]}"
        )

    def _handle_create_response(self, resp: requests.Response) -> FabricApiResult:
        if resp.status_code in (200, 201):
            body = resp.json()
            return FabricApiResult(
                semantic_model_id=str(body.get("id") or ""),
                state="Succeeded",
                operation_id=None,
            )
        if resp.status_code == 202:
            op_id = self._poll_operation(resp)
            # Result of the LRO contains the created item; the LRO result
            # endpoint exposes it.
            location = resp.headers.get("Location")
            result_url = (
                location.replace("/operations/", "/operations/")
                + "/result"
                if location and "/result" not in location
                else f"https://api.fabric.microsoft.com/v1/operations/{op_id}/result"
            )
            res = self._session.get(
                result_url, headers=self._headers(), timeout=30,
            )
            model_id = ""
            if res.ok:
                model_id = str(res.json().get("id") or "")
            return FabricApiResult(
                semantic_model_id=model_id,
                state="Succeeded",
                operation_id=op_id,
            )
        raise RuntimeError(
            f"Fabric semanticModels POST failed: HTTP {resp.status_code}: "
            f"{resp.text[:600]}"
        )

    def _poll_operation(self, initial_resp: requests.Response) -> str:
        location = initial_resp.headers.get("Location")
        if not location:
            raise RuntimeError(
                f"Fabric LRO response missing Location header: "
                f"status={initial_resp.status_code}, body={initial_resp.text[:300]}"
            )
        retry_after_hdr = initial_resp.headers.get("Retry-After")
        interval = float(retry_after_hdr) if retry_after_hdr else self._poll_interval
        deadline = time.monotonic() + self._poll_timeout
        op_id = location.rstrip("/").rsplit("/", 1)[-1]
        last_body: Any = None
        while time.monotonic() < deadline:
            time.sleep(interval)
            resp = self._session.get(location, headers=self._headers(), timeout=30)
            if not resp.ok:
                raise RuntimeError(
                    f"Fabric LRO status GET failed: HTTP {resp.status_code}: "
                    f"{resp.text[:600]}"
                )
            last_body = resp.json()
            state = str(last_body.get("status") or "")
            if state == "Succeeded":
                return op_id
            if state == "Failed":
                raise RuntimeError(
                    f"Fabric LRO failed: {last_body!r}",
                )
            retry_after_hdr = resp.headers.get("Retry-After")
            interval = (
                float(retry_after_hdr) if retry_after_hdr else self._poll_interval
            )
        raise RuntimeError(
            f"Fabric LRO did not finish within {self._poll_timeout}s; "
            f"last response: {last_body!r}"
        )


def push_semantic_model(
    client: FabricApiClient,
    *,
    model: PBIModel,
    display_name: str,
    overwrite_existing: bool,
) -> FabricApiResult:
    """Create the semantic model in the workspace, or update it if one with
    the same displayName already exists and ``overwrite_existing`` is True.
    """
    existing_id = client.find_by_display_name(display_name)
    if existing_id is None:
        return client.create(display_name=display_name, model=model)
    if not overwrite_existing:
        raise RuntimeError(
            f"Fabric semantic model {display_name!r} already exists "
            f"(id={existing_id}). Tick 'Merge into existing model' to "
            f"overwrite, or pick a new name.",
        )
    return client.update(semantic_model_id=existing_id, model=model)
