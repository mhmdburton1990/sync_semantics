"""Package a PBIModel as a `.pbit` template (an OPC/ZIP of Power BI parts).

A `.pbit` is a template: it carries the model *schema* (no data) plus a report
layout. The key parts:

- ``DataModelSchema`` — the TMSL model definition (JSON). This is what makes it
  a template; the ``DataModel`` part (binary VertiPaq archive) belongs only to a
  ``.pbix``. Power BI Desktop reads text parts as UTF-16LE with a BOM.
- ``Report/Layout`` — the report definition (legacy report format). A ``.pbit``
  is fundamentally a report package, so Desktop cannot open one without it.
- ``Version`` / ``[Content_Types].xml`` — OPC packaging metadata. Every part is
  extensionless, so each needs an explicit ``Override`` in ``[Content_Types].xml``.

Editing ``.pbit`` internals is not a Microsoft-supported authoring path, so the
exact shape here targets what Desktop emits/accepts and may need adjustment
against a specific Desktop version.
"""

from __future__ import annotations

import codecs
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from databricks_to_pbi.writers.pbi_model import PBIModel
from databricks_to_pbi.writers.tmsl import render_tmsl

__all__ = ["pbit_bytes", "write_pbit"]


_VERSION_MARKER = "3.0"

# Power BI Desktop writes/reads .pbit text parts as UTF-16LE with a BOM.
_UTF16LE_BOM = codecs.BOM_UTF16_LE

# Parts (other than the OPC metadata) that carry JSON text.
_JSON_PARTS = ("DataModelSchema", "Report/Layout", "Metadata", "Settings")


def _utf16le(text: str) -> bytes:
    return _UTF16LE_BOM + text.encode("utf-16-le")


def _content_types_xml(parts: tuple[str, ...]) -> str:
    """OPC content-types with an explicit Override for every extensionless part.

    Every part in a .pbit is extensionless, so a Default-by-extension rule never
    matches; each part must be declared with an Override or the package is
    invalid OPC and Desktop refuses to open it.
    """
    overrides = "\n".join(
        f'  <Override PartName="/{p}" ContentType="application/json"/>'
        for p in parts
    )
    return (
        '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        f"{overrides}\n"
        "</Types>\n"
    )


def _report_layout() -> str:
    """A minimal legacy report layout with a single blank page.

    Kept theme-free on purpose: referencing a theme resource package would
    require the matching StaticResources parts, and a missing one corrupts the
    template. An empty page is enough for Desktop to open the template so the
    user can build the report against the synced model.
    """
    layout: dict[str, Any] = {
        "id": 0,
        "sections": [
            {
                "id": 0,
                "name": "ReportSection",
                "displayName": "Page 1",
                "filters": "[]",
                "ordinal": 0,
                "visualContainers": [],
                "config": "{}",
                "displayOption": 1,
                "width": 1280,
                "height": 720,
            },
        ],
        "config": "{}",
        "layoutOptimization": 0,
    }
    return json.dumps(layout)


def _write_pbit_to(zf: zipfile.ZipFile, model: PBIModel) -> None:
    tmsl = render_tmsl(model)
    data_model = tmsl["createOrReplace"]["database"]

    # Order chosen to mirror what Desktop emits (metadata parts first is fine;
    # OPC is order-independent, but keep it stable for reproducible packages).
    zf.writestr("Version", _VERSION_MARKER)
    zf.writestr("DataModelSchema", _utf16le(json.dumps(data_model, indent=2)))
    zf.writestr("Report/Layout", _utf16le(_report_layout()))
    zf.writestr("Metadata", _utf16le(json.dumps({"version": _VERSION_MARKER})))
    zf.writestr("Settings", _utf16le(json.dumps({"version": _VERSION_MARKER})))
    zf.writestr("[Content_Types].xml", _content_types_xml((*_JSON_PARTS, "Version")))


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
