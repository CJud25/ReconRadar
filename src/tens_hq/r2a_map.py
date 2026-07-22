"""R2a determination-support map for the cited Opportunity Packet (roadmap
spine: ... -> R2b -> **R2a determination-support map**, the packet's final
section, ADR-022).

Given the packet's existing typed evidence -- an ACS geography context
record, an Incumbent & teaming leads assessment, a Capture Window band, and
a Staffing what-if result, all optional -- this module ROUTES each piece to
whichever of the four suitability criteria of 41 CFR 51-2.4(a) it speaks to,
and renders an honest "no packet evidence speaks to this criterion yet"
where nothing is attached. It computes NOTHING new: every evidence line
cites an ALREADY-rendered packet section by reference, never re-derives a
fact or a number.

**This is structural routing of citations, never an assessment (N1).** No
criterion carries a met/unmet marker, a score, a count, or a color. The map
presents evidence; the Commission determines suitability. Fair market price
is a separate determination and is out of scope. Allocation of a
Procurement List addition, once made, is CNA-discretionary; a case may
originate from either agency BD or the CNA -- neither is a promise of
outcome or timing (owner-attested, ADR-020).

**The two counsel-gated items (C3 and C4, named with their citations in
ADR-020 and the counsel packet) never appear anywhere in this module** --
not even in comments: a source-text sweep (tests/test_counsel_gate_sweep.py)
enforces that their vocabulary stays out of every packet module wholesale.
Neither is attested; this module must never harden either claim (ADR-020).

This module is pure (no Streamlit, no network, no case-store imports) and
takes only typed evidence objects the packet's OTHER sections already
computed -- it never re-imports the synthetic side or the case store
(AGENTS #1).
"""

from __future__ import annotations

from dataclasses import dataclass

from .capture_window import CaptureWindowBand, CaptureWindowState
from .connectors import GeographyRecord
from .incumbent_leads import IncumbentLeads
from .staffing_whatif import StaffingWhatIfResult, WhatIfState

# --- Local copies of standing constants (anti-circular-import convention) --
#
# r2a_map.py is imported BY opportunity_packet.py (to render this section),
# so it cannot import anything back FROM opportunity_packet -- the same
# established rule incumbent_leads.py / packet_export.py already follow for
# their local ``_md`` copies. The routing-rail requirement (audit MAJOR) is
# to REPRODUCE the geography disclaimer INLINE, not merely cite the section
# -- a local, verbatim copy satisfies both constraints at once. A test locks
# this string byte-identical to ``opportunity_packet.GEOGRAPHY_CONTEXT_
# DISCLAIMER`` so the two can never silently drift apart.

_GEOGRAPHY_CONTEXT_DISCLAIMER = (
    "Geographic context only -- a county-level ACS population statistic. "
    "This is NOT a candidate-supply, hiring-pool, capacity, eligibility, or "
    "partnership claim, and it is not evidence of available workers for this "
    "contract."
)

# Owner-attested capability list (ADR-020 SS2, verbatim). Renders ONLY inside
# the (a)(3) row -- no PSC<->capability mapping table exists or is implied
# anywhere in this module (that would be derived work, explicitly out of
# scope; see ADR-022).
_CAPABILITY_LIST = (
    "Administrative; Contact center & IT; Contract management; Electronics "
    "recycling; Food services; Fleet management; Healthcare & environmental; "
    "Laundry; Mail management; Records & document management; Secure "
    "document destruction; Retail services; Supply chain management & "
    "warehouse; Product packing; Total facility management; plus "
    "cybersecurity, software testing, information assurance, Section 508 "
    "assurance, data entry, document management, transcription, digital "
    "imaging, GPC program support, audit-readiness support, ready-to-close "
    "contract/grant file prep, pre-/post-award administrative services, "
    "switchboard, order processing, help desk."
)


@dataclass(frozen=True, slots=True)
class CriterionRow:
    """One (a)(N) row: its C1-confirmed one-line description plus the
    cited evidence that speaks to it (or the honest absence line)."""

    criterion: str
    description: str
    evidence_lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class R2aMap:
    """The full four-criteria evidence map plus its fixed epilogue's one
    conditional line (the Capture Window citation)."""

    rows: tuple[CriterionRow, ...]  # exactly (a)(1), (a)(2), (a)(3), (a)(4), in order
    capture_window_epilogue_line: str


R2A_NO_EVIDENCE_LINE = "No packet evidence speaks to this criterion yet."

_A1_DESCRIPTION = (
    "Employment potential of persons who are blind or have other severe "
    "disabilities."
)
_A2_DESCRIPTION = (
    "The NPA's qualifications to satisfactorily perform the work (the 75% "
    "ODLH capability question lives here)."
)
_A3_DESCRIPTION = "Capability to meet quality standards and delivery schedules."
_A4_DESCRIPTION = (
    "Impact on the current or most recently prior contractor for the "
    "requirement."
)


def _a1_evidence(geography: GeographyRecord | None) -> tuple[str, ...]:
    if geography is None:
        return (R2A_NO_EVIDENCE_LINE,)
    return (
        "Geography context (ACS) is attached — context only, "
        f"{_GEOGRAPHY_CONTEXT_DISCLAIMER} Employment-potential evidence "
        "beyond context is analyst work.",
    )


def _a2_evidence(staffing: StaffingWhatIfResult | None) -> tuple[str, ...]:
    if staffing is None:
        return (R2A_NO_EVIDENCE_LINE,)
    if staffing.state is not WhatIfState.COMPUTED:
        return (
            "A Staffing what-if entry was started but could not be computed "
            "(see the Staffing what-if section above for the reason); no "
            "usable ratio evidence is available for this criterion yet.",
        )
    return (
        "A Staffing what-if baseline/scenario is attached (see the "
        "Staffing what-if section above) — a labeled planning indicator "
        "toward NPA qualifications, never an official ODLH compliance "
        "determination.",
    )


def _a3_evidence() -> tuple[str, ...]:
    return (
        "General attested capability areas (owner-attested, ADR-020) — NOT "
        f"assessed against this contract's scope or PSC: {_CAPABILITY_LIST}",
    )


def _a4_evidence(incumbent_leads: IncumbentLeads | None) -> tuple[str, ...]:
    if incumbent_leads is None:
        return (R2A_NO_EVIDENCE_LINE,)
    return (
        "The Incumbent & teaming leads / PL-impact context section above "
        "carries the current recipient's competition posture and the "
        "PL-impact context sub-block (side-by-side cited facts, "
        "deliberately no computed share) — see that section for the cited "
        "evidence.",
    )


def _capture_window_epilogue_line(capture_window: CaptureWindowBand | None) -> str:
    if capture_window is not None and capture_window.state is CaptureWindowState.ESTIMATED:
        return (
            "PL-addition lead: an owner-attested 9–12 month band (ADR-020) "
            "is already reflected in the Capture Window section's R2a "
            "start-by band above."
        )
    return (
        "PL-addition lead: an owner-attested 9–12 month band (ADR-020); no "
        "live Capture Window band is available on this render to anchor it "
        "to."
    )


def derive_r2a_map(
    *,
    capture_window: CaptureWindowBand | None = None,
    incumbent_leads: IncumbentLeads | None = None,
    geography: GeographyRecord | None = None,
    staffing: StaffingWhatIfResult | None = None,
) -> R2aMap:
    """Route the packet's existing typed evidence onto the four criteria (pure).

    Every branch here decides ONLY whether an already-computed piece of
    evidence is attached; it never recomputes, re-derives, or re-verifies
    anything. See ADR-022 for why ``contract_facts`` and ``pl_matches`` are
    not separate parameters: whenever ``incumbent_leads`` is non-``None``
    the packet builder has already required live Contract Facts to compute
    it, so that signal is not independently needed here, and a Procurement
    List (R2b) cross-reference is opportunity-discovery evidence about this
    worksite, not suitability evidence for any of the four (a)(1)-(a)(4)
    criteria.
    """

    rows = (
        CriterionRow("(a)(1)", _A1_DESCRIPTION, _a1_evidence(geography)),
        CriterionRow("(a)(2)", _A2_DESCRIPTION, _a2_evidence(staffing)),
        CriterionRow("(a)(3)", _A3_DESCRIPTION, _a3_evidence()),
        CriterionRow("(a)(4)", _A4_DESCRIPTION, _a4_evidence(incumbent_leads)),
    )
    return R2aMap(
        rows=rows,
        capture_window_epilogue_line=_capture_window_epilogue_line(capture_window),
    )


# --- Rendering ---------------------------------------------------------------
#
# Caveat-first: the presents-not-determines framing always precedes the
# criteria, and the fixed epilogue's non-prediction facts always close the
# section, so no evidence line can be read in isolation as a verdict.

R2A_MAP_HEADER = (
    "## R2a determination-support map (evidence toward suitability, 41 CFR 51-2.4(a))"
)

R2A_PRESENTS_NOT_DETERMINES = (
    "This map ROUTES existing packet evidence to the four suitability "
    "criteria of 41 CFR 51-2.4(a); it does not assess, rate, or determine "
    "anything. No criterion below carries a met/unmet marker, a count, or "
    "a color — the Commission determines suitability, not this tool."
)

R2A_EPILOGUE_FMP = (
    "Fair market price (FMP) is a SEPARATE determination (41 U.S.C. 8503 / "
    "41 CFR 51-2.7), not one of the four criteria above."
)

R2A_EPILOGUE_PRESENTS_NOT_DETERMINES = (
    "The Commission determines suitability — this map presents evidence "
    "only."
)

R2A_EPILOGUE_ALLOCATION = (
    "Allocation of a Procurement List addition, once made, is at the CNA's "
    "discretion (owner-attested, ADR-020) — adding a requirement to the "
    "list does not itself promise allocation to any particular NPA."
)

R2A_EPILOGUE_ORIGINATION = (
    "A case may originate from either direction — agency BD or the CNA "
    "(owner-attested, ADR-020)."
)

# Deliberately an identification, not an instruction: "Next action: ..." on a
# packet holding little or no evidence would be the one line closest to a
# directive (adversarial-verify finding). Naming the coordination lane keeps
# the attested fact without telling the analyst to take a step.
R2A_EPILOGUE_NEXT_ACTION = (
    "The coordination lane for any R2a Procurement-List-addition case is "
    "SourceAmerica, the CNA (owner-attested, ADR-020). This map does not "
    "direct a pursuit."
)


def r2a_map_lines(r2a_map: R2aMap) -> list[str]:
    """Render the R2a determination-support map as caveat-first Markdown lines (pure)."""

    lines: list[str] = [
        R2A_MAP_HEADER,
        "",
        f"- {R2A_PRESENTS_NOT_DETERMINES}",
        "",
    ]
    for row in r2a_map.rows:
        lines.append(f"### {row.criterion} {row.description}")
        lines.append("")
        lines.extend(f"- {evidence_line}" for evidence_line in row.evidence_lines)
        lines.append("")
    lines.extend(
        [
            f"- {R2A_EPILOGUE_FMP}",
            f"- {R2A_EPILOGUE_PRESENTS_NOT_DETERMINES}",
            f"- {R2A_EPILOGUE_ALLOCATION}",
            f"- {R2A_EPILOGUE_ORIGINATION}",
            f"- {R2A_EPILOGUE_NEXT_ACTION}",
            f"- {r2a_map.capture_window_epilogue_line}",
            "",
        ]
    )
    return lines


__all__ = [
    "R2A_EPILOGUE_ALLOCATION",
    "R2A_EPILOGUE_FMP",
    "R2A_EPILOGUE_NEXT_ACTION",
    "R2A_EPILOGUE_ORIGINATION",
    "R2A_EPILOGUE_PRESENTS_NOT_DETERMINES",
    "R2A_MAP_HEADER",
    "R2A_NO_EVIDENCE_LINE",
    "R2A_PRESENTS_NOT_DETERMINES",
    "CriterionRow",
    "R2aMap",
    "derive_r2a_map",
    "r2a_map_lines",
]
