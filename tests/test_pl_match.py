"""Offline unit tests for the R2b PL-services cross-reference matcher.

Records are produced by the *real* AbilityOne Services connector parsing a
minimal in-memory workbook, so the tests exercise the same parse -> match path
the UI uses (location parsing, unparsed-row handling, dedup) rather than
hand-built normalized dicts.
"""

from __future__ import annotations

import io
import zipfile

from tens_hq.connectors import SourceKind
from tens_hq.connectors.abilityone import parse_workbook
from tens_hq.pl_match import (
    PLMatchResult,
    PLServiceMatch,
    find_pl_service_matches,
    normalize_service_type,
    pl_service_match_lines,
)

_SERVICES_HEADERS = ["CNA", "Service Type", "Service Location", "Mandatory for Contracting Activity"]


def _services_workbook(rows: list[list[object]]) -> bytes:
    """Build a minimal .xlsx the Services connector can parse (stdlib only)."""

    def col(index: int) -> str:
        result = ""
        index += 1
        while index:
            index, rem = divmod(index - 1, 26)
            result = chr(65 + rem) + result
        return result

    xml_rows: list[str] = []
    for row_number, values in enumerate([["ReconRadar export"], _SERVICES_HEADERS] + rows, 1):
        cells = []
        for index, value in enumerate(values):
            text = "" if value is None else str(value)
            cells.append(f'<c r="{col(index)}{row_number}" t="inlineStr"><is><t>{text}</t></is></c>')
        xml_rows.append(f'<row r="{row_number}">' + "".join(cells) + "</row>")
    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>" + "".join(xml_rows) + "</sheetData></worksheet>"
    )
    workbook_xml = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Export" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    types = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/></Types>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()


def _records(rows: list[list[object]]):
    return parse_workbook(SourceKind.ABILITYONE_SERVICES, _services_workbook(rows)).records


# A small national-directory slice: two lines at Denver, one at Aurora, and a
# statewide line that cannot parse to a city.
_ROWS = [
    ["CNA A", "Janitorial", "Denver, CO 80202", "Yes"],
    ["CNA A", "Grounds Maintenance", "Denver, CO", "No"],
    ["CNA B", "Janitorial", "Aurora, CO", "Yes"],
    ["CNA C", "Custodial", "Colorado", "Yes"],
]


def test_normalize_service_type_casefolds_collapses_and_handles_none() -> None:
    assert normalize_service_type(None) == ""
    assert normalize_service_type("   ") == ""
    assert normalize_service_type("  Grounds   Maintenance ") == "grounds maintenance"
    assert normalize_service_type("JANITORIAL") == normalize_service_type("janitorial")


def test_exact_city_state_and_service_type_split() -> None:
    result = find_pl_service_matches(_records(_ROWS), city="Denver", state="CO", service_type="Janitorial")
    assert isinstance(result, PLMatchResult)
    # Denver/CO has exactly two parsed lines; Aurora and statewide are excluded.
    assert result.same_location_count == 2
    assert [m.service_type for m in result.service_type_matches] == ["Janitorial"]
    assert [m.service_type for m in result.same_location_other] == ["Grounds Maintenance"]


def test_service_type_equality_is_case_and_whitespace_insensitive() -> None:
    result = find_pl_service_matches(_records(_ROWS), city="Denver", state="CO", service_type="  janitorial ")
    assert [m.service_type for m in result.service_type_matches] == ["Janitorial"]


def test_blank_query_never_matches_blank_to_blank() -> None:
    # A blank service-type query must put every same-location row in "other",
    # never manufacture an exact match (including against a blank row value).
    for query in (None, "", "   "):
        result = find_pl_service_matches(_records(_ROWS), city="Denver", state="CO", service_type=query)
        assert result.service_type_matches == ()
        assert result.same_location_count == 2
        assert result.queried_service_type is None


def test_statewide_and_unparsed_rows_never_match() -> None:
    # The "Colorado" (statewide) row parses UNPARSED and must never appear, even
    # when the state matches -- the exact city gate fails closed (B2 mechanism).
    result = find_pl_service_matches(_records(_ROWS), city="Denver", state="CO", service_type="Custodial")
    surfaced = result.service_type_matches + result.same_location_other
    assert all(m.parsed_state == "CO" and m.parsed_city == "Denver" for m in surfaced)
    assert all(m.service_location != "Colorado" for m in surfaced)


def test_other_city_is_excluded() -> None:
    result = find_pl_service_matches(_records(_ROWS), city="Denver", state="CO", service_type="Janitorial")
    surfaced = result.service_type_matches + result.same_location_other
    assert all(m.parsed_city == "Denver" for m in surfaced)
    # The Aurora "Janitorial" row is a different city and is not a match.
    assert all(not (m.parsed_city == "Aurora") for m in surfaced)


def test_no_match_is_absence_not_negative() -> None:
    # A worksite with no PL line at that exact city is evidence-absence, not a
    # negative finding: an empty result with zero counts.
    result = find_pl_service_matches(_records(_ROWS), city="Boulder", state="CO", service_type="Janitorial")
    assert result.has_any is False
    assert result.same_location_count == 0


def test_zip_narrows_the_match() -> None:
    # A ZIP query matches only the row carrying that ZIP; the no-ZIP Denver row
    # is excluded because it has no parsed ZIP to compare.
    result = find_pl_service_matches(
        _records(_ROWS), city="Denver", state="CO", service_type="Janitorial", zip_code="80202"
    )
    assert result.same_location_count == 1
    assert result.service_type_matches[0].parsed_zip == "80202"


def test_render_escapes_markdown_in_untrusted_values() -> None:
    # A hostile uploaded filename or workbook cell must not forge a clickable
    # Markdown link (or inject code/emphasis) into a packet whose value is
    # provenance integrity.
    hostile_match = PLServiceMatch(
        cna="[owned by us](https://attacker.example)",
        service_type="Custodial](https://phish.example) `code` **bold**",
        service_location="Denver, CO",
        parsed_city="Denver",
        parsed_state="CO",
        parsed_zip=None,
        mandatory_for_contracting_activity=True,
        source_row=3,
    )
    result = PLMatchResult(
        city="Denver",
        state="CO",
        queried_service_type="Custodial](https://phish.example)",
        source_label="[Official PL Source](https://attacker.example).xlsx",
        retrieved_at="2026-07-15",
        synthetic_sample=False,
        service_type_matches=(hostile_match,),
        same_location_other=(),
    )
    rendered = "\n".join(pl_service_match_lines(result))
    # The link-forming sequences are broken by escaping...
    assert "](https://attacker.example)" not in rendered
    assert "](https://phish.example)" not in rendered
    # ...the escaped bracket/paren survive as literal text...
    assert "\\]" in rendered and "\\(" in rendered
    # ...and code/emphasis metacharacters are escaped too.
    assert "\\`code\\`" in rendered
    assert "\\*\\*bold\\*\\*" in rendered


def test_provenance_fields_pass_through() -> None:
    result = find_pl_service_matches(
        _records(_ROWS),
        city="Denver",
        state="CO",
        service_type="Janitorial",
        source_label="PL_Services_2026Q2.xlsx",
        retrieved_at="2026-07-15",
        synthetic_sample=True,
    )
    assert result.source_label == "PL_Services_2026Q2.xlsx"
    assert result.retrieved_at == "2026-07-15"
    assert result.synthetic_sample is True
