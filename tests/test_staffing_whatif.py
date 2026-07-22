"""Offline unit tests for the Staffing what-if module (A6, ADR-021).

Covers: the pinned two-mode input contract (explicit mode discriminator,
mode-field disagreement rejected, share XOR count, per-mode completeness,
fail-closed partials never produce a fabricated number), hand-computed ratio
math (AGENTS #10 test vectors, delta both directions), the mode-aware
supervisory/indirect-exclusion note (audit MAJOR: a flat "excluded" line is
FALSE in FTE mode), code-07 shown-never-counted, and the guarded-vocabulary /
never-a-determination framing.
"""

from __future__ import annotations

import math

import pytest

from tens_hq.staffing_whatif import (
    REASON_BASELINE_QUALIFYING_EXCEEDS_TOTAL,
    REASON_INCOMPLETE,
    REASON_MODE_DISAGREEMENT,
    REASON_NON_FINITE_OR_NEGATIVE,
    REASON_SCENARIO_QUALIFYING_EXCEEDS_TOTAL,
    REASON_SHARE_AND_COUNT_BOTH,
    REASON_SHARE_OUT_OF_RANGE,
    WHATIF_VERSION,
    StaffingWhatIfInput,
    WhatIfMode,
    WhatIfState,
    assess_staffing_whatif,
    staffing_whatif_lines,
)


def _render(data: StaffingWhatIfInput) -> str:
    return "\n".join(staffing_whatif_lines(assess_staffing_whatif(data)))


# --- Hand-computed ratio math (AGENTS #10 test vectors) -----------------------


def test_hours_mode_hand_computed_negative_delta_via_count() -> None:
    # baseline 750/1000 = 75.0%; scenario adds 100/200 qualifying/total
    # (a LOWER share than baseline) -> combined 850/1200 = 70.8333...%.
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=750.0,
        baseline_total_hours=1000.0,
        scenario_total_hours=200.0,
        scenario_qualifying_count=100.0,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.COMPUTED
    assert result.baseline_ratio == pytest.approx(0.75)
    assert result.scenario_ratio == pytest.approx(850.0 / 1200.0)
    assert result.delta == pytest.approx((850.0 / 1200.0) - 0.75)
    assert result.delta < 0  # dilutes the ratio
    rendered = _render(data)
    assert "75.0%" in rendered
    assert "70.8%" in rendered
    assert "-4.2 pp" in rendered


def test_hours_mode_hand_computed_positive_delta_via_share() -> None:
    # baseline 300/1000 = 30.0%; scenario adds 500 total with an assumed 80%
    # qualifying share (400 qualifying) -> combined 700/1500 = 46.6667%.
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=300.0,
        baseline_total_hours=1000.0,
        scenario_total_hours=500.0,
        scenario_qualifying_share=0.8,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.COMPUTED
    assert result.scenario_qualifying_added == pytest.approx(400.0)
    assert result.baseline_ratio == pytest.approx(0.3)
    assert result.scenario_ratio == pytest.approx(700.0 / 1500.0)
    assert result.delta > 0  # raises the ratio
    rendered = _render(data)
    assert "30.0%" in rendered
    assert "46.7%" in rendered
    assert "+16.7 pp" in rendered


def test_fte_mode_hand_computed_with_code_07_display_only() -> None:
    # baseline 30/100 = 30.0%; scenario adds 20 FTE with 10 assumed
    # qualifying -> combined 40/120 = 33.3333%. code_07=5 is display-only.
    data = StaffingWhatIfInput(
        mode=WhatIfMode.FTE,
        baseline_code_01=70.0,
        baseline_code_02=30.0,
        baseline_code_07=5.0,
        scenario_total_fte=20.0,
        scenario_qualifying_count=10.0,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.COMPUTED
    assert result.baseline_total == pytest.approx(100.0)  # 07 excluded from total
    assert result.baseline_ratio == pytest.approx(0.3)
    assert result.scenario_ratio == pytest.approx(40.0 / 120.0)
    assert result.delta == pytest.approx((40.0 / 120.0) - 0.3)
    rendered = _render(data)
    assert "30.0%" in rendered
    assert "33.3%" in rendered
    assert "+3.3 pp" in rendered
    assert "5" in rendered  # code_07 value shown
    assert "never counted" in rendered.lower()


# --- Version tag (AGENTS #10) --------------------------------------------------


def test_version_tag_is_whatif_1_0_and_always_rendered() -> None:
    assert WHATIF_VERSION == "WHATIF-1.0"
    data = StaffingWhatIfInput(mode=WhatIfMode.HOURS)
    rendered = _render(data)  # CANNOT_COMPUTE (nothing entered) still shows the tag
    assert "WHATIF-1.0" in rendered


# --- Mode-field disagreement (pinned, no SME discretion) -----------------------


def test_hours_mode_rejects_fte_field_populated() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=750.0,
        baseline_total_hours=1000.0,
        scenario_total_hours=200.0,
        scenario_qualifying_count=100.0,
        baseline_code_01=10.0,  # stale FTE-mode field
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.CANNOT_COMPUTE
    assert result.reason == REASON_MODE_DISAGREEMENT


def test_fte_mode_rejects_hours_field_populated() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.FTE,
        baseline_code_01=70.0,
        baseline_code_02=30.0,
        scenario_total_fte=20.0,
        scenario_qualifying_count=10.0,
        baseline_total_hours=1000.0,  # stale HOURS-mode field
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.CANNOT_COMPUTE
    assert result.reason == REASON_MODE_DISAGREEMENT


# --- Share XOR count ------------------------------------------------------------


def test_share_and_count_both_supplied_fails_closed() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=750.0,
        baseline_total_hours=1000.0,
        scenario_total_hours=200.0,
        scenario_qualifying_count=100.0,
        scenario_qualifying_share=0.5,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.CANNOT_COMPUTE
    assert result.reason == REASON_SHARE_AND_COUNT_BOTH
    assert result.reason == (
        "cannot compute — supply either an assumed qualifying share or a "
        "qualifying count, not both."
    )


def test_neither_share_nor_count_supplied_is_incomplete() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=750.0,
        baseline_total_hours=1000.0,
        scenario_total_hours=200.0,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.CANNOT_COMPUTE
    assert result.reason == REASON_INCOMPLETE


# --- Per-mode completeness / fail-closed partials -------------------------------


def test_hours_mode_zero_total_denominator_is_incomplete_not_a_crash() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=0.0,
        baseline_total_hours=0.0,
        scenario_total_hours=10.0,
        scenario_qualifying_count=5.0,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.CANNOT_COMPUTE
    assert result.reason == REASON_INCOMPLETE


def test_fte_mode_zero_sum_denominator_is_incomplete() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.FTE,
        baseline_code_01=0.0,
        baseline_code_02=0.0,
        scenario_total_fte=10.0,
        scenario_qualifying_count=5.0,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.CANNOT_COMPUTE
    assert result.reason == REASON_INCOMPLETE


def test_fte_mode_code_07_only_without_01_or_02_is_incomplete() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.FTE,
        baseline_code_07=5.0,
        scenario_total_fte=10.0,
        scenario_qualifying_count=5.0,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.CANNOT_COMPUTE
    assert result.reason == REASON_INCOMPLETE


def test_hours_mode_missing_scenario_total_is_incomplete() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=750.0,
        baseline_total_hours=1000.0,
        scenario_qualifying_count=100.0,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.CANNOT_COMPUTE
    assert result.reason == REASON_INCOMPLETE


def test_all_blank_input_is_incomplete_not_a_crash() -> None:
    for mode in (WhatIfMode.HOURS, WhatIfMode.FTE):
        result = assess_staffing_whatif(StaffingWhatIfInput(mode=mode))
        assert result.state is WhatIfState.CANNOT_COMPUTE
        assert result.reason == REASON_INCOMPLETE


# --- Negative / non-finite rejected ---------------------------------------------


def test_negative_value_is_rejected() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=-5.0,
        baseline_total_hours=1000.0,
        scenario_total_hours=200.0,
        scenario_qualifying_count=100.0,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.CANNOT_COMPUTE
    assert result.reason == REASON_NON_FINITE_OR_NEGATIVE


@pytest.mark.parametrize("bad", [math.inf, math.nan, -math.inf])
def test_non_finite_value_is_rejected(bad: float) -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=750.0,
        baseline_total_hours=1000.0,
        scenario_total_hours=bad,
        scenario_qualifying_count=100.0,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.CANNOT_COMPUTE
    assert result.reason == REASON_NON_FINITE_OR_NEGATIVE


def test_negative_fte_count_is_rejected() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.FTE,
        baseline_code_01=70.0,
        baseline_code_02=-1.0,
        scenario_total_fte=20.0,
        scenario_qualifying_count=10.0,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.CANNOT_COMPUTE
    assert result.reason == REASON_NON_FINITE_OR_NEGATIVE


# --- Share range [0, 1] ----------------------------------------------------------


def test_share_above_one_is_rejected() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=750.0,
        baseline_total_hours=1000.0,
        scenario_total_hours=200.0,
        scenario_qualifying_share=1.5,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.CANNOT_COMPUTE
    assert result.reason == REASON_SHARE_OUT_OF_RANGE


def test_share_boundaries_zero_and_one_are_valid() -> None:
    for boundary in (0.0, 1.0):
        data = StaffingWhatIfInput(
            mode=WhatIfMode.HOURS,
            baseline_qualifying_hours=750.0,
            baseline_total_hours=1000.0,
            scenario_total_hours=200.0,
            scenario_qualifying_share=boundary,
        )
        result = assess_staffing_whatif(data)
        assert result.state is WhatIfState.COMPUTED


# --- Qualifying may not exceed total (fail-closed, no clamping) ----------------


def test_baseline_qualifying_exceeds_total_is_rejected() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=900.0,
        baseline_total_hours=800.0,
        scenario_total_hours=200.0,
        scenario_qualifying_count=100.0,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.CANNOT_COMPUTE
    assert result.reason == REASON_BASELINE_QUALIFYING_EXCEEDS_TOTAL


def test_scenario_qualifying_count_exceeds_total_is_rejected_no_clamping() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=750.0,
        baseline_total_hours=1000.0,
        scenario_total_hours=100.0,
        scenario_qualifying_count=150.0,
    )
    result = assess_staffing_whatif(data)
    assert result.state is WhatIfState.CANNOT_COMPUTE
    assert result.reason == REASON_SCENARIO_QUALIFYING_EXCEEDS_TOTAL


# --- Mode-aware supervisory/indirect-exclusion note (audit MAJOR) --------------


def test_hours_mode_states_direct_hours_exclusion() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=750.0,
        baseline_total_hours=1000.0,
        scenario_total_hours=200.0,
        scenario_qualifying_count=100.0,
    )
    rendered = _render(data).lower()
    assert "supervisory and indirect hours are excluded from the odlh computation" in rendered
    # The FTE-only "cannot perform" caveat must not leak into the HOURS render.
    assert "cannot perform" not in rendered


def test_fte_mode_states_it_cannot_perform_the_exclusion_not_a_flat_excluded_claim() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.FTE,
        baseline_code_01=70.0,
        baseline_code_02=30.0,
        scenario_total_fte=20.0,
        scenario_qualifying_count=10.0,
    )
    rendered = _render(data).lower()
    assert "cannot perform the supervisory/indirect exclusion" in rendered
    assert "approximation" in rendered
    # The FLAT HOURS-mode "excluded from the ODLH computation" claim (as if
    # the exclusion were actually performed) must NEVER render in FTE mode --
    # a flat "excluded" line here would be false (audit MAJOR).
    assert "supervisory and indirect hours are excluded from the odlh computation entirely" not in rendered


# --- Framing: never a determination, UNVERIFIED-supply, no ramp, PLDLH context -


def test_computed_render_carries_all_standing_framing_notes() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=750.0,
        baseline_total_hours=1000.0,
        scenario_total_hours=200.0,
        scenario_qualifying_count=100.0,
    )
    rendered = _render(data).lower()
    assert "planning indicator" in rendered
    assert "never an official odlh compliance determination" in rendered
    assert "(a)(2)" in rendered
    assert "unverified supply" in rendered
    assert "end-state delta" in rendered
    assert "pldlh" in rendered or "edlh" in rendered
    assert "75%" in rendered


def test_agency_scale_counts_render_thousands_separated_never_scientific() -> None:
    # Agency-wide direct labor hours are routinely in the millions; a raw
    # count must render "2,000,000", never Python's :g sci-notation "2e+06"
    # (adversarial-verify finding, reproduced live before the fix).
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=1_500_000.0,
        baseline_total_hours=2_000_000.0,
        scenario_total_hours=250_000.0,
        scenario_qualifying_share=0.8,
    )
    rendered = _render(data)
    assert "2,000,000" in rendered
    assert "1,500,000" in rendered
    assert "250,000" in rendered
    assert "e+06" not in rendered
    assert "e+05" not in rendered


def test_fractional_fte_counts_keep_one_decimal_place() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.FTE,
        baseline_code_01=25.0,
        baseline_code_02=75.5,
        scenario_total_fte=10.0,
        scenario_qualifying_share=0.8,
    )
    rendered = _render(data)
    assert "75.5" in rendered


def test_cannot_compute_render_has_no_fabricated_number() -> None:
    data = StaffingWhatIfInput(mode=WhatIfMode.HOURS)
    rendered = _render(data).lower()
    assert "cannot compute" in rendered
    # No computed baseline/scenario/delta figure is fabricated on a partial
    # entry -- only the STANDING policy caveats (e.g. the constant "75%"
    # floor mentioned in the PLDLH context note) render, never a "pp" delta
    # marker or the baseline/scenario result lines themselves.
    assert "baseline (observed)" not in rendered
    assert "scenario (baseline + addition)" not in rendered
    assert "delta:" not in rendered


# --- Guarded vocabulary (packet-not-score) --------------------------------------


def test_no_score_or_directive_vocabulary_computed() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=750.0,
        baseline_total_hours=1000.0,
        scenario_total_hours=200.0,
        scenario_qualifying_count=100.0,
    )
    rendered = _render(data).lower()
    for forbidden in ("score", "pwin", "/100", "bid/no-bid", "pursue", "call "):
        assert forbidden not in rendered


def test_no_score_or_directive_vocabulary_cannot_compute() -> None:
    rendered = _render(StaffingWhatIfInput(mode=WhatIfMode.FTE)).lower()
    for forbidden in ("score", "pwin", "/100", "bid/no-bid", "pursue", "call "):
        assert forbidden not in rendered


# --- Rounding: one decimal, no spurious precision -------------------------------


def test_rounding_is_one_decimal_no_spurious_precision() -> None:
    data = StaffingWhatIfInput(
        mode=WhatIfMode.HOURS,
        baseline_qualifying_hours=1.0,
        baseline_total_hours=3.0,  # 33.333...%
        scenario_total_hours=3.0,
        scenario_qualifying_count=1.0,
    )
    rendered = _render(data)
    assert "33.3%" in rendered
    assert "33.33333" not in rendered
    assert "33.333333333333336%" not in rendered
