"""Staffing what-if (ODLH delta) for the cited Opportunity Packet (A6, ADR-021).

An analyst enters the agency's CURRENT, observed staffing baseline and a
contract staffing SCENARIO (the addition being contemplated if this contract
is won and staffed); this module computes the marginal effect on the
agency-wide ODLH ratio -- disabled direct labor hours divided by total
direct labor hours -- and renders it as a labeled PLANNING INDICATOR, never
an official ODLH compliance determination, framed as evidence toward
suitability criterion (a)(2) only (owner-attested domain constants, ADR-020).

**Two entry modes (owner-attested, ADR-020), chosen by an EXPLICIT mode
discriminator that travels with the input -- never inferred from which
fields happen to be populated:**

* ``HOURS`` -- direct labor hours, exact. The analyst enters DIRECT labor
  hours only; supervisory and indirect hours are excluded from the ODLH
  computation entirely (owner-attested).
* ``FTE`` -- headcounts by employee code (01 non-disabled, 02 disabled, 07
  pending disability documentation). This is an APPROXIMATION of the
  hours-based statutory ratio: a headcount cannot separate a person's
  supervisory/indirect hours from their direct-labor hours, so this mode
  CANNOT perform the supervisory/indirect exclusion the HOURS mode can --
  that is a core reason the FTE result is only an approximation, never the
  ratio itself. Code 07 renders for context but is never counted in either
  the numerator or the denominator.

**The baseline is OBSERVED (dashboard-visible), never an assumption.** The
scenario's TOTAL (hours or FTE being added) is analyst-entered, but the
scenario's QUALIFYING portion of that addition is necessarily an ASSUMPTION
about a workforce not yet hired -- entered as EITHER an assumed qualifying
SHARE of the addition (a fraction in [0, 1]) OR an assumed qualifying COUNT
(hours or FTEs), never both (fail-closed, no silent precedence).

This module is pure (no Streamlit, no network, no case-store imports) and
consumes ONLY the analyst-entered numbers passed to it. It must not depend on
synthetic datasets, bulk analytics, or the case store. Its local ratio helper
returns NaN for a nonpositive denominator so an invalid baseline cannot become
a fabricated numeric result, while keeping that rule inside this pure module.

Every rejection is an honest ``CANNOT_COMPUTE`` result with a fixed,
descriptive reason -- never a raised exception for ordinary invalid analyst
input, and never a fabricated number for a partial entry (fail-closed
honesty). See ADR-021 for the full design record (why no ramp
curve, why no per-project PLDLH calculator, formula version ``WHATIF-1.0``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

WHATIF_VERSION = "WHATIF-1.0"


class WhatIfMode(str, Enum):
    """The explicit, caller-declared entry-mode discriminator (owner-attested, ADR-020)."""

    HOURS = "HOURS"
    FTE = "FTE"


class WhatIfState(str, Enum):
    """Whether a usable what-if result could be computed."""

    COMPUTED = "COMPUTED"
    CANNOT_COMPUTE = "CANNOT_COMPUTE"


@dataclass(frozen=True, slots=True)
class StaffingWhatIfInput:
    """Analyst-entered staffing what-if input.

    ``mode`` is the EXPLICIT discriminator (never inferred from which fields
    are populated). Only the fields belonging to the declared mode may carry
    a value; a populated field from the OTHER mode -- e.g. stale session
    state left over from a UI mode toggle -- is a mode-field disagreement and
    fails closed rather than silently being ignored or blended in.

    BASELINE fields (``baseline_*``) describe the agency's CURRENT, OBSERVED
    staffing state (dashboard-visible; not an assumption). SCENARIO fields
    (``scenario_*``) describe the contract staffing ADDITION being
    contemplated: ``scenario_total_hours`` / ``scenario_total_fte`` is the
    size of the addition, and its qualifying portion is given as EITHER
    ``scenario_qualifying_share`` (a fraction of the addition assumed
    qualifying) OR ``scenario_qualifying_count`` (an exact assumed qualifying
    hours/FTE count) -- never both.
    """

    mode: WhatIfMode

    # --- HOURS mode ------------------------------------------------------
    baseline_qualifying_hours: float | None = None
    baseline_total_hours: float | None = None
    scenario_total_hours: float | None = None

    # --- FTE mode ----------------------------------------------------------
    baseline_code_01: float | None = None
    baseline_code_02: float | None = None
    baseline_code_07: float | None = None  # optional, display-only, never counted
    scenario_total_fte: float | None = None

    # --- Scenario qualifying entry: share XOR count, either mode -----------
    scenario_qualifying_share: float | None = None
    scenario_qualifying_count: float | None = None


@dataclass(frozen=True, slots=True)
class StaffingWhatIfResult:
    """One what-if assessment. ``CANNOT_COMPUTE`` carries a reason, never a fabricated number."""

    state: WhatIfState
    mode: WhatIfMode
    version: str = WHATIF_VERSION
    reason: str | None = None
    baseline_qualifying: float | None = None
    baseline_total: float | None = None
    baseline_code_07: float | None = None
    scenario_qualifying_added: float | None = None
    scenario_total_added: float | None = None
    baseline_ratio: float | None = None
    scenario_ratio: float | None = None
    delta: float | None = None


# --- Local NaN-honesty ratio helper ------------------------------------------
# A nonpositive denominator is not computable and must yield NaN, never zero.
# Keeping this helper local preserves the module's pure, input-only boundary.


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return float("nan")
    return float(numerator / denominator)


# --- Fixed, fail-closed reason messages ---------------------------------------

REASON_MODE_DISAGREEMENT = (
    "cannot compute — the entered fields do not match the declared entry "
    "mode; a stale value from the other entry mode was not cleared."
)

REASON_SHARE_AND_COUNT_BOTH = (
    "cannot compute — supply either an assumed qualifying share or a "
    "qualifying count, not both."
)

REASON_NON_FINITE_OR_NEGATIVE = (
    "cannot compute — every entered number must be a finite value of zero "
    "or greater."
)

REASON_SHARE_OUT_OF_RANGE = (
    "cannot compute — the assumed qualifying share must be between 0 and 1."
)

REASON_INCOMPLETE = (
    "cannot compute — baseline and scenario values for the selected entry "
    "mode are incomplete."
)

REASON_BASELINE_QUALIFYING_EXCEEDS_TOTAL = (
    "cannot compute — the baseline qualifying hours cannot exceed the "
    "baseline total hours."
)

REASON_SCENARIO_QUALIFYING_EXCEEDS_TOTAL = (
    "cannot compute — the scenario's assumed qualifying amount cannot "
    "exceed the scenario's total amount."
)


def _cannot_compute(mode: WhatIfMode, reason: str) -> StaffingWhatIfResult:
    return StaffingWhatIfResult(state=WhatIfState.CANNOT_COMPUTE, mode=mode, reason=reason)


def assess_staffing_whatif(data: StaffingWhatIfInput) -> StaffingWhatIfResult:
    """Compute the agency-wide baseline/scenario ODLH ratio delta (pure).

    Validation order: mode-field disagreement, share-XOR-count, finite/
    non-negative sweep, share range, per-mode completeness, then
    qualifying-may-not-exceed-total. Any failure returns an honest
    ``CANNOT_COMPUTE`` result with a fixed reason -- never a raised
    exception for ordinary invalid analyst input, and never a fabricated
    number for a partial entry.
    """

    mode = data.mode

    # 1. Mode-field disagreement: only the declared mode's fields may be populated.
    if mode is WhatIfMode.HOURS:
        other_mode_fields = (
            data.baseline_code_01,
            data.baseline_code_02,
            data.baseline_code_07,
            data.scenario_total_fte,
        )
    else:
        other_mode_fields = (
            data.baseline_qualifying_hours,
            data.baseline_total_hours,
            data.scenario_total_hours,
        )
    if any(value is not None for value in other_mode_fields):
        return _cannot_compute(mode, REASON_MODE_DISAGREEMENT)

    # 2. Share XOR count.
    share = data.scenario_qualifying_share
    count = data.scenario_qualifying_count
    if share is not None and count is not None:
        return _cannot_compute(mode, REASON_SHARE_AND_COUNT_BOTH)

    # 3. Finite / non-negative sweep over every populated numeric field.
    candidates = (
        data.baseline_qualifying_hours,
        data.baseline_total_hours,
        data.scenario_total_hours,
        data.baseline_code_01,
        data.baseline_code_02,
        data.baseline_code_07,
        data.scenario_total_fte,
        share,
        count,
    )
    for value in candidates:
        if value is not None and (not math.isfinite(value) or value < 0):
            return _cannot_compute(mode, REASON_NON_FINITE_OR_NEGATIVE)

    # 4. Share range [0, 1].
    if share is not None and not (0.0 <= share <= 1.0):
        return _cannot_compute(mode, REASON_SHARE_OUT_OF_RANGE)

    # 5. Per-mode completeness (baseline exact; scenario total + a resolved
    #    qualifying assumption -- at least one of share/count is required).
    if mode is WhatIfMode.HOURS:
        if (
            data.baseline_qualifying_hours is None
            or data.baseline_total_hours is None
            or not (data.baseline_total_hours > 0)
        ):
            return _cannot_compute(mode, REASON_INCOMPLETE)
        if data.scenario_total_hours is None:
            return _cannot_compute(mode, REASON_INCOMPLETE)
        baseline_qualifying = data.baseline_qualifying_hours
        baseline_total = data.baseline_total_hours
        baseline_code_07 = None
        scenario_total_added = data.scenario_total_hours
    else:
        if (
            data.baseline_code_01 is None
            or data.baseline_code_02 is None
            or not (data.baseline_code_01 + data.baseline_code_02 > 0)
        ):
            return _cannot_compute(mode, REASON_INCOMPLETE)
        if data.scenario_total_fte is None:
            return _cannot_compute(mode, REASON_INCOMPLETE)
        baseline_qualifying = data.baseline_code_02
        baseline_total = data.baseline_code_01 + data.baseline_code_02
        baseline_code_07 = data.baseline_code_07
        scenario_total_added = data.scenario_total_fte

    if share is None and count is None:
        return _cannot_compute(mode, REASON_INCOMPLETE)

    # 6. Qualifying may not exceed total -- baseline, then resolve + check the
    #    scenario's assumed qualifying amount (no clamping, ever).
    if baseline_qualifying > baseline_total:
        return _cannot_compute(mode, REASON_BASELINE_QUALIFYING_EXCEEDS_TOTAL)

    if count is not None:
        if count > scenario_total_added:
            return _cannot_compute(mode, REASON_SCENARIO_QUALIFYING_EXCEEDS_TOTAL)
        scenario_qualifying_added = count
    else:
        # share in [0, 1] and scenario_total_added >= 0 already guarantees
        # share * total <= total -- no separate exceeds-total check needed.
        scenario_qualifying_added = share * scenario_total_added

    baseline_ratio = _safe_ratio(baseline_qualifying, baseline_total)
    scenario_ratio = _safe_ratio(
        baseline_qualifying + scenario_qualifying_added,
        baseline_total + scenario_total_added,
    )
    delta = (
        scenario_ratio - baseline_ratio
        if math.isfinite(baseline_ratio) and math.isfinite(scenario_ratio)
        else float("nan")
    )

    return StaffingWhatIfResult(
        state=WhatIfState.COMPUTED,
        mode=mode,
        baseline_qualifying=baseline_qualifying,
        baseline_total=baseline_total,
        baseline_code_07=baseline_code_07,
        scenario_qualifying_added=scenario_qualifying_added,
        scenario_total_added=scenario_total_added,
        baseline_ratio=baseline_ratio,
        scenario_ratio=scenario_ratio,
        delta=delta,
    )


# --- Rendering ---------------------------------------------------------------
#
# Caveat-first, exactly like the rest of the packet: framing, assumption, and
# mode-aware exclusion notes always precede any number, so a ratio can never
# be read in isolation as a determination.

STAFFING_HEADER = "## Staffing what-if (ODLH planning indicator)"

STAFFING_PLANNING_INDICATOR_NOTE = (
    "This is a labeled PLANNING INDICATOR only, never an official ODLH "
    "compliance determination. It does not compute or claim the "
    "agency's real, current ODLH compliance status."
)

STAFFING_A2_EVIDENCE_NOTE = (
    "Framed as evidence toward suitability criterion (a)(2) — the NPA's "
    "qualifications to satisfactorily perform the work — only. It is not "
    "itself a suitability determination; the Commission determines "
    "suitability."
)

STAFFING_PLDLH_CONTEXT_NOTE = (
    "Context (owner-attested, ADR-020): a per-PL-project or product-family "
    "ratio (PLDLH, a.k.a. EDLH — \"Estimated Direct Hours\") may be "
    "Commission-approved BELOW the 75% floor, permissible only while the "
    "agency maintains the 75% ODLH ratio overall. This what-if computes the "
    "AGENCY-WIDE ODLH ratio only; it does not compute a per-project "
    "PLDLH/EDLH figure."
)

STAFFING_UNVERIFIED_SUPPLY_CAVEAT = (
    "The scenario's assumed qualifying share/count is an ANALYST ASSUMPTION "
    "about a workforce not yet hired — UNVERIFIED supply, not observed "
    "evidence."
)

STAFFING_NO_RAMP_NOTE = (
    "This is an END-STATE delta only — the difference once the scenario's "
    "staffing is fully in place. Ramp timing is site-dependent (an "
    "incumbent-workforce transition ramps differently than mass recruiting, "
    "owner-attested) and is not modeled here."
)

STAFFING_HOURS_EXCLUSION_NOTE = (
    "Enter DIRECT labor hours only — supervisory and indirect hours are "
    "excluded from the ODLH computation entirely (owner-attested, ADR-020)."
)

STAFFING_FTE_EXCLUSION_CAVEAT = (
    "An FTE headcount cannot separate a person's supervisory/indirect hours "
    "from their direct-labor hours, so this entry mode CANNOT perform the "
    "supervisory/indirect exclusion the hours-based ODLH ratio requires — a "
    "core reason this result is only an APPROXIMATION of the hours-based "
    "statutory ratio, never the ratio itself."
)

STAFFING_CODE_07_NOTE = (
    "Code 07 (pending disability documentation) renders for context only — "
    "it is never counted in the numerator or the denominator."
)

_MD_ESCAPE = {ch: "\\" + ch for ch in "\\`*[]()<>"}


def _md(value: object) -> str:
    if value is None:
        return ""
    flat = " ".join(str(value).splitlines())
    return "".join(_MD_ESCAPE.get(ch, ch) for ch in flat)


def _count(value: float) -> str:
    # Raw hour/FTE counts render thousands-separated, never in scientific
    # notation -- agency-wide hours are routinely in the millions, and "2e+06"
    # in a cited evidence packet reads as a rendering glitch. Whole values
    # drop the decimal; fractional FTE entries keep one place.
    if value == int(value):
        return f"{value:,.0f}"
    return f"{value:,.1f}"


def _pct(ratio: float) -> str:
    if not math.isfinite(ratio):
        return "not computable"
    return f"{ratio * 100:.1f}%"


def _pp_delta(delta: float) -> str:
    if not math.isfinite(delta):
        return "not computable"
    return f"{delta * 100:+.1f} pp"


def _mode_label(mode: WhatIfMode) -> str:
    return "hours" if mode is WhatIfMode.HOURS else "FTE (approximation)"


def staffing_whatif_lines(result: StaffingWhatIfResult) -> list[str]:
    """Render the staffing what-if as caveat-first Markdown lines (pure)."""

    lines: list[str] = [
        STAFFING_HEADER,
        "",
        f"- Entry mode: {_md(_mode_label(result.mode))}",
        f"- Formula version: {_md(result.version)}",
        f"- {STAFFING_PLANNING_INDICATOR_NOTE}",
        f"- {STAFFING_A2_EVIDENCE_NOTE}",
    ]
    if result.mode is WhatIfMode.HOURS:
        lines.append(f"- {STAFFING_HOURS_EXCLUSION_NOTE}")
    else:
        lines.append(f"- {STAFFING_FTE_EXCLUSION_CAVEAT}")
    lines.append(f"- {STAFFING_PLDLH_CONTEXT_NOTE}")
    lines.append(f"- {STAFFING_NO_RAMP_NOTE}")
    lines.append("")

    if result.state is WhatIfState.CANNOT_COMPUTE:
        lines.append(f"- {_md(result.reason)}")
        lines.append("")
        return lines

    assert result.baseline_ratio is not None
    assert result.scenario_ratio is not None
    assert result.delta is not None
    assert result.baseline_qualifying is not None
    assert result.baseline_total is not None
    assert result.scenario_qualifying_added is not None
    assert result.scenario_total_added is not None

    unit = "hours" if result.mode is WhatIfMode.HOURS else "FTE"
    lines.append(f"- {STAFFING_UNVERIFIED_SUPPLY_CAVEAT}")
    lines.append(
        f"- Baseline (observed): {_count(result.baseline_qualifying)} qualifying "
        f"{unit} of {_count(result.baseline_total)} total {unit} — "
        f"{_md(_pct(result.baseline_ratio))}"
    )
    if result.baseline_code_07 is not None:
        lines.append(
            f"- Baseline code 07 (pending disability documentation): "
            f"{_count(result.baseline_code_07)} {unit}. {STAFFING_CODE_07_NOTE}"
        )
    lines.append(
        f"- Scenario addition (assumed): {_count(result.scenario_qualifying_added)} "
        f"qualifying {unit} of {_count(result.scenario_total_added)} total {unit} added"
    )
    lines.append(
        f"- Scenario (baseline + addition): "
        f"{_count(result.baseline_qualifying + result.scenario_qualifying_added)} "
        f"qualifying {unit} of "
        f"{_count(result.baseline_total + result.scenario_total_added)} total {unit} — "
        f"{_md(_pct(result.scenario_ratio))}"
    )
    lines.append(f"- Delta: {_md(_pp_delta(result.delta))} (scenario minus baseline)")
    lines.append("")
    return lines


__all__ = [
    "REASON_BASELINE_QUALIFYING_EXCEEDS_TOTAL",
    "REASON_INCOMPLETE",
    "REASON_MODE_DISAGREEMENT",
    "REASON_NON_FINITE_OR_NEGATIVE",
    "REASON_SCENARIO_QUALIFYING_EXCEEDS_TOTAL",
    "REASON_SHARE_AND_COUNT_BOTH",
    "REASON_SHARE_OUT_OF_RANGE",
    "STAFFING_A2_EVIDENCE_NOTE",
    "STAFFING_CODE_07_NOTE",
    "STAFFING_FTE_EXCLUSION_CAVEAT",
    "STAFFING_HEADER",
    "STAFFING_HOURS_EXCLUSION_NOTE",
    "STAFFING_NO_RAMP_NOTE",
    "STAFFING_PLANNING_INDICATOR_NOTE",
    "STAFFING_PLDLH_CONTEXT_NOTE",
    "STAFFING_UNVERIFIED_SUPPLY_CAVEAT",
    "WHATIF_VERSION",
    "StaffingWhatIfInput",
    "StaffingWhatIfResult",
    "WhatIfMode",
    "WhatIfState",
    "assess_staffing_whatif",
    "staffing_whatif_lines",
]
