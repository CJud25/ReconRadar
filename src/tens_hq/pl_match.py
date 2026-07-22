"""R2b Procurement List cross-reference (pure, offline).

Given normalized AbilityOne PL *Services* records (parsed by the approved
workbook connector) and a pasted contract worksite, surface any Procurement
List service line at the **exact same city/state** as a cited fact-pair --
*"this expiring service matches a service already on the Procurement List at
[loc]".*  This module is **discovery evidence only** and holds hard honesty
invariants so the surface can never quietly overclaim:

* **No score (N1).**  No numeric feasibility / PWin / readiness / match score,
  rank, or percentage -- only cited fact-pairs and plain, labeled counts.
* **Exact city/state, no fuzzy (N4).**  Location matching reuses the connector's
  :func:`service_location_matches` primitive, which fails closed on any row
  whose location did not parse.  A worksite recorded as a base/installation
  name, an adjacent metro city, or a statewide/regional PL line will therefore
  NOT match -- so a no-match is *evidence-absence*, never "not on the
  Procurement List" (AGENTS #13).
* **Not convertibility (AGENTS #11).**  A PL line at a worksite is NOT evidence
  the pasted contract is competable, convertible to the Procurement List, or
  winnable.  R2b concerns growing an *existing* PL line; a new PL addition (R2a)
  is a separate, CNA-submitted suitability determination not asserted here.
* **No holder in the data.**  The PL export names no performing NPA, and its
  ``cna`` column is the Central Nonprofit Agency intermediary (NIB/SourceAmerica),
  not the holder -- so "is this line ours" is always an analyst-confirm step.
* **Service-type equality is a STRING fact.**  A character-equal service type is
  a cited string coincidence, not evidence of the same service or a capability
  fit.

The module is pure (no Streamlit, no network, no case store): callers parse an
uploaded workbook offline, hand the normalized records here, and render the
result.  Rendering (with the standing caveats and provenance stamps) lives in
:func:`pl_service_match_lines`, added alongside the packet builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .connectors import NormalizedRecord, service_location_matches


def normalize_service_type(value: object) -> str:
    """Canonical service-type key: casefold + collapse whitespace.

    ``None`` and blank values normalize to the empty string.  This mirrors the
    connector's ``_canonical_city`` discipline (casefold, whitespace-collapse,
    no fuzzy/substring matching) so that an equality here is an exact,
    explainable *string* fact -- never a fuzzy or semantic match.
    """

    if value is None:
        return ""
    return " ".join(str(value).casefold().split())


@dataclass(frozen=True)
class PLServiceMatch:
    """One PL Services row that parsed to the queried city/state.

    Every field is copied verbatim from the parsed workbook row so the render
    can cite it.  ``cna`` is retained but is the Central Nonprofit Agency, not
    the performing NPA -- callers must never present it as "whose line this is".
    """

    cna: str | None
    service_type: str | None
    service_location: str | None
    parsed_city: str | None
    parsed_state: str | None
    parsed_zip: str | None
    mandatory_for_contracting_activity: bool | None
    source_row: int | None


@dataclass(frozen=True)
class PLMatchResult:
    """The outcome of one worksite cross-reference against an uploaded PL.

    The "no PL uploaded yet" state is represented upstream by passing
    ``pl_matches=None`` to the packet builder (the section is then omitted); a
    ``PLMatchResult`` therefore always describes a workbook that WAS parsed, and
    an empty result is evidence-absence, never "not on the Procurement List"
    (B2). ``service_type_matches`` are same-location rows whose service type is
    *character-equal* to a non-empty analyst query; ``same_location_other`` are
    the remaining same-location rows (presence, not relevance).
    """

    city: str
    state: str
    queried_service_type: str | None
    source_label: str | None
    retrieved_at: str | None
    synthetic_sample: bool
    service_type_matches: tuple[PLServiceMatch, ...]
    same_location_other: tuple[PLServiceMatch, ...]

    @property
    def same_location_count(self) -> int:
        return len(self.service_type_matches) + len(self.same_location_other)

    @property
    def has_any(self) -> bool:
        return self.same_location_count > 0


def _match_from_record(record: NormalizedRecord) -> PLServiceMatch:
    values = record.values
    return PLServiceMatch(
        cna=values.get("cna"),
        service_type=values.get("service_type"),
        service_location=values.get("service_location"),
        parsed_city=values.get("parsed_city"),
        parsed_state=values.get("parsed_state"),
        parsed_zip=values.get("parsed_zip"),
        mandatory_for_contracting_activity=values.get("mandatory_for_contracting_activity"),
        source_row=record.source_row,
    )


def find_pl_service_matches(
    records: Iterable[NormalizedRecord],
    *,
    city: str,
    state: str,
    service_type: str | None = None,
    zip_code: str | None = None,
    source_label: str | None = None,
    retrieved_at: str | None = None,
    synthetic_sample: bool = False,
) -> PLMatchResult:
    """Cross-reference a worksite against parsed PL Services records.

    The location gate is exact city/state (with optional exact ZIP) via
    :func:`service_location_matches`, which fails closed on any row whose
    location did not parse -- statewide/region-only and otherwise-unparsed rows
    are never a silent match.  Among the same-location rows, a row is a
    service-type match only when the analyst supplied a non-empty service type
    AND the row's service type is character-equal to it (never blank == blank);
    all other same-location rows are returned as presence, not relevance.
    """

    queried = normalize_service_type(service_type)
    exact: list[PLServiceMatch] = []
    other: list[PLServiceMatch] = []
    for record in records:
        if not service_location_matches(record, city=city, state=state, zip_code=zip_code):
            continue
        match = _match_from_record(record)
        row_key = normalize_service_type(match.service_type)
        if queried and row_key and row_key == queried:
            exact.append(match)
        else:
            other.append(match)
    return PLMatchResult(
        city=city,
        state=state,
        # A blank / whitespace-only query is recorded as "no service type
        # supplied" so the render never implies the analyst asked for something.
        queried_service_type=(service_type if queried else None),
        source_label=source_label,
        retrieved_at=retrieved_at,
        synthetic_sample=synthetic_sample,
        service_type_matches=tuple(exact),
        same_location_other=tuple(other),
    )


# --- Rendering ---------------------------------------------------------------
#
# The render is intentionally caveat-first: every cross-reference is wrapped in
# the standing honesty statements BEFORE any fact-pair, so a fact-pair can never
# be read in isolation as a route, a convertibility claim, or a holder claim.

R2B_HEADER = "## Procurement List cross-reference (R2b)"

R2B_DISCOVERY_FRAMING = (
    "Discovery evidence only. This cross-reference is a cited fact-pair for "
    "analyst review -- not a route, a pursuit recommendation, or a resolved "
    "next action."
)

R2B_NON_CONVERTIBILITY = (
    "A Procurement List line at this location is NOT evidence that the pasted "
    "contract is competable, convertible to the Procurement List, or winnable. "
    "R2b concerns growing an EXISTING Procurement List line; adding new work to "
    "the Procurement List (R2a) is a separate suitability determination, "
    "submitted by the Central Nonprofit Agency, that is not assessed here."
)

R2B_WHOSE_LINE = (
    "The Procurement List export does not name which nonprofit agency performs "
    "a line. Confirm whether a line is YOURS (an R2b lead) or another agency's "
    "(landscape awareness only -- the Procurement List is not competed between "
    "agencies). Any 'Central Nonprofit Agency' shown is the NIB/SourceAmerica "
    "intermediary, not the performing agency."
)

R2B_NO_MATCH_ABSENCE = (
    "No Procurement List line parsed to this exact city/state in the uploaded "
    "workbook. This is NOT evidence the worksite is off the Procurement List: "
    "exact city/state matching does not see base- or installation-named "
    "worksites, adjacent metro-area cities, statewide or regional lines, or a "
    "stale or partial upload."
)

R2B_SAMPLE_SYNTHETIC = (
    "EXAMPLE DATA -- this cross-reference used the bundled SYNTHETIC sample "
    "workbook, not the official Procurement List. Findings are illustrative only."
)


# A workbook-supplied value (Service Type, CNA, location) and the uploaded
# filename are interpolated into Markdown that is rendered with st.markdown. HTML
# is already inert (unsafe_allow_html is never set on this path), but Markdown
# link/emphasis/code syntax is not -- an unescaped value could forge a clickable
# "source" link inside a packet whose whole value is provenance integrity. Escape
# the inline-Markdown metacharacters at this single render chokepoint. The set is
# deliberately narrow (no ``_ . -``) so ordinary filenames, dates, and ZIPs are
# left readable while links/code/emphasis/autolinks are neutralized.
_MD_ESCAPE = {ch: "\\" + ch for ch in "\\`*[]()<>"}


def _md(value: object) -> str:
    if value is None:
        return ""
    return "".join(_MD_ESCAPE.get(ch, ch) for ch in str(value))


def _provenance_line(result: PLMatchResult) -> str:
    source = _md(result.source_label) or "the uploaded workbook"
    when = _md(result.retrieved_at) or "an unattested date (no retrieval date provided)"
    return (
        f"As of {source}, retrieved {when}. The Procurement List is a "
        "point-in-time snapshot amendable by Federal Register add/delete "
        "notices; a stale upload can assert a removed line or miss a new one."
    )


def _mandatory_text(value: bool | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


def _location_text(match: PLServiceMatch) -> str:
    parts = [p for p in (match.parsed_city, match.parsed_state) if p]
    location = ", ".join(parts) if parts else (match.service_location or "unspecified")
    if match.parsed_zip:
        location = f"{location} {match.parsed_zip}"
    return location


def _match_detail_bullets(match: PLServiceMatch) -> list[str]:
    return [
        f"  - PL Service Location: {_md(_location_text(match))} (workbook row {match.source_row})",
        "  - Central Nonprofit Agency (NIB/SourceAmerica intermediary, NOT the "
        f"performing agency): {_md(match.cna) or 'not listed'}",
        "  - Mandatory for contracting activity: "
        f"{_mandatory_text(match.mandatory_for_contracting_activity)} "
        "(contracting-activity mandate context, not evidence the line is yours)",
    ]


def pl_service_match_lines(result: PLMatchResult) -> list[str]:
    """Render the R2b cross-reference as caveat-first Markdown lines (pure).

    Holds every honesty invariant on the render surface: no numeric rating of
    any kind (N1); the non-convertibility, whose-line, and staleness caveats
    always precede any fact-pair; a character-equal service type is labeled a
    string fact, not a same-service finding; and a no-match renders as
    evidence-absence, never a negative "not on the Procurement List" finding.
    """

    place = ", ".join(_md(part) for part in (result.city, result.state) if str(part).strip())
    lines: list[str] = [R2B_HEADER, ""]
    if result.synthetic_sample:
        lines += [f"> {R2B_SAMPLE_SYNTHETIC}", ""]
    lines += [
        f"- {R2B_DISCOVERY_FRAMING}",
        f"- {R2B_NON_CONVERTIBILITY}",
        f"- {R2B_WHOSE_LINE}",
        f"- {_provenance_line(result)}",
        "",
    ]
    if not result.has_any:
        lines += [f"- {R2B_NO_MATCH_ABSENCE}", ""]
        return lines
    if result.service_type_matches:
        query = result.queried_service_type
        lines += [f"### Character-equal service types at {place}", ""]
        for match in result.service_type_matches:
            lines.append(
                f'- Service Type "{_md(match.service_type)}" is character-equal to '
                f'your entered service type "{_md(query)}" -- a cited string fact, '
                "NOT a same-service or capability finding."
            )
            lines += _match_detail_bullets(match)
        lines.append("")
    if result.same_location_other:
        count = len(result.same_location_other)
        lines += [
            f"### Other Procurement List lines at {place} (different service type)",
            "",
            f"- {count} Procurement List line(s) parsed to this city/state with a "
            "different service type. Presence is not relevance and these are NOT "
            "matches:",
        ]
        for match in result.same_location_other:
            lines.append(
                f'  - Service Type "{_md(match.service_type) or "not listed"}" -- {_md(_location_text(match))}'
            )
        lines.append("")
    return lines


__all__ = [
    "PLMatchResult",
    "PLServiceMatch",
    "R2B_DISCOVERY_FRAMING",
    "R2B_HEADER",
    "R2B_NON_CONVERTIBILITY",
    "R2B_NO_MATCH_ABSENCE",
    "R2B_SAMPLE_SYNTHETIC",
    "R2B_WHOSE_LINE",
    "find_pl_service_matches",
    "normalize_service_type",
    "pl_service_match_lines",
]
