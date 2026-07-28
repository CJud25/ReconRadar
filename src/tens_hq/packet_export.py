"""Packet-export assembler for the cited Opportunity Packet (A7).

The Opportunity Packet tab today downloads the raw on-screen Markdown body
with a fixed filename. The house's real cited-export discipline lives in
``bd_page._render_assessment``'s export block: an as-of stamp, non-claim
disclaimers, and a ``## Source manifest`` table with pipe-escaped cells. This
module brings that same discipline to the packet download by composing THREE
pieces around the packet's own body, unmodified:

* a small header (as-of, the packet identifiers, the standing framing and
  attestation disclaimers) that precedes the body,
* a ``## Section ledger`` -- all eleven packet sections (originally seven;
  extended by ADR-019 with the A2 Radar-handoff Origin row, by ADR-021 with
  the A6 Staffing what-if row, by ADR-022 with the R2a determination-support
  map row, and by ADR-023 with the A4 Procurement List activity (Federal
  Register) row), always in packet order, each marked
  included/not-included with an honest, structural basis (never derived by
  string-searching the rendered body), and
* a ``## Source manifest`` -- one row per ATTACHED source (live pull or
  analyst upload/attestation), with its reference, retrieval time, assurance
  (``API_RETRIEVED`` vs ``USER_ATTESTED``), and notes,

and a sanitized, deterministic filename derived from the PIID and an injected
``as_of``.

This module composes; it does not analyze. No new fact is computed here and
no fact already in the body is restated with different wording -- the ledger
and manifest describe SECTIONS and SOURCES, never findings (N1/N2). "Not
included" is always an evidence-absence reason ("no live contract-facts pull
attached"), never a negative claim about the contract or the world.

This module is pure (no Streamlit, no network, no case-store imports) and
deterministic: ``as_of`` is always caller-supplied; nothing here calls
``datetime.now()``. It has its own LOCAL Markdown-escape copy -- mirrors
``incumbent_leads.py`` / ``pl_match.py`` exactly -- and does NOT import ``_md``
from :mod:`tens_hq.opportunity_packet` (an unrelated, established
anti-circular-import convention this module simply follows; only
``PACKET_FRAMING`` is imported from there). See ADR-018.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from .connectors import ContractFactsRecord, GeographyRecord, PLNoticesResult, SubawardsResult
from .opportunity_packet import PACKET_FRAMING
from .pl_activity import PL_ACTIVITY_NO_PULL, PL_ACTIVITY_SECTION_NAME
from .pl_match import PLMatchResult
from .radar_handoff import RadarHandoff
from .staffing_whatif import StaffingWhatIfResult

_ASSURANCE_API_RETRIEVED = "API_RETRIEVED"
_ASSURANCE_USER_ATTESTED = "USER_ATTESTED"
_ASSURANCE_SYNTHETIC_EXAMPLE = "SYNTHETIC_EXAMPLE"

# Used for both a missing retrieval timestamp and a missing reference -- the
# exact wording the SourceEntry.retrieved_at field promises (see the
# dataclass docstring below); reused for "no value at all" cells so the
# manifest never fabricates a stand-in.
_NOT_SUPPLIED = "Not supplied (analyst attestation absent)"

_SYNTHETIC_SAMPLE_NOTE = "SYNTHETIC example workbook — not real Procurement List data"


@dataclass(frozen=True, slots=True)
class SectionEntry:
    """One fixed Section-ledger row (D3): whether it is included, and why."""

    name: str
    included: bool
    basis: str  # why included / the honest evidence-absence reason


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """One Source-manifest row: an ATTACHED source with full provenance.

    ``retrieved_at`` is either the source's own retrieval timestamp or the
    literal ``"Not supplied (analyst attestation absent)"`` when no
    attestation time is available (e.g. an uploaded directory workbook, which
    carries no retrieval timestamp at all). ``assurance`` is always one of
    ``API_RETRIEVED``, ``USER_ATTESTED``, or ``SYNTHETIC_EXAMPLE`` (ADR-025:
    the bundled offline synthetic-example contract-facts row only -- never a
    real record, never claimed as a live retrieval).
    """

    source: str  # e.g. "Contract Facts (live, USAspending award detail)"
    reference: str  # URL, or a workbook/file label, or the raw attested value
    retrieved_at: str
    assurance: str
    notes: str  # truncation / synthetic / vintage / "" (never a claim)


# --- Section ledger (D3: eleven fixed rows, always in packet order; ---------
# originally seven, extended by ADR-019 with the Origin row, by ADR-021 with
# the Staffing what-if row, by ADR-022 with the R2a determination-support
# map row, and by ADR-023 with the A4 PL activity (Federal Register) row.)


def _handoff_row(handoff_attached: bool, handoff_piid_matched: bool) -> SectionEntry:
    """The Origin row (D7): the three honest bases a handoff render can be in.

    Pinned by the audit finding that the LEDGER cannot tell "no handoff" and
    "a handoff whose PIID no longer matches" apart from a single gated value
    alone -- so this row takes the two booleans directly, distinctly, rather
    than accepting the already-gated ``RadarHandoff | None`` the builder
    receives. A stale-PIID handoff drops out for the same reason every other
    reuse-guard on this page drops a stale result (bd_page.py:580-586,
    659-666, 743-750, 840-850): it no longer describes this render.
    """

    if not handoff_attached:
        return SectionEntry(
            "Origin (Radar handoff)",
            False,
            "No handoff attached to this render.",
        )
    if not handoff_piid_matched:
        return SectionEntry(
            "Origin (Radar handoff)",
            False,
            "A handoff is attached but its PIID no longer matches this "
            "packet's current PIID, so it no longer describes this render.",
        )
    return SectionEntry(
        "Origin (Radar handoff)",
        True,
        "A Radar handoff snapshot is attached and its PIID matches this "
        "packet's current PIID.",
    )


def _gate_row(eligibility: object | None, contract_facts: ContractFactsRecord | None) -> SectionEntry:
    """The gate basis distinguishes analyst-entered, synthetic, and live feeding.

    Pinned predicate (audit finding): ``included`` is
    ``eligibility is not None OR contract_facts is not None``. The packet
    builder (``opportunity_packet.py:256-279``) recomputes the gate from
    ``contract_facts.set_aside_code`` and IGNORES a ``None`` eligibility once
    facts are attached, so an attached-facts render must read included with a
    source-specific basis even when no ``eligibility`` object was supplied.
    """

    if contract_facts is not None and contract_facts.synthetic_example:
        return SectionEntry(
            "Eligibility gate",
            True,
            "Gate fed by the attached SYNTHETIC example set-aside value "
            "(USAspending FPDS type_set_aside), which supersedes any "
            "analyst-typed value once the example Contract Facts are attached.",
        )
    if contract_facts is not None:
        return SectionEntry(
            "Eligibility gate",
            True,
            "Gate fed by the LIVE retrieved set-aside value (USAspending FPDS "
            "type_set_aside), which supersedes any analyst-typed value once "
            "live Contract Facts are attached.",
        )
    if eligibility is not None:
        return SectionEntry(
            "Eligibility gate",
            True,
            "Gate fed by the analyst-entered set-aside value (no live "
            "Contract Facts attached to this render).",
        )
    return SectionEntry(
        "Eligibility gate",
        False,
        "No set-aside value entered and no live contract-facts pull attached.",
    )


def _contract_facts_live_row(contract_facts: ContractFactsRecord | None) -> SectionEntry:
    if contract_facts is not None and contract_facts.synthetic_example:
        # ADR-025: the bundled offline SYNTHETIC-example record must not claim
        # a live pull in the ledger either -- worded with no "live" token so
        # the honesty test can be a clean substring ban.
        return SectionEntry(
            "Contract Facts (SYNTHETIC example)",
            True,
            "Bundled SYNTHETIC example facts attached — offline, not a real "
            "USAspending API retrieval.",
        )
    if contract_facts is not None:
        return SectionEntry(
            "Contract Facts (live)",
            True,
            "Live USAspending contract-facts pull attached to this render.",
        )
    return SectionEntry("Contract Facts (live)", False, "No live contract-facts pull attached.")


def _contract_facts_analyst_row() -> SectionEntry:
    # This block renders unconditionally in build_opportunity_packet_markdown
    # (it needs no evidence beyond the analyst-pasted piid/county/state), so
    # it is the one ledger row with no absent state to describe.
    return SectionEntry(
        "Contract Facts (analyst-entered)",
        True,
        "Always rendered from the analyst-pasted PIID and place of "
        "performance, independent of any other evidence attached.",
    )


def _capture_window_row(contract_facts: ContractFactsRecord | None) -> SectionEntry:
    if contract_facts is not None and contract_facts.synthetic_example:
        return SectionEntry(
            "Capture window",
            True,
            "Computed from the attached SYNTHETIC example Contract Facts' "
            "potential period end date.",
        )
    if contract_facts is not None:
        return SectionEntry(
            "Capture window",
            True,
            "Computed from the attached live Contract Facts pull's "
            "potential period end date.",
        )
    return SectionEntry(
        "Capture window",
        False,
        "No live contract-facts pull attached (capture window needs a "
        "potential period end date).",
    )


def _leads_row(
    contract_facts: ContractFactsRecord | None,
    subawards: SubawardsResult | None,
    directory_agency_names: Sequence[str] | None,
) -> SectionEntry:
    if contract_facts is None:
        return SectionEntry(
            "Incumbent & teaming leads / PL-impact",
            False,
            "No live contract-facts pull attached (this section needs at "
            "least a live award to reason from).",
        )
    parts = ["facts"]
    if subawards is not None:
        parts.append("subawards")
    if directory_agency_names is not None:
        parts.append("directory")
    evidence_text = "facts only" if parts == ["facts"] else " + ".join(parts)
    return SectionEntry(
        "Incumbent & teaming leads / PL-impact",
        True,
        f"Evidence attached: {evidence_text}.",
    )


def _staffing_row(staffing: StaffingWhatIfResult | None) -> SectionEntry:
    """The Staffing what-if row (ADR-021): included tracks "was a baseline
    entered," never "did it validate." A ``CANNOT_COMPUTE`` result (a
    partial baseline) is still an entered baseline, so it is still included
    -- the render itself carries the honest partial-entry message. Only a
    completely blank baseline (``staffing is None``, the builder never even
    computed one) is "not included."
    """

    if staffing is not None:
        return SectionEntry(
            "Staffing what-if",
            True,
            "An analyst-entered staffing baseline was attached to this render.",
        )
    return SectionEntry(
        "Staffing what-if",
        False,
        "No baseline entered.",
    )


def _geography_row(geography: GeographyRecord | None) -> SectionEntry:
    # The builder renders the Geography section UNCONDITIONALLY (an honest
    # placeholder when nothing was retrieved), so this row is always included
    # -- "Not included" would misdescribe the document itself. The basis
    # distinguishes retrieved context from the placeholder.
    if geography is not None:
        return SectionEntry(
            "Geography (ACS)",
            True,
            "Live ACS geography context attached to this render.",
        )
    return SectionEntry(
        "Geography (ACS)",
        True,
        "Section rendered as a placeholder -- no ACS context retrieved (not yet pulled).",
    )


def _pl_row(pl_matches: PLMatchResult | None) -> SectionEntry:
    if pl_matches is not None:
        return SectionEntry(
            "PL cross-reference (R2b)",
            True,
            "A PL workbook was cross-referenced against this render's worksite.",
        )
    return SectionEntry(
        "PL cross-reference (R2b)",
        False,
        "No PL workbook cross-referenced this render.",
    )


def _pl_notices_row(pl_notices: PLNoticesResult | None) -> SectionEntry:
    """The A4 PL activity (Federal Register) row (D4).

    Included tracks "was a live Federal Register pull attached to this
    render" -- the same "pull != None" presence-gating discipline the R2b
    row above already holds for its own optional workbook cross-reference. A
    real, empty pull (0 notices matched) is still an attached pull, so it is
    still included -- the section itself renders the honest zero-count line.
    """

    if pl_notices is not None:
        return SectionEntry(
            PL_ACTIVITY_SECTION_NAME,
            True,
            "A live Federal Register pull was attached to this render.",
        )
    return SectionEntry(PL_ACTIVITY_SECTION_NAME, False, PL_ACTIVITY_NO_PULL)


def _r2a_map_row() -> SectionEntry:
    # ALWAYS included, unconditionally, needing no evidence-presence check
    # (ADR-022): the R2a determination-support map renders on every packet,
    # routing whatever evidence is currently attached elsewhere onto the
    # four suitability criteria -- an honest "no packet evidence speaks to
    # this criterion yet" line is itself part of a valid render, exactly
    # like the Geography placeholder row above.
    return SectionEntry(
        "R2a determination-support map",
        True,
        "Always rendered -- routes whatever evidence is currently attached "
        "above onto the four suitability criteria of 41 CFR 51-2.4(a).",
    )


def derive_section_ledger(
    *,
    eligibility: object | None,
    contract_facts: ContractFactsRecord | None,
    geography: GeographyRecord | None,
    pl_matches: PLMatchResult | None,
    subawards: SubawardsResult | None,
    directory_agency_names: Sequence[str] | None,
    handoff_attached: bool = False,
    handoff_piid_matched: bool = False,
    staffing: StaffingWhatIfResult | None = None,
    pl_notices: PLNoticesResult | None = None,
) -> tuple[SectionEntry, ...]:
    """The eleven fixed Section-ledger rows (D3), always in packet order.

    Originally seven; ADR-019 adds the Origin (Radar handoff) row as row 1,
    since D3 places that section first in the packet; ADR-021 adds the
    Staffing what-if row between Incumbent leads and Geography, mirroring
    that section's own packet placement; ADR-022 adds the R2a
    determination-support map row LAST, since that section renders last and
    unconditionally; ADR-023 adds the A4 PL activity (Federal Register) row
    between R2b and the R2a map, mirroring that section's own packet
    placement. Included-state is derived STRUCTURALLY from the same inputs
    the packet builder receives -- never by string-searching the rendered
    body markdown.
    """

    return (
        _handoff_row(handoff_attached, handoff_piid_matched),
        _gate_row(eligibility, contract_facts),
        _contract_facts_live_row(contract_facts),
        _contract_facts_analyst_row(),
        _capture_window_row(contract_facts),
        _leads_row(contract_facts, subawards, directory_agency_names),
        _staffing_row(staffing),
        _geography_row(geography),
        _pl_row(pl_matches),
        _pl_notices_row(pl_notices),
        _r2a_map_row(),
    )


# --- Source manifest (one row per ATTACHED source, fixed order) --------------


_HANDOFF_SNAPSHOT_NOTE = (
    "The handoff's claimed snapshot retrieval time; not independently "
    "verified. Contract Facts, where attached, supersede this claim."
)


def derive_source_manifest(
    *,
    contract_facts: ContractFactsRecord | None,
    subawards: SubawardsResult | None,
    geography: GeographyRecord | None,
    pl_matches: PLMatchResult | None,
    directory_source_label: str | None,
    set_aside_analyst_value: str | None,
    handoff: RadarHandoff | None = None,
    handoff_source_label: str | None = None,
    handoff_piid_matched: bool = False,
    staffing: StaffingWhatIfResult | None = None,
    pl_notices: PLNoticesResult | None = None,
) -> tuple[SourceEntry, ...]:
    """One row per ATTACHED source, in a fixed order.

    The analyst-typed set-aside gets a ``USER_ATTESTED`` row ONLY when the
    gate actually ran off it AND a non-blank value was typed -- pinned
    predicate (audit finding + PM decision): ``contract_facts is None AND
    set_aside_analyst_value.strip()``. A blank typed field is not an attached
    source (the gate's UNKNOWN state from a blank is section behavior, not a
    source), so it never earns a manifest row.

    The Radar-handoff row (ADR-019, D7) emits ONLY when ``handoff`` is
    supplied AND ``handoff_piid_matched`` is true -- a handoff attached but
    no longer PIID-matched influenced nothing in this render, the same
    phantom-source rule the directory row already follows below.

    The Staffing what-if row (ADR-021) emits whenever ``staffing is not
    None`` -- the same "was a baseline entered" predicate the Section-ledger
    row uses, with NO live-supersession branch (unlike the set-aside row):
    the staffing inputs are never superseded by anything else in the packet.

    The A4 PL activity (Federal Register) row (ADR-023) emits whenever
    ``pl_notices is not None`` -- the same "was it pulled" predicate as the
    R2b row below, no live-supersession branch. Its ``notes`` carry BOTH the
    truncation disclosure ("newest 20 of N") when truncated AND the search
    term when one was used (D4) -- not either/or, since both can be true of
    the same pull.
    """

    entries: list[SourceEntry] = []

    if handoff is not None and handoff_piid_matched:
        notes = _HANDOFF_SNAPSHOT_NOTE
        if handoff.synthetic_sample:
            notes = f"{notes} SYNTHETIC example handoff — not real Radar output."
        entries.append(
            SourceEntry(
                source="Radar handoff (analyst upload)",
                reference=handoff_source_label or _NOT_SUPPLIED,
                retrieved_at=handoff.snapshot_date,
                assurance=_ASSURANCE_USER_ATTESTED,
                notes=notes,
            )
        )

    if contract_facts is not None and contract_facts.synthetic_example:
        # ADR-025: never API_RETRIEVED, never a live award URL -- reference is
        # the same honest, non-URL provenance marker the packet body cites.
        entries.append(
            SourceEntry(
                source="Contract Facts (SYNTHETIC example, offline)",
                reference=contract_facts.source_url,
                retrieved_at=contract_facts.retrieved_at,
                assurance=_ASSURANCE_SYNTHETIC_EXAMPLE,
                notes="SYNTHETIC example — not real USAspending data.",
            )
        )
    elif contract_facts is not None:
        entries.append(
            SourceEntry(
                source="Contract Facts (live, USAspending award detail)",
                reference=contract_facts.source_url,
                retrieved_at=contract_facts.retrieved_at,
                assurance=_ASSURANCE_API_RETRIEVED,
                notes="",
            )
        )

    if subawards is not None:
        notes = (
            "More subaward records exist than were retrieved (first 100 shown)."
            if subawards.truncated
            else ""
        )
        source = "Subaward records (live, USAspending FSRS/FFATA)"
        assurance = _ASSURANCE_API_RETRIEVED
        if contract_facts is not None and contract_facts.synthetic_example:
            # ADR-025: the offline fixture's subaward provenance follows the
            # synthetic award chain even when its source fields differ.
            source = "Subaward records (SYNTHETIC example, offline)"
            assurance = _ASSURANCE_SYNTHETIC_EXAMPLE
            notes = "SYNTHETIC example — not real USAspending data. " + notes
        entries.append(
            SourceEntry(
                source=source,
                reference=subawards.source_url,
                retrieved_at=subawards.retrieved_at,
                assurance=assurance,
                notes=notes.strip(),
            )
        )

    # The directory can only influence the packet when the leads section
    # renders (contract facts attached); without them the upload contributed
    # nothing to this document, and listing it would cite a phantom source.
    if (
        contract_facts is not None
        and directory_source_label is not None
        and directory_source_label.strip()
    ):
        entries.append(
            SourceEntry(
                source="AbilityOne NPA directory (analyst upload)",
                reference=directory_source_label,
                retrieved_at=_NOT_SUPPLIED,
                assurance=_ASSURANCE_USER_ATTESTED,
                notes="",
            )
        )

    if staffing is not None:
        entries.append(
            SourceEntry(
                source="Staffing what-if inputs (analyst-entered)",
                reference=f"{staffing.mode.value} mode entry",
                retrieved_at=_NOT_SUPPLIED,
                assurance=_ASSURANCE_USER_ATTESTED,
                notes="",
            )
        )

    if geography is not None:
        entries.append(
            SourceEntry(
                source="ACS geography context (Census, live)",
                reference=geography.source_url,
                retrieved_at=geography.retrieved_at,
                assurance=_ASSURANCE_API_RETRIEVED,
                notes=f"Survey: {geography.acs_survey}; vintage {geography.acs_vintage_year}.",
            )
        )

    if pl_matches is not None:
        notes = _SYNTHETIC_SAMPLE_NOTE if pl_matches.synthetic_sample else ""
        entries.append(
            SourceEntry(
                source="Procurement List cross-reference workbook (R2b)",
                reference=pl_matches.source_label or _NOT_SUPPLIED,
                retrieved_at=pl_matches.retrieved_at or _NOT_SUPPLIED,
                assurance=_ASSURANCE_USER_ATTESTED,
                notes=notes,
            )
        )

    if pl_notices is not None:
        note_parts: list[str] = []
        if pl_notices.truncated:
            note_parts.append(
                f"Showing the newest {len(pl_notices.records)} of "
                f"{pl_notices.count_total} total notices."
            )
        if pl_notices.search_term:
            note_parts.append(f'Search term: "{pl_notices.search_term}".')
        entries.append(
            SourceEntry(
                source="Procurement List activity (live, Federal Register)",
                reference=pl_notices.source_url,
                retrieved_at=pl_notices.retrieved_at,
                assurance=_ASSURANCE_API_RETRIEVED,
                notes=" ".join(note_parts),
            )
        )

    if (
        contract_facts is None
        and set_aside_analyst_value is not None
        and set_aside_analyst_value.strip()
    ):
        entries.append(
            SourceEntry(
                source="Set-aside status (analyst-entered)",
                reference=set_aside_analyst_value,
                retrieved_at=_NOT_SUPPLIED,
                assurance=_ASSURANCE_USER_ATTESTED,
                notes="",
            )
        )

    return tuple(entries)


# --- Filename ------------------------------------------------------------

_FILENAME_DISALLOWED = re.compile(r"[^A-Za-z0-9._-]")
_FILENAME_RUN = re.compile(r"[-]{2,}")
_FILENAME_MAX_PIID_CHARS = 40


def _sanitize_piid_for_filename(piid: str | None) -> str:
    """PIID filtered to ``[A-Za-z0-9._-]``, per §3, or ``no-piid`` when empty.

    Every other character becomes ``-``, runs of ``-`` collapse to one, the
    result is trimmed of leading/trailing ``-``/``.``, and it is capped at 40
    characters. The cap is re-trimmed of a trailing ``-``/``.`` too -- the
    brief's stated order (filter, collapse, trim, cap) does not itself
    guarantee the cut lands clean, and a filename should never end on a bare
    separator.
    """

    raw = piid or ""
    filtered = _FILENAME_DISALLOWED.sub("-", raw)
    collapsed = _FILENAME_RUN.sub("-", filtered)
    trimmed = collapsed.strip("-.")
    capped = trimmed[:_FILENAME_MAX_PIID_CHARS].strip("-.")
    return capped or "no-piid"


def packet_export_filename(piid: str, as_of: datetime) -> str:
    """``opportunity-packet-{sanitized-piid}-{YYYYMMDD}.md`` (§3).

    ``as_of`` is REQUIRED and drives the date stamp -- this function never
    calls ``date.today()`` / ``datetime.now()``.
    """

    sanitized = _sanitize_piid_for_filename(piid)
    stamp = as_of.strftime("%Y%m%d")
    return f"opportunity-packet-{sanitized}-{stamp}.md"


# --- Markdown escape chokepoint -------------------------------------------
#
# A LOCAL copy, exactly like incumbent_leads.py / pl_match.py. This module
# cannot import ``_md`` from opportunity_packet (the established anti-
# circular-import rule; see pl_match.py:221-227) -- it imports only the
# unrelated ``PACKET_FRAMING`` constant from there.

_MD_ESCAPE = {ch: "\\" + ch for ch in "\\`*[]()<>"}


def _md(value: object) -> str:
    if value is None:
        return ""
    # This module's _md feeds single-line contexts only (header bullets and
    # table cells), where a line break is itself structural injection: an
    # uploaded filename may legally contain one and would split a manifest
    # table row. Flatten every line boundary to a space before escaping.
    flat = " ".join(str(value).splitlines())
    return "".join(_MD_ESCAPE.get(ch, ch) for ch in flat)


def _reported(value: object) -> str:
    if value is None or not str(value).strip():
        return "Not supplied"
    return _md(value)


def _cell(value: object) -> str:
    """Two-layer table-cell escaping (§3): the local ``_md`` copy, THEN ``|`` -> ``/``."""

    return _md(value).replace("|", "/")


# A URL-safe sibling of ``_md``/``_cell`` (§5.8 fix): cited source URLs (FR,
# USAspending, ACS, subawards) legitimately contain "[]" in query params
# (e.g. FR's conditions[type][]=NOTICE), so the blanket escape above renders
# visible "\[" / "\]" that corrupt paste-and-resolve in the downloadable
# export. A clean absolute http(s) value with no whitespace/angle-brackets/
# pipe renders as a CommonMark autolink (``<https://...>``), which preserves
# "[]()" literally and cannot itself carry a table- or markdown-injection
# (autolinks cannot contain whitespace, angle brackets, or "|"). Anything
# else -- a hostile or non-URL reference such as an uploaded filename or
# "HOURS mode entry" -- still falls back to the same two-layer ``_cell``
# escaping as before.
def _md_url(value: object) -> str:
    if value is None:
        return ""
    flat = " ".join(str(value).splitlines())
    if flat.startswith(("http://", "https://")) and not any(
        ch in flat for ch in (" ", "\t", "<", ">", "|")
    ):
        return f"<{flat}>"
    return "".join(_MD_ESCAPE.get(ch, ch) for ch in flat)


def _cell_url(value: object) -> str:
    return _md_url(value).replace("|", "/")


# --- Rendering ---------------------------------------------------------------

PACKET_EXPORT_TITLE = "# Opportunity Packet — cited export"

EXPORT_ATTESTATION_DISCLAIMER = (
    "Analyst-typed and analyst-uploaded evidence in this export (a typed "
    "set-aside value, an uploaded NPA directory, or the selected Procurement "
    "List workbook and its retrieval date) is an analyst attestation and has "
    "not been independently verified."
)

EXPORT_WORKBOOK_NOT_RETAINED = (
    "Workbook bytes are not retained by this export. Retrieval and upload "
    "times are analyst-supplied and may be unknown."
)

SECTION_LEDGER_HEADER = "## Section ledger"

SOURCE_MANIFEST_HEADER = "## Source manifest"

MANIFEST_EMPTY_NOTE = "No live or uploaded sources attached to this render."


def _section_ledger_lines(ledger: Sequence[SectionEntry]) -> list[str]:
    lines = [
        SECTION_LEDGER_HEADER,
        "",
        "| Section | Included | Basis |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| {_cell(entry.name)} | {'Yes' if entry.included else 'Not included'} | {_cell(entry.basis)} |"
        for entry in ledger
    )
    lines.append("")
    return lines


def _source_manifest_lines(manifest: Sequence[SourceEntry]) -> list[str]:
    lines = [SOURCE_MANIFEST_HEADER, ""]
    if not manifest:
        lines.append(f"- {MANIFEST_EMPTY_NOTE}")
        lines.append("")
        return lines
    lines.extend(
        [
            "| Source | Reference | Retrieved at | Assurance | Notes |",
            "|---|---|---|---|---|",
        ]
    )
    lines.extend(
        f"| {_cell(entry.source)} | {_cell_url(entry.reference)} | {_cell(entry.retrieved_at)} | "
        f"{_cell(entry.assurance)} | {_cell(entry.notes)} |"
        for entry in manifest
    )
    lines.append("")
    return lines


def assemble_packet_export(
    *,
    body_markdown: str,
    piid: str,
    county: str,
    state: str,
    ledger: Sequence[SectionEntry],
    manifest: Sequence[SourceEntry],
    as_of: datetime,
) -> str:
    """Render the full cited export: header + body VERBATIM + ledger + manifest.

    The assembler is deliberately dumb: it renders exactly what the
    ``derive_*`` functions produced, plus the packet body byte-for-byte
    unmodified. All judgment lives in the derive functions, where it is
    unit-testable in isolation.
    """

    state_text = _reported(state.strip().upper()) if state and state.strip() else "Not supplied"
    header_lines = [
        PACKET_EXPORT_TITLE,
        "",
        f"- As of: {as_of.isoformat()}",
        f"- PIID: {_reported(piid)}",
        f"- Place of performance: {_reported(county)}, {state_text}",
        f"- {PACKET_FRAMING}",
        f"- {EXPORT_ATTESTATION_DISCLAIMER}",
        f"- {EXPORT_WORKBOOK_NOT_RETAINED}",
        "",
    ]
    appendix_lines = _section_ledger_lines(ledger) + _source_manifest_lines(manifest)
    header_text = "\n".join(header_lines) + "\n"
    appendix_text = "\n".join(appendix_lines)
    return header_text + body_markdown + "\n---\n\n" + appendix_text


__all__ = [
    "EXPORT_ATTESTATION_DISCLAIMER",
    "EXPORT_WORKBOOK_NOT_RETAINED",
    "MANIFEST_EMPTY_NOTE",
    "PACKET_EXPORT_TITLE",
    "SECTION_LEDGER_HEADER",
    "SOURCE_MANIFEST_HEADER",
    "SectionEntry",
    "SourceEntry",
    "assemble_packet_export",
    "derive_section_ledger",
    "derive_source_manifest",
    "packet_export_filename",
]
