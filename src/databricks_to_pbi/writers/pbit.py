"""Package a PBIModel as a `.pbit` template (zip of TMSL + auxiliary parts)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from databricks_to_pbi.writers.pbi_model import PBIModel
from databricks_to_pbi.writers.tmsl import render_tmsl

__all__ = ["pbit_bytes", "write_pbit"]


_CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="json" ContentType="application/json"/>
  <Default Extension="xml" ContentType="application/xml"/>
</Types>
"""


_VERSION_MARKER = "3.0"


def _connections_json(model: PBIModel) -> str:
    """Minimal connections payload — references the embedded DataModel."""
    return json.dumps({
        "Version": 3,
        "Connections": [
            {
                "Name": f"EntityDataSource_{model.name}",
                "ConnectionString": "Provider=DataModel;",
                "ConnectionType": "EntityDataSource",
            }
        ],
    })


def _write_pbit_to(zf: zipfile.ZipFile, model: PBIModel) -> None:
    tmsl = render_tmsl(model)
    data_model = tmsl["createOrReplace"]["database"]
    zf.writestr("DataModel", json.dumps(data_model, indent=2))
    zf.writestr("Connections", _connections_json(model))
    zf.writestr("[Content_Types].xml", _CONTENT_TYPES_XML)
    zf.writestr("Version", _VERSION_MARKER)


def write_pbit(model: PBIModel, *, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        _write_pbit_to(zf, model)
    return output_path


def pbit_bytes(model: PBIModel) -> bytes:
    """Same content as write_pbit, returned as bytes for in-memory upload."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        _write_pbit_to(zf, model)
    return buf.getvalue()
