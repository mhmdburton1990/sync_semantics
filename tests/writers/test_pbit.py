from __future__ import annotations

import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from databricks_to_pbi.writers.pbi_model import (
    PBIColumn,
    PBIModel,
    PBITable,
)
from databricks_to_pbi.writers.pbit import pbit_bytes, write_pbit

# Text parts in a .pbit are UTF-16LE with a BOM (matches what Power BI Desktop
# writes and expects); the leading two bytes are the little-endian BOM.
_UTF16LE_BOM = b"\xff\xfe"

_OPC_CT_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"


def _model() -> PBIModel:
    return PBIModel(
        name="SalesModel", description=None,
        tables=[
            PBITable(
                name="Orders", storage_mode="direct_query", uc_path="main.sales.orders",
                sql_definition=None,
                columns=[
                    PBIColumn(name="amount", data_type="DECIMAL(18,2)", source_column="amount")
                ],
                measures=[], description=None, annotations=[],
            ),
        ],
        relationships=[], annotations=[],
    )


def _read_utf16(zf: zipfile.ZipFile, name: str) -> object:
    raw = zf.read(name)
    assert raw.startswith(_UTF16LE_BOM), f"{name} must be UTF-16LE with a BOM"
    return json.loads(raw.decode("utf-16"))


def test_pbit_uses_datamodelschema_not_binary_datamodel(tmp_path: Path) -> None:
    # A .pbit template carries the model *schema* (JSON) in a part named
    # `DataModelSchema`. `DataModel` is the binary VertiPaq archive found only
    # in a .pbix — writing JSON under that name makes Desktop treat it as a
    # corrupt binary backup.
    out = tmp_path / "SalesModel.pbit"
    write_pbit(_model(), output_path=out)
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "DataModelSchema" in names
    assert "DataModel" not in names


def test_pbit_has_report_layout_so_desktop_can_open_it(tmp_path: Path) -> None:
    out = tmp_path / "SalesModel.pbit"
    write_pbit(_model(), output_path=out)
    with zipfile.ZipFile(out) as zf:
        assert "Report/Layout" in zf.namelist()
        layout = _read_utf16(zf, "Report/Layout")
    assert isinstance(layout, dict)
    assert len(layout["sections"]) == 1
    assert layout["sections"][0]["displayName"]


def test_pbit_datamodelschema_is_utf16_and_valid_tmsl(tmp_path: Path) -> None:
    out = tmp_path / "SalesModel.pbit"
    write_pbit(_model(), output_path=out)
    with zipfile.ZipFile(out) as zf:
        data = _read_utf16(zf, "DataModelSchema")
    assert data["name"] == "SalesModel"
    assert data["compatibilityLevel"] == 1567
    assert data["model"]["tables"][0]["name"] == "Orders"


def test_pbit_content_types_declares_every_extensionless_part(tmp_path: Path) -> None:
    # OPC requires every package part to be covered by a Default (by extension)
    # or an Override (by part name). All of a .pbit's parts are extensionless,
    # so each needs an explicit Override or Desktop rejects the package.
    out = tmp_path / "SalesModel.pbit"
    write_pbit(_model(), output_path=out)
    with zipfile.ZipFile(out) as zf:
        parts = [n for n in zf.namelist() if n != "[Content_Types].xml"]
        ct_xml = zf.read("[Content_Types].xml").decode("utf-8")
    root = ET.fromstring(ct_xml)
    overrides = {
        o.attrib["PartName"] for o in root.findall(f"{_OPC_CT_NS}Override")
    }
    for part in parts:
        assert f"/{part}" in overrides, f"{part} not covered by a Content_Types Override"


def test_pbit_bytes_matches_write_pbit(tmp_path: Path) -> None:
    out = tmp_path / "SalesModel.pbit"
    write_pbit(_model(), output_path=out)
    disk = out.read_bytes()
    mem = pbit_bytes(_model())
    # Both go through the same packer; member sets must match (zip byte-for-byte
    # equality isn't guaranteed due to timestamps).
    with zipfile.ZipFile(out) as zf:
        disk_names = set(zf.namelist())
    import io

    with zipfile.ZipFile(io.BytesIO(mem)) as zf:
        mem_names = set(zf.namelist())
    assert disk_names == mem_names
    assert disk  # non-empty
