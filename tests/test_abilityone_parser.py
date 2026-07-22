from __future__ import annotations

import io
import zipfile

import pytest

from tens_hq.connectors.abilityone import (
    ConnectorError,
    SourceKind,
    normalize_zip,
    parse_service_location,
    parse_workbook,
    service_location_matches,
)


def workbook(headers: list[str], rows: list[list[object]], *, title_rows: int = 2) -> bytes:
    def col(index: int) -> str:
        result = ""
        index += 1
        while index:
            index, rem = divmod(index - 1, 26)
            result = chr(65 + rem) + result
        return result

    xml_rows: list[str] = []
    for row_number, values in enumerate([["ReconRadar export"]] * title_rows + [headers] + rows, 1):
        cells = []
        for index, value in enumerate(values):
            text = "" if value is None else str(value)
            cells.append(f'<c r="{col(index)}{row_number}" t="inlineStr"><is><t>{text}</t></is></c>')
        xml_rows.append(f'<row r="{row_number}">' + "".join(cells) + "</row>")
    sheet = "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData>" + "".join(xml_rows) + "</sheetData></worksheet>"
    workbook_xml = "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><sheets><sheet name=\"Export\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>"
    rels = "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/></Relationships>"
    types = "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"xml\" ContentType=\"application/xml\"/></Types>"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()


def test_nib_schema_and_deduplication() -> None:
    data = workbook(
        ["Nonprofit Agency Name", "City", "State", "Zip Code"],
        [["Agency A", "Denver", "CO", "80202"], ["Agency A", "Denver", "CO", "80202"]],
    )
    result = parse_workbook(SourceKind.NIB_NPA, data)
    assert result.record_count == 1
    assert result.duplicate_rows == 1
    assert result.records[0]["zip_code"] == "80202"


def test_exact_schema_accepts_unordered_columns_and_records_order() -> None:
    data = workbook(
        ["State", "Zip Code", "City", "Nonprofit Agency Name"],
        [["CO", "80202", "Denver", "Agency A"]],
    )
    result = parse_workbook(SourceKind.NIB_NPA, data)
    assert result.records[0]["agency_name"] == "Agency A"
    assert result.header_order == ("State", "Zip Code", "City", "Nonprofit Agency Name")


def test_service_location_is_retained_when_unparsed() -> None:
    data = workbook(
        ["CNA", "Service Type", "Service Location", "Mandatory for Contracting Activity"],
        [["CNA A", "Janitorial", "Denver, CO 80202", "Yes"], ["CNA B", "Other", "unknown", "No"]],
    )
    result = parse_workbook(SourceKind.ABILITYONE_SERVICES, data)
    assert result.record_count == 2
    assert result.unparsed_rows == 1
    assert result.records[1]["service_location"] == "unknown"
    assert service_location_matches(result.records[0], city="Denver", state="CO", zip_code="80202")


def test_service_location_is_required_but_cna_and_mandatory_are_nullable() -> None:
    data = workbook(
        ["CNA", "Service Type", "Service Location", "Mandatory for Contracting Activity"],
        [["CNA A", "Janitorial", None, None]],
    )
    result = parse_workbook(SourceKind.ABILITYONE_SERVICES, data)
    assert result.unparsed_rows == 1
    assert result.partial
    assert result.records[0]["location_parse_status"] == "UNPARSED"
    assert result.records[0]["cna"] == "CNA A"
    assert result.records[0]["service_type"] == "Janitorial"

    location_only = workbook(
        ["CNA", "Service Type", "Service Location", "Mandatory for Contracting Activity"],
        [[None, None, "Denver, CO", None]],
    )
    nullable_result = parse_workbook(SourceKind.ABILITYONE_SERVICES, location_only)
    assert nullable_result.unparsed_rows == 0
    assert nullable_result.records[0]["location_parse_status"] == "PARSED"
    assert result.records[0]["mandatory_for_contracting_activity"] is None


def test_invalid_npa_row_is_rejected_from_evidence() -> None:
    data = workbook(
        ["Nonprofit Agency Name", "City", "State", "Zip Code"],
        [["Agency A", "Denver", "CO", "80202"], [None, "Denver", "CO", "80202"]],
    )
    result = parse_workbook(SourceKind.NIB_NPA, data)
    assert result.record_count == 1
    assert result.rejected_rows == 1
    assert result.partial


def test_header_must_be_exact_and_in_first_25_rows() -> None:
    data = workbook(["Nonprofit Agency Name", "City", "State", "Zip Code", "extra"], [["x", "y", "CO", "1"]])
    with pytest.raises(ConnectorError) as error:
        parse_workbook(SourceKind.NIB_NPA, data)
    assert error.value.code == "HEADER_NOT_FOUND"


def test_zip_semantics() -> None:
    assert normalize_zip(2108) == "02108"
    assert normalize_zip("02108-1234") == "02108-1234"
    assert parse_service_location("Boston, MA 02108-1234").zip_code == "02108-1234"
    assert parse_service_location("Services in multiple regions").state is None
    assert parse_service_location("Locations or as assigned").state is None
