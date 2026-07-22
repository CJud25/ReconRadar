"""Immutable content model for ReconRadar's seven-beat guided demonstration.

The tour walks the packet spine of ``docs/DEMO_SCRIPT.md``. It navigates
PAGES; it cannot open a Streamlit tab, so beats that live on the Opportunity
Packet tab tell the operator to open it. The governance close covers the
synthetic-data validation and public-evidence boundary. Every quoted widget
label is verbatim from ``bd_page.py`` (locked by a test), and every sentence
keeps the packet's own honesty rules: prefills are never verified evidence,
leads are never verdicts, indicators are never determinations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class DemoBeat:
    """One guided-demo stop and the on-screen value the operator points at."""

    title: str
    target_page: str
    highlight: str
    sentence: str


DEMO_TOUR: Final[tuple[DemoBeat, ...]] = (
    DemoBeat(
        title="The packet thesis",
        target_page="BD Feasibility",
        highlight="the no-score framing caption",
        sentence=(
            "Open the Opportunity Packet tab (rightmost) and read the framing "
            "caption aloud: the packet never renders a score, ranking, or "
            "bid/no-bid recommendation. The rest of the tour is that "
            "sentence's proof."
        ),
    ),
    DemoBeat(
        title="Origin and live contract facts",
        target_page="BD Feasibility",
        highlight="obligated dollars, distinct from the ceiling",
        sentence=(
            "Tick 'Use the bundled SYNTHETIC example instead of an upload' and "
            "click 'Use handoff' — the handoff prefills retrieval inputs only "
            "and is never treated as verified. Then 'Pull contract facts "
            "(live)': one analyst-initiated, cited USAspending pull; a missing "
            'amount reads "Not reported," never $0.00.'
        ),
    ),
    DemoBeat(
        title="Eligibility gate and capture window",
        target_page="BD Feasibility",
        highlight="the gate state and the capture-window band",
        sentence=(
            "The gate sits above all other evidence and reads the live "
            "set-aside — blank means Unknown, never unrestricted; it fails "
            "closed. The capture window is an honest band from the potential "
            "end date and owner-attested lead times: an estimate labeled as "
            "one."
        ),
    ),
    DemoBeat(
        title="Incumbent leads and staffing what-if",
        target_page="BD Feasibility",
        highlight="the direct-labor ratio planning indicator",
        sentence=(
            "'Pull subaward records (live)' and the directory workbook yield "
            "leads, never verdicts — a subaward is teaming-posture evidence, "
            "not proof of a relationship. The staffing scenario is a labeled "
            "planning indicator, never an official ODLH compliance "
            "determination."
        ),
    ),
    DemoBeat(
        title="Geography, Procurement List, notices",
        target_page="BD Feasibility",
        highlight="the cited ACS county figure",
        sentence=(
            "'Pull ACS geography context (live)' cites one Census figure as "
            "context, not candidate supply. 'Cross-reference the Procurement "
            "List' is an exact city/state match — a no-match is evidence "
            "absence. 'Pull Procurement List activity (live)' lists the "
            "Commission's notices, cited and never interpreted."
        ),
    ),
    DemoBeat(
        title="R2a map and the cited export",
        target_page="BD Feasibility",
        highlight="the Section ledger and Source manifest in the download",
        sentence=(
            "The always-last map routes the attached evidence onto the four "
            "suitability criteria of 41 CFR 51-2.4(a) — the Commission "
            "determines suitability. 'Export Opportunity Packet (Markdown)' "
            "wraps the body verbatim in a stamped header, the Section ledger, "
            "and the Source manifest."
        ),
    ),
    DemoBeat(
        title="Governance close",
        target_page="Privacy & Governance",
        highlight="the passed synthetic-data validation",
        sentence=(
            "End on the synthetic-data validation and the public-evidence "
            "boundary: ReconRadar keeps cited organizational and contract-"
            "directory evidence separate from its clearly labeled synthetic "
            "demonstration data."
        ),
    ),
)
