"""N6 set-aside eligibility gate for the cited Opportunity Packet.

The gate classifies one analyst-entered FPDS-style set-aside value.  It does
not determine eligibility or recommend a pursuit: it presents the entered fact
and the structural rule for a human decision.  Blank values fail closed as
``UNKNOWN``; only an affirmative ``NONE`` enters the internal
``UNRESTRICTED`` state, meaning no set-aside was reported; every other
non-empty value is treated as a set-aside, including unrecognized codes.

This module is pure (no Streamlit, network, or case-store imports).  Its
renderer is caveat-first and escapes the raw analyst input before interpolating
it into Markdown. Barred renders name the unassessed FAR 8.7 mandatory-source
lane.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ._markdown import _md


class EligibilityState(str, Enum):
    """Three-state interpretation of an analyst-entered set-aside value."""

    UNKNOWN = "UNKNOWN"
    UNRESTRICTED = "UNRESTRICTED"
    SET_ASIDE_BARRED = "SET_ASIDE_BARRED"


@dataclass(frozen=True)
class EligibilityGate:
    """One set-aside gate assessment with the raw input preserved verbatim."""

    raw_set_aside: str | None
    state: EligibilityState
    set_aside_label: str | None
    recognized: bool
    set_aside_family: str | None = None


ELIGIBILITY_GATE_HEADER = "## Eligibility gate (can the NPA prime?)"

ELIGIBILITY_UNKNOWN = (
    "Set-aside status not reported (blank \u2260 unrestricted). Verify against "
    "SAM.gov / USAspending before relying on this."
)

ELIGIBILITY_UNRESTRICTED = (
    "No set-aside restriction reported (set-aside = NONE) \u2014 an NPA is not "
    "barred BY A SET-ASIDE from priming. This does NOT establish that the work "
    "is competable or full-and-open: extent of competition is a separate fact "
    "not provided here, and a NONE set-aside can still be sole-source or not "
    "available for competition (e.g. a statutory or existing mandatory-source "
    "route). Eligibility-open is NOT a pursuit recommendation; other gates "
    "still apply."
)

ELIGIBILITY_SET_ASIDE_BARRED = (
    "This work is set aside for small-business / socioeconomic concerns. A "
    "nonprofit agency is not a 'small business concern' (13 CFR 121.105), so "
    "the NPA is structurally ineligible to PRIME it as a set-aside."
)

ELIGIBILITY_BARRED_BUY_INDIAN = (
    "This work is set aside under the Buy-Indian program (Indian Economic "
    "Enterprise). An AbilityOne nonprofit agency is not an Indian Economic "
    "Enterprise, so it cannot prime this set-aside. This is a Buy-Indian "
    "eligibility bar, not a small-business-rule determination."
)

ELIGIBILITY_BARRED_UNVERIFIED = (
    "A set-aside restriction is present (code shown), but its category is not "
    "confirmed here. A set-aside reserves the work for a specific offeror "
    "category, and an NPA prime is not established for any set-aside, so this "
    "is treated as barred \u2014 verify the exact set-aside type against SAM.gov / "
    "USAspending. Do not apply a small-business rationale until the code is "
    "confirmed; some set-asides (e.g. local-area/disaster or Buy-Indian) are "
    "not small-business-based."
)

ELIGIBILITY_PARTIAL_NOTE = (
    "This is a PARTIAL set-aside \u2014 only a portion of the work is reserved for "
    "the set-aside category. Whether an unrestricted remainder exists that an NPA "
    "could prime is a separate question not assessed here."
)

ELIGIBILITY_MANDATORY_SOURCE_LANE = (
    "This bar closes the prime-as-a-set-aside lane only. A separate AbilityOne "
    "mandatory-source lane (FAR 8.002 / FAR subpart 8.7) is NOT assessed here: "
    "a requirement added to the Procurement List is a mandatory source; for "
    "small-business set-asides that priority sits above the set-aside. How it "
    "interacts with other set-aside families is likewise not assessed here. "
    "Whether this requirement is on, or suitable for, the Procurement List is "
    "not assessed by this gate — see the R2a determination-support map."
)

ELIGIBILITY_TEAMING_LANE = (
    "A subcontract / teaming lane (R1-teaming) may still apply \u2014 not assessed "
    "here."
)

ELIGIBILITY_PRESENTS_NOT_DETERMINES = (
    "This gate presents the cited set-aside status plus a structural rule for "
    "analyst review; it does not determine eligibility. The human decides."
)


# Common FPDS set-aside codes.  This map is display help only: recognition does
# not change the classifier's fail-closed rule that every non-NONE, non-blank
# value is a set-aside.  An absent code is labeled unrecognized rather than
# assigned a guessed meaning.
_SET_ASIDE_LABELS = {
    "8a": "8(a) set-aside",
    "8an": "8(a) sole source",
    "edwosb": "Economically Disadvantaged WOSB",
    "edwosbss": "Economically Disadvantaged WOSB sole source",
    "hzc": "HUBZone",
    "hzs": "HUBZone sole source",
    "iee": "Indian Economic Enterprise",
    "isbee": "Indian Small Business Economic Enterprise",
    "sba": "Total Small Business",
    "sbp": "Partial Small Business",
    "sdvosbc": "SDVOSB",
    "sdvosbs": "SDVOSB sole source",
    "vsa": "Veteran-Owned Small Business",
    "vss": "Veteran-Owned Small Business sole source",
    "wosb": "WOSB",
    "wosbss": "WOSB sole source",
}

_SET_ASIDE_FAMILIES = {
    "8a": "small_business",
    "8an": "small_business",
    "edwosb": "small_business",
    "edwosbss": "small_business",
    "hzc": "small_business",
    "hzs": "small_business",
    "sba": "small_business",
    "sbp": "small_business",
    "sdvosbc": "small_business",
    "sdvosbs": "small_business",
    "vsa": "small_business",
    "vss": "small_business",
    "wosb": "small_business",
    "wosbss": "small_business",
    "iee": "buy_indian",
    "isbee": "buy_indian",
}


def assess_eligibility(raw_set_aside: str | None) -> EligibilityGate:
    """Classify a raw FPDS-style set-aside value without making a verdict.

    Whitespace and case are ignored only for classification and friendly-label
    lookup.  ``raw_set_aside`` itself is retained unchanged for provenance.
    Blank values never default to no set-aside; only the affirmative code
    ``NONE`` enters the no-set-aside, still-amber state.
    """

    if raw_set_aside is None or not raw_set_aside.strip():
        return EligibilityGate(
            raw_set_aside=raw_set_aside,
            state=EligibilityState.UNKNOWN,
            set_aside_label=None,
            set_aside_family=None,
            recognized=False,
        )

    normalized = raw_set_aside.strip().casefold()
    if normalized == "none":
        return EligibilityGate(
            raw_set_aside=raw_set_aside,
            state=EligibilityState.UNRESTRICTED,
            set_aside_label="No set-aside (set-aside = NONE)",
            set_aside_family=None,
            recognized=True,
        )

    label = _SET_ASIDE_LABELS.get(normalized)
    return EligibilityGate(
        raw_set_aside=raw_set_aside,
        state=EligibilityState.SET_ASIDE_BARRED,
        set_aside_label=label,
        set_aside_family=_SET_ASIDE_FAMILIES.get(normalized),
        recognized=label is not None,
    )


def _state_headline(state: EligibilityState) -> str:
    if state is EligibilityState.UNKNOWN:
        return "### UNKNOWN \u2014 verification required"
    if state is EligibilityState.UNRESTRICTED:
        return "### NO SET-ASIDE \u2014 eligibility-open (amber)"
    return "### SET_ASIDE_BARRED (set-aside prime lane)"


def _raw_set_aside_text(raw_set_aside: str | None) -> str:
    if raw_set_aside is None:
        return "None (no value supplied)"
    return f'"{_md(raw_set_aside)}"'


def eligibility_gate_lines(
    gate: EligibilityGate,
    *,
    source_lines: tuple[str, ...] | None = None,
) -> list[str]:
    """Render the eligibility gate as caveat-first Markdown lines (pure).

    The state framing and applicable structural caveat precede the raw fact so
    the entered value cannot be read in isolation as an eligibility or pursuit
    verdict.  The raw input is always surfaced and Markdown-escaped.
    """

    lines: list[str] = [
        ELIGIBILITY_GATE_HEADER,
        "",
        _state_headline(gate.state),
        "",
        f"- {ELIGIBILITY_PRESENTS_NOT_DETERMINES}",
    ]
    if gate.state is EligibilityState.UNKNOWN:
        lines.append(f"- {ELIGIBILITY_UNKNOWN}")
    elif gate.state is EligibilityState.UNRESTRICTED:
        lines.append(f"- {ELIGIBILITY_UNRESTRICTED}")
    else:
        if gate.set_aside_family == "small_business":
            barred_rationale = ELIGIBILITY_SET_ASIDE_BARRED
        elif gate.set_aside_family == "buy_indian":
            barred_rationale = ELIGIBILITY_BARRED_BUY_INDIAN
        else:
            barred_rationale = ELIGIBILITY_BARRED_UNVERIFIED
        lines.append(f"- {barred_rationale}")
        # A partial set-aside (e.g. SBP) reserves only a portion for the set-aside
        # category; the unrestricted remainder is a separate, unassessed question,
        # so the barred rationale must not read as closing the whole opportunity.
        if gate.set_aside_label and "Partial" in gate.set_aside_label:
            lines.append(f"- {ELIGIBILITY_PARTIAL_NOTE}")
        # AbilityOne NPAs need the separate R2a lane named so the set-aside bar
        # cannot read as closing that unassessed path (finding A1, ADR-029).
        lines.append(f"- {ELIGIBILITY_MANDATORY_SOURCE_LANE}")
        lines.append(f"- {ELIGIBILITY_TEAMING_LANE}")

    lines.append("")
    if source_lines is None:
        lines.append(
            "- Source: analyst-entered set-aside value; not independently "
            "verified against SAM.gov or USAspending."
        )
        raw_label = "Raw set-aside (analyst-entered): "
    else:
        for line in source_lines:
            lines.append(f"- {line}")
        raw_label = "Raw set-aside (from USAspending FPDS): "
    lines.append(f"- {raw_label}{_raw_set_aside_text(gate.raw_set_aside)}")
    if gate.recognized and gate.set_aside_label:
        lines.append(f"- Interpreted label: {gate.set_aside_label}")
    elif gate.state is EligibilityState.SET_ASIDE_BARRED:
        lines.append(
            "- Interpreted label: unrecognized set-aside code \u2014 treated as a "
            "set-aside"
        )
    lines.append("")
    return lines


__all__ = [
    "ELIGIBILITY_BARRED_BUY_INDIAN",
    "ELIGIBILITY_BARRED_UNVERIFIED",
    "ELIGIBILITY_GATE_HEADER",
    "ELIGIBILITY_MANDATORY_SOURCE_LANE",
    "ELIGIBILITY_PARTIAL_NOTE",
    "ELIGIBILITY_PRESENTS_NOT_DETERMINES",
    "ELIGIBILITY_SET_ASIDE_BARRED",
    "ELIGIBILITY_TEAMING_LANE",
    "ELIGIBILITY_UNKNOWN",
    "ELIGIBILITY_UNRESTRICTED",
    "EligibilityGate",
    "EligibilityState",
    "assess_eligibility",
    "eligibility_gate_lines",
]
