"""Strict, offline parsers for the approved AbilityOne workbook exports.

Only three source kinds are supported.  The reader intentionally implements
the small XLSX subset needed for tabular exports with the Python standard
library instead of pulling a spreadsheet engine into the demo runtime.  A
future implementation may replace ``_read_xlsx_rows`` with a pinned parser;
the connector and normalized-record contract remain unchanged.
"""

from __future__ import annotations

import io
import posixpath
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from xml.etree import ElementTree as ET

from .base import (
    ConnectorError,
    ConnectorResult,
    NormalizedRecord,
    SourceKind,
    SourceMetadata,
    WorkbookConnector,
    coerce_source_kind,
    stable_row_hash,
)

# Conservative defaults keep an uploaded workbook bounded even when a caller
# does not provide an explicit policy.  Limits can be overridden per connector
# for a controlled offline deployment, but never with a negative value.
DEFAULT_MAX_WORKBOOK_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_UNCOMPRESSED_BYTES = 40 * 1024 * 1024
DEFAULT_MAX_ENTRY_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_XML_RATIO = 100.0
DEFAULT_MAX_ROWS = 100_000
DEFAULT_MAX_CELLS = 500_000
DEFAULT_MAX_SHEETS = 32
DEFAULT_MAX_ARCHIVE_MEMBERS = 200
DEFAULT_MAX_COLUMNS = 100
DEFAULT_MAX_CELL_CHARS = 500
HEADER_SCAN_ROWS = 25


SCHEMAS: dict[SourceKind, tuple[tuple[str, str], ...]] = {
    SourceKind.NIB_NPA: (
        ("Nonprofit Agency Name", "agency_name"),
        ("City", "city"),
        ("State", "state"),
        ("Zip Code", "zip_code"),
    ),
    SourceKind.SOURCEAMERICA_NPA: (
        ("Nonprofit Agency Name", "agency_name"),
        ("City", "city"),
        ("State", "state"),
        ("Zip Code", "zip_code"),
    ),
    SourceKind.ABILITYONE_SERVICES: (
        ("CNA", "cna"),
        ("Service Type", "service_type"),
        ("Service Location", "service_location"),
        ("Mandatory for Contracting Activity", "mandatory_for_contracting_activity"),
    ),
}


def expected_headers(source_kind: SourceKind | str) -> tuple[str, ...]:
    return tuple(header for header, _ in SCHEMAS[coerce_source_kind(source_kind)])


def projected_fields(source_kind: SourceKind | str) -> tuple[str, ...]:
    return tuple(field for _, field in SCHEMAS[coerce_source_kind(source_kind)])


_STATE_NAMES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "puerto rico": "PR",
    "guam": "GU",
    "virgin islands": "VI",
}
_STATE_CODES = set(_STATE_NAMES.values())


def normalize_state(value: Any) -> str | None:
    """Normalize a state code/name without fuzzy matching."""

    if value is None:
        return None
    text = _clean_text(value)
    if not text:
        return None
    upper = text.upper().replace(".", "")
    if upper in _STATE_CODES:
        return upper
    return _STATE_NAMES.get(text.casefold())


def normalize_zip(value: Any) -> str | None:
    """Return canonical ZIP or ZIP+4; invalid values return ``None``.

    A five-digit query matches only the five-digit portion of a ZIP+4 record;
    a ZIP+4 query must match all nine digits.  This is intentionally not a
    prefix/fuzzy comparison.
    """

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        text = str(value)
    else:
        text = _clean_text(value).replace(" ", "")
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if re.fullmatch(r"\d{5}", text):
        return text
    if re.fullmatch(r"\d{4}", text):
        # Excel commonly turns a leading-zero ZIP into a 4-digit number.
        return "0" + text
    if re.fullmatch(r"\d{9}", text):
        return f"{text[:5]}-{text[5:]}"
    if re.fullmatch(r"\d{5}-\d{4}", text):
        return text
    return None


def _zip_base(value: str | None) -> str | None:
    return value[:5] if value else None


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).replace("\u00a0", " ")
    return " ".join(text.strip().split())


def _canonical_city(value: Any) -> str:
    # Punctuation is retained: matching "St. Louis" to "St Louis" would be
    # fuzzy and could produce a false positive.  Case and whitespace are not
    # substantive differences in an operator-entered location.
    return _clean_text(value).casefold()


@dataclass(frozen=True)
class ParsedServiceLocation:
    raw: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    status: str
    note: str | None = None

    @property
    def parsed(self) -> bool:
        return self.status == "PARSED"


def parse_service_location(value: Any) -> ParsedServiceLocation:
    """Parse common ``City, ST [ZIP]`` exports with an explicit fallback.

    If a location cannot be parsed, the caller still receives a record with
    ``status='UNPARSED'`` and the source location text.  No row is silently
    discarded.  The parser accepts full state names as a convenience, then
    canonicalizes them to their two-letter code.
    """

    raw = _clean_text(value)
    if not raw:
        # A local feasibility case cannot treat a blank location as a match.
        # Keep the row in the parser result for quarantine/audit, but mark it
        # unparsed so it cannot become current location evidence.
        return ParsedServiceLocation(None, None, None, None, "UNPARSED", "service location is empty")
    text = raw.strip(" ,")
    zip_match = re.search(r"(?:^|\s)(\d{5}(?:-\d{4})?)$", text)
    zip_code = normalize_zip(zip_match.group(1)) if zip_match else None
    if zip_match:
        text = text[: zip_match.start()].strip(" ,")

    city: str | None = None
    state: str | None = None
    if "," in text:
        city_part, rest = text.split(",", 1)
        city = _clean_text(city_part)
        state = normalize_state(rest)
        # If there is a comma but trailing labels remain, only a standalone
        # state token is acceptable; this prevents accidental fuzzy parsing.
        if state is None:
            state_token = _clean_text(rest).casefold()
            state = _STATE_NAMES.get(state_token)
    else:
        words = text.split()
        # Find a state token at the end, preferring the longest full name.
        for index in range(len(words) - 1, -1, -1):
            candidate = " ".join(words[index:])
            state = normalize_state(candidate)
            if state is not None:
                city = _clean_text(" ".join(words[:index]))
                break

    if not state:
        # Preserve a state token from a labelled/statewide value even when the
        # city grammar is not exact.  The scanner may retain such a row as a
        # broad, state-level candidate, but it can never satisfy city-level
        # readiness until an analyst verifies a parsed local address.
        for token in re.findall(r"\b[A-Za-z]{2,}\b", text):
            # Two-letter postal codes are conventionally uppercase in the
            # export.  Requiring that form prevents ordinary words such as
            # "in" and "or" from becoming Indiana/Oregon broad candidates;
            # full state names remain case-insensitive.
            if len(token) == 2 and token.upper() != token:
                continue
            candidate = normalize_state(token)
            if candidate:
                state = candidate
    if not city or not state:
        return ParsedServiceLocation(raw, city or None, state, zip_code, "UNPARSED", "location format not recognized")
    # A ZIP-looking suffix that failed normalization is an invalid location,
    # not a reason to discard the source row.
    if zip_match and zip_code is None:
        return ParsedServiceLocation(raw, city, state, None, "UNPARSED", "invalid ZIP")
    return ParsedServiceLocation(raw, city, state, zip_code, "PARSED")


def service_location_matches(
    record: NormalizedRecord | Mapping[str, Any],
    *,
    city: str,
    state: str,
    zip_code: str | None = None,
) -> bool:
    """Exact city/state matching with explicit ZIP semantics.

    The function does not perform proximity or substring matching.  A 5-digit
    query matches the base of a ZIP+4, while a ZIP+4 query is exact.
    """

    values = record.values if isinstance(record, NormalizedRecord) else record
    if str(values.get("location_parse_status", "")) != "PARSED":
        return False
    wanted_state = normalize_state(state)
    if not wanted_state or _canonical_city(city) != _canonical_city(values.get("parsed_city")):
        return False
    if str(values.get("parsed_state", "")) != wanted_state:
        return False
    if zip_code is None:
        return True
    wanted_zip = normalize_zip(zip_code)
    actual_zip = normalize_zip(values.get("parsed_zip"))
    if not wanted_zip or not actual_zip:
        return False
    if "-" in wanted_zip:
        return wanted_zip == actual_zip
    return wanted_zip == _zip_base(actual_zip)


class _XlsxLimits:
    def __init__(
        self,
        *,
        max_workbook_bytes: int = DEFAULT_MAX_WORKBOOK_BYTES,
        max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
        max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES,
        max_xml_ratio: float = DEFAULT_MAX_XML_RATIO,
        max_rows: int = DEFAULT_MAX_ROWS,
        max_cells: int = DEFAULT_MAX_CELLS,
        max_sheets: int = DEFAULT_MAX_SHEETS,
        max_archive_members: int = DEFAULT_MAX_ARCHIVE_MEMBERS,
        max_columns: int = DEFAULT_MAX_COLUMNS,
        max_cell_chars: int = DEFAULT_MAX_CELL_CHARS,
    ) -> None:
        values = (
            max_workbook_bytes,
            max_uncompressed_bytes,
            max_entry_bytes,
            max_rows,
            max_cells,
            max_sheets,
            max_archive_members,
            max_columns,
            max_cell_chars,
        )
        if any(not isinstance(v, int) or v <= 0 for v in values) or not isinstance(max_xml_ratio, (int, float)) or max_xml_ratio <= 0:
            raise ValueError("workbook limits must be positive")
        self.max_workbook_bytes = max_workbook_bytes
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.max_entry_bytes = max_entry_bytes
        self.max_xml_ratio = float(max_xml_ratio)
        self.max_rows = max_rows
        self.max_cells = max_cells
        self.max_sheets = max_sheets
        self.max_archive_members = max_archive_members
        self.max_columns = max_columns
        self.max_cell_chars = max_cell_chars


def _xml_namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _q(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}" if namespace else name


def _preflight(payload: bytes | bytearray | memoryview, limits: _XlsxLimits) -> zipfile.ZipFile:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ConnectorError("INVALID_INPUT")
    size = len(payload)
    if size <= 0:
        raise ConnectorError("SOURCE_REQUIRED")
    if size > limits.max_workbook_bytes:
        raise ConnectorError("WORKBOOK_TOO_LARGE")
    # OLE compound-file magic is the usual encrypted Office workbook form.
    prefix = bytes(payload[:8])
    if prefix == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ConnectorError("ZIP_ENCRYPTED")
    if not prefix.startswith(b"PK"):
        raise ConnectorError("ZIP_INVALID")
    try:
        archive = zipfile.ZipFile(io.BytesIO(bytes(payload)), "r")
        infos = archive.infolist()
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise ConnectorError("ZIP_INVALID") from None
    if len(infos) > limits.max_archive_members:
        archive.close()
        raise ConnectorError("ZIP_BOMB")
    total = 0
    has_macro = False
    for info in infos:
        # Encryption bit in a ZIP member's general-purpose flags.
        if info.flag_bits & 0x1:
            archive.close()
            raise ConnectorError("ZIP_ENCRYPTED")
        name = info.filename.replace("\\", "/")
        lowered = name.casefold()
        # Reject path traversal and package parts that could carry active
        # content or an unapproved external data connection.  These checks
        # happen before reading any member and intentionally expose no name.
        parts = name.split("/")
        if name.startswith("/") or any(part in {"", ".", ".."} for part in parts[:-1]) or ".." in parts:
            archive.close()
            raise ConnectorError("ZIP_INVALID")
        if any(token in lowered for token in ("activex", "embeddings", "externallinks", "connections")):
            archive.close()
            raise ConnectorError("ZIP_INVALID")
        if "vbaproject" in lowered or lowered.endswith(".bin") and "vba" in lowered:
            has_macro = True
        if info.file_size < 0 or info.file_size > limits.max_entry_bytes:
            archive.close()
            raise ConnectorError("ZIP_BOMB")
        total += info.file_size
        if total > limits.max_uncompressed_bytes:
            archive.close()
            raise ConnectorError("ZIP_BOMB")
        compressed = max(info.compress_size, 1)
        if info.file_size / compressed > limits.max_xml_ratio:
            archive.close()
            raise ConnectorError("ZIP_BOMB")
    try:
        content_types = archive.read("[Content_Types].xml")
        lowered_types = content_types.lower()
        if b"macroenabled" in lowered_types or b"vbaproject" in lowered_types or has_macro:
            archive.close()
            raise ConnectorError("ZIP_MACRO")
        # External hyperlinks/connections can be hidden in worksheet
        # relationship parts even when no externalLinks directory exists.
        for member in archive.namelist():
            if member.casefold().endswith(".rels"):
                rel_bytes = archive.read(member).lower()
                if b'targetmode="external"' in rel_bytes or b"externalLink".lower() in rel_bytes:
                    archive.close()
                    raise ConnectorError("ZIP_INVALID")
    except KeyError:
        archive.close()
        raise ConnectorError("ZIP_INVALID") from None
    return archive


def _read_xml(archive: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        raw = archive.read(name)
        return ET.fromstring(raw)
    except (KeyError, OSError, ValueError, ET.ParseError, UnicodeError):
        raise ConnectorError("WORKBOOK_XML") from None


def _relationship_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    root = _read_xml(archive, "xl/_rels/workbook.xml.rels")
    ns = _xml_namespace(root.tag)
    result: dict[str, str] = {}
    for item in root.findall(_q(ns, "Relationship")):
        rid = item.attrib.get("Id")
        target = item.attrib.get("Target")
        target_mode = item.attrib.get("TargetMode", "").casefold()
        rel_type = item.attrib.get("Type", "").casefold()
        if target_mode == "external" or "externallink" in rel_type or "external" in rel_type and "hyperlink" not in rel_type:
            raise ConnectorError("ZIP_INVALID")
        if rid and target:
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = posixpath.normpath(posixpath.join("xl", target))
            result[rid] = target
    return result


def _shared_strings(archive: zipfile.ZipFile, max_cell_chars: int) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = _read_xml(archive, "xl/sharedStrings.xml")
    ns = _xml_namespace(root.tag)
    values: list[str] = []
    for item in root.findall(_q(ns, "si")):
        value = _clean_text("".join(node.text or "" for node in item.iter(_q(ns, "t"))))
        if len(value) > max_cell_chars:
            raise ConnectorError("ROW_LIMIT")
        values.append(value)
    return values


def _column_index(reference: str) -> int | None:
    match = re.match(r"([A-Za-z]+)", reference)
    if not match:
        return None
    value = 0
    for char in match.group(1).upper():
        value = value * 26 + ord(char) - 64
    return value - 1


def _cell_value(cell: ET.Element, ns: str, shared: Sequence[str]) -> Any:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return _clean_text("".join(node.text or "" for node in cell.iter(_q(ns, "t"))))
    node = cell.find(_q(ns, "v"))
    if node is None or node.text is None:
        return None
    text = node.text.strip()
    if cell_type == "s":
        try:
            return shared[int(text)]
        except (ValueError, IndexError):
            raise ConnectorError("WORKBOOK_XML") from None
    if cell_type == "b":
        return text == "1"
    if cell_type in {"str", "e"}:
        return _clean_text(text)
    # Preserve numeric text as int/float where safe; ZIP normalization handles
    # both and mandatory values are normalized separately.
    try:
        number = float(text)
        if number.is_integer():
            return int(number)
        return number
    except ValueError:
        return _clean_text(text)


def _read_xlsx_rows(archive: zipfile.ZipFile, limits: _XlsxLimits) -> list[tuple[str | None, list[tuple[int, list[Any]]]]]:
    workbook = _read_xml(archive, "xl/workbook.xml")
    ns = _xml_namespace(workbook.tag)
    rels = _relationship_targets(archive)
    shared = _shared_strings(archive, limits.max_cell_chars)
    sheets = workbook.find(_q(ns, "sheets"))
    if sheets is None:
        raise ConnectorError("SHEET_NOT_FOUND")
    sheet_nodes = list(sheets.findall(_q(ns, "sheet")))
    if not sheet_nodes or len(sheet_nodes) > limits.max_sheets:
        raise ConnectorError("SHEET_NOT_FOUND")
    output: list[tuple[str | None, list[tuple[int, list[Any]]]]] = []
    total_cells = 0
    for sheet_node in sheet_nodes:
        rid = None
        for key, value in sheet_node.attrib.items():
            if key.rsplit("}", 1)[-1] == "id":
                rid = value
                break
        name = rels.get(rid or "")
        if not name:
            # A few minimal exports omit relationships; use the conventional
            # sheet sequence only as a bounded fallback.
            sheet_id = sheet_node.attrib.get("sheetId", "1")
            name = f"xl/worksheets/sheet{sheet_id}.xml"
        root = _read_xml(archive, name)
        sheet_ns = _xml_namespace(root.tag)
        rows_node = root.find(_q(sheet_ns, "sheetData"))
        if rows_node is None:
            output.append((sheet_node.attrib.get("name"), []))
            continue
        rows: list[tuple[int, list[Any]]] = []
        for position, row in enumerate(rows_node.findall(_q(sheet_ns, "row")), start=1):
            row_number = int(row.attrib.get("r", position)) if row.attrib.get("r", "").isdigit() else position
            cells: dict[int, Any] = {}
            next_index = 0
            for cell in row.findall(_q(sheet_ns, "c")):
                index = _column_index(cell.attrib.get("r", ""))
                if index is None:
                    index = next_index
                if index < 0 or index >= limits.max_columns:
                    raise ConnectorError("ROW_LIMIT")
                next_index = index + 1
                value = _cell_value(cell, sheet_ns, shared)
                if isinstance(value, str) and len(value) > limits.max_cell_chars:
                    raise ConnectorError("ROW_LIMIT")
                cells[index] = value
                total_cells += 1
                if total_cells > limits.max_cells:
                    raise ConnectorError("ROW_LIMIT")
            width = max(cells.keys(), default=-1) + 1
            if width > limits.max_columns:
                raise ConnectorError("ROW_LIMIT")
            rows.append((row_number, [cells.get(index) for index in range(width)]))
            if len(rows) > limits.max_rows:
                raise ConnectorError("ROW_LIMIT")
        output.append((sheet_node.attrib.get("name"), rows))
    return output


def _find_header(
    rows: Sequence[tuple[int, list[Any]]], headers: Sequence[str]
) -> tuple[int, int, dict[str, int], tuple[str, ...]]:
    expected = tuple(headers)
    expected_set = set(expected)
    matches: list[tuple[int, int, dict[str, int], tuple[str, ...]]] = []
    for index, (row_number, values) in enumerate(rows[:HEADER_SCAN_ROWS]):
        normalized = [_clean_text(value) for value in values]
        while normalized and not normalized[-1]:
            normalized.pop()
        # Exact schema as an unordered set: order may vary between official
        # exports, but duplicate/missing/unknown columns fail closed.  Keep
        # the observed order for provenance and map values by header name.
        if len(normalized) != len(set(normalized)):
            continue
        if set(normalized) == expected_set and len(normalized) == len(expected):
            matches.append((index, row_number, {header: col for col, header in enumerate(normalized)}, tuple(normalized)))
    if not matches:
        raise ConnectorError("HEADER_NOT_FOUND")
    if len(matches) > 1:
        raise ConnectorError("HEADER_AMBIGUOUS")
    return matches[0]


def _normalize_mandatory(value: Any) -> tuple[bool | None, str | None]:
    if isinstance(value, bool):
        return value, None
    text = _clean_text(value).casefold()
    if text in {"yes", "y", "true", "1", "mandatory"}:
        return True, None
    if text in {"no", "n", "false", "0", "not mandatory", "optional"}:
        return False, None
    if not text:
        # The source column is required by schema, but its row value is
        # nullable.  Preserve null without treating it as malformed.
        return None, None
    return None, "mandatory flag is not recognized"


def _normalize_npa(raw: Mapping[str, Any]) -> tuple[dict[str, Any], str, str | None]:
    values = {
        "agency_name": _clean_text(raw.get("Nonprofit Agency Name")) or None,
        "city": _clean_text(raw.get("City")) or None,
        "state": normalize_state(raw.get("State")),
        "zip_code": normalize_zip(raw.get("Zip Code")),
    }
    issues: list[str] = []
    if not values["agency_name"]:
        issues.append("agency name is empty")
    if not values["city"]:
        issues.append("city is empty")
    if not values["state"]:
        issues.append("state is invalid")
    raw_zip = _clean_text(raw.get("Zip Code"))
    if raw_zip and not values["zip_code"]:
        issues.append("ZIP is invalid")
    status = "UNPARSED" if issues else "PARSED"
    return values, status, "; ".join(issues) if issues else None


def _normalize_service(raw: Mapping[str, Any]) -> tuple[dict[str, Any], str, str | None]:
    location = parse_service_location(raw.get("Service Location"))
    mandatory, mandatory_note = _normalize_mandatory(raw.get("Mandatory for Contracting Activity"))
    values = {
        "cna": _clean_text(raw.get("CNA")) or None,
        "service_type": _clean_text(raw.get("Service Type")) or None,
        "service_location": location.raw,
        "mandatory_for_contracting_activity": mandatory,
        # Derived values are still allowlisted, deterministic fields used by
        # exact feasibility queries; the original service location is retained
        # so unparsed rows remain reviewable.
        "parsed_city": location.city,
        "parsed_state": location.state,
        "parsed_zip": location.zip_code,
        "location_parse_status": location.status,
    }
    issues: list[str] = []
    # CNA and Service Type are nullable in the official directory export;
    # their absence is an advisory data-quality gap, not a reason to discard
    # an otherwise location-identifiable public row.
    if location.status != "PARSED":
        issues.append(location.note or "service location is unparsed")
    if mandatory_note:
        issues.append(mandatory_note)
    status = "UNPARSED" if issues else "PARSED"
    return values, status, "; ".join(issues) if issues else None


class AbilityOneWorkbookConnector(WorkbookConnector):
    """Connector for exactly one approved source kind."""

    def __init__(
        self,
        source_kind: SourceKind | str,
        *,
        max_workbook_bytes: int = DEFAULT_MAX_WORKBOOK_BYTES,
        max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
        max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES,
        max_xml_ratio: float = DEFAULT_MAX_XML_RATIO,
        max_rows: int = DEFAULT_MAX_ROWS,
        max_cells: int = DEFAULT_MAX_CELLS,
        max_sheets: int = DEFAULT_MAX_SHEETS,
        max_archive_members: int = DEFAULT_MAX_ARCHIVE_MEMBERS,
        max_columns: int = DEFAULT_MAX_COLUMNS,
        max_cell_chars: int = DEFAULT_MAX_CELL_CHARS,
    ) -> None:
        self.source_kind = coerce_source_kind(source_kind)
        self.limits = _XlsxLimits(
            max_workbook_bytes=max_workbook_bytes,
            max_uncompressed_bytes=max_uncompressed_bytes,
            max_entry_bytes=max_entry_bytes,
            max_xml_ratio=max_xml_ratio,
            max_rows=max_rows,
            max_cells=max_cells,
            max_sheets=max_sheets,
            max_archive_members=max_archive_members,
            max_columns=max_columns,
            max_cell_chars=max_cell_chars,
        )

    def parse(
        self,
        workbook: bytes | bytearray | memoryview,
        *,
        metadata: SourceMetadata | None = None,
    ) -> ConnectorResult:
        if metadata is None:
            metadata = SourceMetadata(self.source_kind)
        else:
            try:
                metadata_kind = coerce_source_kind(metadata.source_kind)
                assurance = metadata.assurance.value if hasattr(metadata.assurance, "value") else str(metadata.assurance)
            except Exception:
                raise ConnectorError("PROVENANCE_REQUIRED") from None
            if metadata_kind is not self.source_kind:
                raise ConnectorError("UNSUPPORTED_SOURCE_KIND")
            if assurance != "USER_ATTESTED":
                raise ConnectorError("PROVENANCE_REQUIRED")
        try:
            archive = _preflight(workbook, self.limits)
            try:
                sheets = _read_xlsx_rows(archive, self.limits)
            finally:
                archive.close()
        except ConnectorError:
            raise
        except Exception:
            # No implementation detail (path, XML text, or source cell) is
            # permitted to cross the connector boundary.
            raise ConnectorError("WORKBOOK_XML") from None

        eligible: list[tuple[str | None, list[tuple[int, list[Any]]], int, int, dict[str, int], tuple[str, ...]]] = []
        headers = expected_headers(self.source_kind)
        for sheet_name, rows in sheets:
            try:
                header_index, header_number, header_positions, header_order = _find_header(rows, headers)
            except ConnectorError as exc:
                if exc.code in {"HEADER_NOT_FOUND"}:
                    continue
                raise
            eligible.append((sheet_name, rows, header_index, header_number, header_positions, header_order))
        if not eligible:
            # The workbook had worksheets, but none carried the exact
            # allowlisted header.  Keep the failure distinct from a workbook
            # with no worksheet at all.
            raise ConnectorError("HEADER_NOT_FOUND")
        if len(eligible) > 1:
            raise ConnectorError("HEADER_AMBIGUOUS")
        sheet_name, rows, header_index, header_number, header_positions, header_order = eligible[0]

        # Header names are exact and therefore map deterministically.  Only
        # allowlisted columns are read into the normalized record.
        records: list[NormalizedRecord] = []
        seen: set[str] = set()
        duplicates = 0
        unparsed = 0
        rejected = 0
        anomalies: list[str] = []
        scanned = 0
        for row_number, values in rows[header_index + 1 :]:
            if not any(_clean_text(value) for value in values):
                continue
            scanned += 1
            if scanned > self.limits.max_rows:
                raise ConnectorError("ROW_LIMIT")
            raw = {
                header: values[index] if index < len(values) else None
                for header, index in header_positions.items()
            }
            if self.source_kind in {SourceKind.NIB_NPA, SourceKind.SOURCEAMERICA_NPA}:
                normalized, status, note = _normalize_npa(raw)
            else:
                normalized, status, note = _normalize_service(raw)
            if self.source_kind in {SourceKind.NIB_NPA, SourceKind.SOURCEAMERICA_NPA} and status != "PARSED":
                # NPA exports have four required row fields.  Invalid rows are
                # quarantined from the public evidence set rather than
                # persisted as misleading partial organizations; the count is
                # retained as a safe anomaly for operator review.
                rejected += 1
                if "ROW_REJECTED" not in anomalies:
                    anomalies.append("ROW_REJECTED")
                continue
            row_hash = stable_row_hash(self.source_kind, normalized, projected_fields(self.source_kind))
            if row_hash in seen:
                duplicates += 1
                continue
            seen.add(row_hash)
            if status != "PARSED":
                unparsed += 1
            records.append(
                NormalizedRecord(
                    self.source_kind,
                    normalized,
                    row_hash,
                    source_row=row_number,
                    parse_status=status,
                    parse_note=note,
                )
            )
        return ConnectorResult(
            self.source_kind,
            tuple(records),
            header_number,
            sheet_name,
            scanned,
            duplicate_rows=duplicates,
            unparsed_rows=unparsed,
            anomalies=tuple(anomalies),
            metadata=metadata,
            header_order=header_order,
            rejected_rows=rejected,
        )

    # Familiar names used by callers that treat connectors as parsers.
    parse_workbook = parse
    scan_records = parse


class NIBNPAConnector(AbilityOneWorkbookConnector):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(SourceKind.NIB_NPA, **kwargs)


class SourceAmericaNPAConnector(AbilityOneWorkbookConnector):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(SourceKind.SOURCEAMERICA_NPA, **kwargs)


class AbilityOneServicesConnector(AbilityOneWorkbookConnector):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(SourceKind.ABILITYONE_SERVICES, **kwargs)


# Concise aliases make the connector discoverable without creating alternate
# source kinds or relaxing the strict registry.
NpaConnector = NIBNPAConnector
ServicesConnector = AbilityOneServicesConnector
AbilityOneConnector = AbilityOneWorkbookConnector


def connector_for(source_kind: SourceKind | str, **kwargs: Any) -> AbilityOneWorkbookConnector:
    return AbilityOneWorkbookConnector(source_kind, **kwargs)


def parse_workbook(
    source_kind: SourceKind | str,
    workbook: bytes | bytearray | memoryview,
    *,
    metadata: SourceMetadata | None = None,
    **kwargs: Any,
) -> ConnectorResult:
    """Parse one approved workbook without retaining its bytes."""

    return connector_for(source_kind, **kwargs).parse(workbook, metadata=metadata)


__all__ = [
    "ABILITYONE_SERVICES",
    "AbilityOneConnector",
    "AbilityOneServicesConnector",
    "AbilityOneWorkbookConnector",
    "ConnectorError",
    "NIBNPAConnector",
    "NpaConnector",
    "ParsedServiceLocation",
    "SCHEMAS",
    "SOURCEAMERICA_NPA",
    "ServicesConnector",
    "SourceAmericaNPAConnector",
    "expected_headers",
    "connector_for",
    "normalize_state",
    "normalize_zip",
    "parse_service_location",
    "parse_workbook",
    "projected_fields",
    "service_location_matches",
]

# String constants are intentional convenience exports; SourceKind remains
# the canonical type used by all APIs.
NIB_NPA = SourceKind.NIB_NPA
SOURCEAMERICA_NPA = SourceKind.SOURCEAMERICA_NPA
ABILITYONE_SERVICES = SourceKind.ABILITYONE_SERVICES
