"""Contracts shared by the offline AbilityOne workbook connectors.

The connector layer deliberately deals in *normalized records*, not source
files.  A caller can hand it bytes from an approved upload, but neither the
connector nor the result object keeps the bytes or a local path.  This is a
small boundary that makes it possible to replace the XLSX reader later while
keeping source provenance and reconciliation deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Iterable, Mapping, Protocol, Sequence, runtime_checkable


class SourceKind(str, Enum):
    """The closed set of source kinds this pilot recognizes.

    The first three are analyst-uploaded workbook sources handled by the
    offline XLSX connectors (see :data:`WORKBOOK_SOURCE_KINDS`).  ``CENSUS_ACS``
    is a public API-retrieved geography source handled by a separate connector
    with its own ``retrieve``/``parse`` boundary; it is intentionally NOT a
    workbook kind and must never be routed through the workbook scanner.
    ``USASPENDING_AWARD`` is likewise an API-retrieved single-award contract-facts
    source with its own ``retrieve``/``parse`` boundary; it is NOT a workbook kind
    and must never be routed through the workbook scanner. ``USASPENDING_SUBAWARD``
    is the same public source's subaward listing for one already-resolved award
    (teaming-posture evidence); it is likewise API-retrieved, NOT a workbook kind,
    and must never be routed through the workbook scanner. ``FEDERAL_REGISTER_NOTICES``
    (A4) is the AbilityOne Commission's own Federal Register notice stream (a
    national, page-1-only pull, optionally text-filtered by an analyst search
    term); it is likewise API-retrieved, NOT a workbook kind, and must never be
    routed through the workbook scanner.
    """

    NIB_NPA = "NIB_NPA"
    SOURCEAMERICA_NPA = "SOURCEAMERICA_NPA"
    ABILITYONE_SERVICES = "ABILITYONE_SERVICES"
    CENSUS_ACS = "CENSUS_ACS"
    USASPENDING_AWARD = "USASPENDING_AWARD"
    USASPENDING_SUBAWARD = "USASPENDING_SUBAWARD"
    FEDERAL_REGISTER_NOTICES = "FEDERAL_REGISTER_NOTICES"


# The workbook scanner and its upload UI only accept these three source kinds.
# Enumerate this tuple instead of ``SourceKind`` so an API-only kind such as
# ``CENSUS_ACS`` can never be offered as a workbook upload target.
WORKBOOK_SOURCE_KINDS = (
    SourceKind.NIB_NPA,
    SourceKind.SOURCEAMERICA_NPA,
    SourceKind.ABILITYONE_SERVICES,
)


def coerce_source_kind(value: SourceKind | str) -> SourceKind:
    """Return a validated :class:`SourceKind`.

    ``ValueError`` intentionally contains only the safe, fixed set of names;
    it never echoes a filename, URL, or workbook cell value.
    """

    if isinstance(value, SourceKind):
        return value
    try:
        return SourceKind(str(value).strip().upper())
    except (TypeError, ValueError) as exc:
        raise ValueError("unsupported AbilityOne source kind") from exc


class Assurance(str, Enum):
    """How source provenance was established.

    ``USER_ATTESTED`` is an analyst attestation over an uploaded workbook.
    ``API_RETRIEVED`` is provenance established by a connector's own network
    ``retrieve`` step (server response + retrieval timestamp), used by the
    public API connectors.  Both are approved; anything else fails closed.
    """

    USER_ATTESTED = "USER_ATTESTED"
    API_RETRIEVED = "API_RETRIEVED"


_APPROVED_ASSURANCES = (Assurance.USER_ATTESTED, Assurance.API_RETRIEVED)


def coerce_assurance(value: Assurance | str) -> Assurance:
    """Return a validated :class:`Assurance`, failing closed on anything else.

    The error message is fixed and never echoes the offending value.
    """

    if isinstance(value, Assurance):
        assurance = value
    else:
        try:
            assurance = Assurance(str(value).strip().upper())
        except (TypeError, ValueError) as exc:
            raise ValueError("source provenance must be USER_ATTESTED or API_RETRIEVED") from exc
    if assurance not in _APPROVED_ASSURANCES:
        raise ValueError("source provenance must be USER_ATTESTED or API_RETRIEVED")
    return assurance


@dataclass(frozen=True)
class SourceMetadata:
    """Minimal provenance that may accompany an uploaded workbook.

    ``source_label`` is a display label only.  It is reduced to a basename by
    :func:`safe_source_label` and is never interpolated into error messages.
    The assurance defaults to a user attestation for uploaded workbooks; an API
    connector constructs it with ``Assurance.API_RETRIEVED``.  Any value outside
    the approved set fails closed.
    """

    source_kind: SourceKind | str
    assurance: Assurance | str = Assurance.USER_ATTESTED
    source_label: str | None = None
    source_version: str | None = None
    asserted_by: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_kind", coerce_source_kind(self.source_kind))
        object.__setattr__(self, "assurance", coerce_assurance(self.assurance))
        object.__setattr__(self, "source_label", safe_source_label(self.source_label))

    @property
    def provenance_assurance(self) -> str:
        return self.assurance.value


def safe_source_label(value: str | None) -> str | None:
    """Return a non-sensitive display label, never a path.

    Source labels are optional and are not used for validation.  Stripping
    path components prevents accidental retention of a user's local path in
    case records while retaining a useful filename-like label for audit UI.
    """

    if value is None:
        return None
    text = str(value).replace("\\", "/").split("/")[-1].strip()
    # A label can be shown in an audit table, but control characters are not
    # useful there.  Keep the value bounded as a second line of defence.
    text = "".join(ch for ch in text if ch.isprintable())
    return text[:160] or None


@dataclass(frozen=True)
class NormalizedRecord:
    """A single allowlisted source row.

    ``values`` contains only the columns approved for its source kind.  The
    row hash is computed from canonical values and source kind, never from the
    worksheet row number or a source-provided identifier.
    """

    source_kind: SourceKind
    values: Mapping[str, Any]
    row_hash: str
    source_row: int | None = None
    parse_status: str = "PARSED"
    parse_note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_kind", coerce_source_kind(self.source_kind))
        # Freeze a shallow copy so a repository cannot mutate a parser-owned
        # dictionary after reconciliation.  The values are scalar by design.
        object.__setattr__(self, "values", dict(self.values))
        if len(self.row_hash) != 64 or any(c not in "0123456789abcdef" for c in self.row_hash):
            raise ValueError("normalized record has an invalid row hash")

    @property
    def fields(self) -> Mapping[str, Any]:
        """Alias used by repository implementations."""

        return self.values

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.values)
        result.update(
            {
                "source_kind": self.source_kind.value,
                "row_hash": self.row_hash,
                "source_row": self.source_row,
                "parse_status": self.parse_status,
                "parse_note": self.parse_note,
            }
        )
        return result


@dataclass(frozen=True)
class ConnectorResult:
    """Normalized output and non-sensitive parse diagnostics."""

    source_kind: SourceKind
    records: tuple[NormalizedRecord, ...]
    header_row: int
    sheet_name: str | None
    scanned_rows: int
    duplicate_rows: int = 0
    unparsed_rows: int = 0
    anomalies: tuple[str, ...] = ()
    metadata: SourceMetadata | None = None
    # Physical header order is retained as provenance; values themselves are
    # projected by canonical header names and therefore remain order-agnostic.
    header_order: tuple[str, ...] = ()
    rejected_rows: int = 0

    @property
    def rows(self) -> tuple[NormalizedRecord, ...]:
        return self.records

    @property
    def unparsed_records(self) -> tuple[NormalizedRecord, ...]:
        return tuple(r for r in self.records if r.parse_status != "PARSED")

    @property
    def partial(self) -> bool:
        return bool(self.unparsed_rows or self.rejected_rows or self.anomalies)

    @property
    def rejected_count(self) -> int:
        return self.rejected_rows

    @property
    def record_count(self) -> int:
        return len(self.records)


class ConnectorError(ValueError):
    """A safe, user-facing connector failure.

    ``code`` is suitable for structured audit events.  ``message`` is fixed
    and intentionally omits source names, paths, cell contents, and XML
    parser details.
    """

    _MESSAGES = {
        "INVALID_INPUT": "The uploaded workbook could not be read.",
        "UNSUPPORTED_SOURCE_KIND": "The selected AbilityOne source is not supported.",
        "SOURCE_REQUIRED": "A source workbook is required.",
        "PROVENANCE_REQUIRED": "Source provenance must be user-attested.",
        "WORKBOOK_TOO_LARGE": "The workbook exceeds the permitted size.",
        "ZIP_INVALID": "The uploaded file is not a valid workbook.",
        "ZIP_ENCRYPTED": "Encrypted workbooks are not accepted.",
        "ZIP_MACRO": "Macro-enabled workbooks are not accepted.",
        "ZIP_BOMB": "The workbook archive exceeds safe expansion limits.",
        "WORKBOOK_XML": "The workbook structure could not be read.",
        "SHEET_NOT_FOUND": "No eligible worksheet was found.",
        "HEADER_NOT_FOUND": "The workbook does not contain the required header row.",
        "HEADER_AMBIGUOUS": "The workbook contains more than one eligible header row.",
        "HEADER_SCHEMA": "The workbook columns do not match the required schema.",
        "ROW_LIMIT": "The workbook contains too many rows or cells.",
        "ROW_INVALID": "One or more workbook rows could not be normalized.",
        "REPOSITORY": "The source could not be saved.",
        "IDEMPOTENCY": "The scan idempotency key is invalid.",
        # Public API retrieval failures.  These are fail-loud codes: an upstream
        # error is surfaced, never converted into a silently-empty result.
        "RATE_LIMITED": "The public data source is rate limiting requests. Try again later.",
        "UPSTREAM_UNAVAILABLE": "The public data source is temporarily unavailable.",
        "UPSTREAM_SCHEMA": "The public data source returned an unexpected response.",
        "UPSTREAM_TOO_LARGE": "The public data source returned an unexpectedly large response.",
        "GEOGRAPHY_NOT_FOUND": "The requested geography could not be resolved.",
        "CENSUS_KEY_REQUIRED": (
            "The Census API did not accept this request's API key. Set (or "
            "verify) the TENS_HQ_CENSUS_API_KEY environment variable -- free "
            "signup at api.census.gov/data/key_signup.html -- and retry the "
            "pull."
        ),
        "AWARD_NOT_FOUND": "No USAspending award matched that contract identifier.",
        "AWARD_SEARCH_TRUNCATED": "Too many awards matched that contract identifier to guarantee a unique result; refine the PIID or supply the award id.",
    }

    def __init__(self, code: str, message: str | None = None):
        self.code = str(code)
        # Only allow a fixed message.  Callers may pass a custom message for
        # logging, but the public exception is always safe and bounded.
        self.public_message = self._MESSAGES.get(self.code, "The workbook could not be processed.")
        super().__init__(self.public_message)


@runtime_checkable
class WorkbookConnector(Protocol):
    """Protocol implemented by one-source workbook connectors."""

    source_kind: SourceKind

    def parse(
        self,
        workbook: bytes | bytearray | memoryview,
        *,
        metadata: SourceMetadata | None = None,
    ) -> ConnectorResult:
        ...


@runtime_checkable
class CaseRepositoryProtocol(Protocol):
    """Minimal repository contract consumed by :mod:`tens_hq.scanner`.

    The concrete case-store provides additional methods; this protocol records
    only the calls used by the scanner.
    """

    def start_scan(
        self,
        case_id: str,
        source_kind: str,
        workbook_name: str,
        *,
        workbook_sha256: str | None = None,
        source_uri: str | None = None,
        idempotency_key: str | None = None,
        snapshot: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> Any:
        ...

    def get_case(self, case_id: str) -> Any | None:
        ...

    def get_scan(self, scan_id: str) -> Any | None:
        ...

    def list_resources(
        self,
        case_id: str,
        *,
        source_kind: str | None = None,
        current_only: bool = False,
    ) -> list[Any]:
        ...

    def finalize_scan(
        self,
        scan_id: str,
        rows: Iterable[Mapping[str, Any]] | None = None,
        *,
        success: bool = True,
        status: str | None = None,
        schema_fingerprint: str | None = None,
        source_row_count: int | None = None,
        excluded_row_count: int = 0,
        unparsed_rows: int = 0,
        rejected_rows: int = 0,
        excluded_records: Iterable[Mapping[str, Any]] = (),
    ) -> Any:
        ...

    def fail_scan(self, scan_id: str, error_message: str) -> Any:
        ...


@runtime_checkable
class IdempotencyStore(Protocol):
    def get(self, key: str) -> Any:
        ...

    def put(self, key: str, value: Any) -> None:
        ...


def canonical_value(value: Any) -> str:
    """Canonical scalar representation used for stable row identity."""

    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ").strip()
    # Whitespace differences in a downloaded sheet should not manufacture a
    # new identity.  Case is intentionally folded for identity because names,
    # states, and service labels are not source IDs.
    return " ".join(text.split()).casefold()


def stable_row_hash(source_kind: SourceKind | str, values: Mapping[str, Any], columns: Sequence[str]) -> str:
    """Hash canonical allowlisted values in schema order.

    Length-prefixed components avoid ambiguities such as ``["ab", "c"]`` vs
    ``["a", "bc"]``.  The source kind is included so identical rows from two
    approved sources remain independently reconcilable.
    """

    kind = coerce_source_kind(source_kind).value
    parts = [kind, *[canonical_value(values.get(column)) for column in columns]]
    payload = "\x1f".join(f"{len(part)}:{part}" for part in parts).encode("utf-8")
    return sha256(payload).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "Assurance",
    "CaseRepositoryProtocol",
    "ConnectorError",
    "ConnectorResult",
    "IdempotencyStore",
    "NormalizedRecord",
    "SourceKind",
    "SourceMetadata",
    "WORKBOOK_SOURCE_KINDS",
    "WorkbookConnector",
    "canonical_value",
    "coerce_assurance",
    "coerce_source_kind",
    "safe_source_label",
    "stable_row_hash",
    "utc_now",
]
