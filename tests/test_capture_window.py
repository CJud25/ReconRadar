"""Offline unit tests for the Capture Window band (roadmap SS4.2, ADR-015).

Covers: safe date parsing (missing/garbled -> honest unknown, never a crash),
calendar-correct month-shift arithmetic, the caveat-first band render (never a
single-point runway, provisional/effective-dated constants, anchored to the
solicitation clock not the contract end date), and honest past-window
handling. Deterministic: every assessment is driven by an explicit ``as_of``;
nothing here relies on the real clock.
"""

from __future__ import annotations

from datetime import date

import pytest

from tens_hq.capture_window import (
    BandStatus,
    CaptureWindowPolicy,
    CaptureWindowState,
    DateBand,
    assess_capture_window,
    capture_window_lines,
)

_POLICY = CaptureWindowPolicy(
    proc_lead_min_months=6,
    proc_lead_max_months=12,
    pl_addition_lead_min_months=9,
    pl_addition_lead_max_months=12,
    effective_date="2026-07-19",
)


def _render(raw: str | None, as_of: date, policy: CaptureWindowPolicy = _POLICY) -> str:
    band = assess_capture_window(raw, as_of, policy=policy)
    return "\n".join(capture_window_lines(band))


# --- Safe date parsing --------------------------------------------------------


def test_missing_or_blank_potential_end_is_unknown_not_a_crash() -> None:
    for raw in (None, "", "   "):
        band = assess_capture_window(raw, date(2026, 7, 19), policy=_POLICY)
        assert band.state is CaptureWindowState.UNKNOWN
        assert band.potential_end_date is None
        rendered = "\n".join(capture_window_lines(band))
        assert "capture window unknown" in rendered.casefold()


def test_garbled_potential_end_is_unknown_not_a_crash() -> None:
    for raw in ("not-a-date", "TBD", "2026-13-40", "never"):
        band = assess_capture_window(raw, date(2026, 7, 19), policy=_POLICY)
        assert band.state is CaptureWindowState.UNKNOWN
        rendered = "\n".join(capture_window_lines(band))
        assert "capture window unknown" in rendered.casefold()


def test_time_of_day_suffix_is_stripped_safely() -> None:
    # The live USAspending field may carry a " 00:00:00" (or "T"-separated) suffix.
    for raw in ("2028-05-31 00:00:00", "2028-05-31T00:00:00"):
        band = assess_capture_window(raw, date(2026, 7, 19), policy=_POLICY)
        assert band.state is CaptureWindowState.ESTIMATED
        assert band.potential_end_date == date(2028, 5, 31)


# --- Calendar-correct month arithmetic ----------------------------------------


def test_month_shift_clamps_day_of_month() -> None:
    # May 31 minus 6 months has no 31st in November, so the day clamps to 30;
    # minus 12 months lands on May 31 the prior year with no clamping needed.
    # Exercised through the public API (band math), not a private helper.
    band = assess_capture_window("2028-05-31", date(2026, 7, 19), policy=_POLICY)
    assert band.solicitation_window == DateBand(start=date(2027, 5, 31), end=date(2027, 11, 30))


def test_date_band_status_upcoming_current_passed() -> None:
    band = DateBand(start=date(2026, 1, 1), end=date(2026, 7, 1))
    assert band.status(date(2025, 12, 1)) is BandStatus.UPCOMING
    assert band.status(date(2026, 3, 1)) is BandStatus.CURRENT
    assert band.status(date(2026, 1, 1)) is BandStatus.CURRENT  # inclusive start
    assert band.status(date(2026, 7, 1)) is BandStatus.CURRENT  # inclusive end
    assert band.status(date(2026, 7, 2)) is BandStatus.PASSED


# --- Band math (exact, using round dates so the arithmetic is hand-checkable) -


def test_band_math_matches_the_roadmap_formula() -> None:
    # potential_end = 2027-01-01; policy = proc min6/max12, pl-addition min9/max12
    # (all round months).
    band = assess_capture_window("2027-01-01", date(2026, 1, 1), policy=_POLICY)
    assert band.state is CaptureWindowState.ESTIMATED
    # solicitation window = [potential_end - 12mo, potential_end - 6mo]
    assert band.solicitation_window == DateBand(start=date(2026, 1, 1), end=date(2026, 7, 1))
    # r2a start-by WIDENS relative to the solicitation window: start shifts
    # back by the longer pl-addition lead (12mo), end shifts back by the
    # shorter one (9mo).
    assert band.r2a_start_by_window == DateBand(start=date(2025, 1, 1), end=date(2025, 10, 1))


# --- Honesty invariants on the render -----------------------------------------


def test_render_is_a_band_never_a_single_point() -> None:
    rendered = _render("2028-05-31 00:00:00", date(2026, 7, 19))
    # Solicitation window = [potential_end - 12mo, potential_end - 6mo].
    assert "2027-05-31" in rendered
    assert "2027-11-30" in rendered
    assert " to " in rendered  # date ranges, not single dates
    assert "months from today" in rendered


def test_render_contains_no_numeric_rating_or_bid_decision_language() -> None:
    for raw in (None, "garbled", "2028-05-31 00:00:00", "2019-03-20"):
        rendered = _render(raw, date(2026, 7, 19)).casefold()
        assert "score" not in rendered
        assert "pwin" not in rendered
        assert "/100" not in rendered
        assert "bid/no-bid" not in rendered


def test_render_states_attested_constants_with_effective_date() -> None:
    rendered = _render("2028-05-31 00:00:00", date(2026, 7, 19))
    # The band's epistemic status is owner-attested (ADR-020) -- but it is a
    # generic methodology band, so the render must still say it is NOT a
    # program/CNA-confirmed figure and direct the analyst to confirm.
    assert "OWNER-ATTESTED" in rendered
    assert "ADR-020" in rendered
    assert "PROVISIONAL" not in rendered
    assert "NOT this program's or Central Nonprofit" in rendered
    assert "2026-07-19" in rendered  # the policy's effective date
    assert "confirm the real lead times" in rendered.casefold()
    assert "cna" in rendered.casefold() or "program" in rendered.casefold()


def test_render_is_anchored_to_solicitation_not_end_date() -> None:
    rendered = _render("2028-05-31 00:00:00", date(2026, 7, 19))
    assert "solicitation" in rendered.casefold()
    assert "not the contract's potential period end date" in rendered.casefold()


def test_render_never_a_determination() -> None:
    rendered = _render("2028-05-31 00:00:00", date(2026, 7, 19))
    assert "never a determination" in rendered.casefold()
    assert "the human decides" in rendered.casefold()


def test_past_window_is_honest_not_hidden() -> None:
    # potential_end is 2019-03-20; as_of is 2026-07-19 -- years past the
    # entire estimated window. Negative runway must be stated, not omitted.
    rendered = _render("2019-03-20", date(2026, 7, 19))
    assert "already elapsed" in rendered.casefold()
    # The past-window note is a neutral timing FACT: it must NOT recommend a
    # capture route. (The standing "pursue-or-not recommendation" disclaimer is
    # fine; the removed directive was the specific teaming/"R2a next" verdict.)
    assert "as a teammate this cycle" not in rendered.casefold()
    assert "r2a next" not in rendered.casefold()


def test_r2a_start_by_can_be_past_while_solicitation_window_is_not() -> None:
    # solicitation window [2026-01-01, 2026-07-01] still contains as_of, but the
    # r2a start-by window [2025-07-01, 2026-01-01] has already elapsed. Both
    # facts must render honestly and independently.
    rendered = _render("2027-01-01", date(2026, 3, 1))
    assert "today falls inside the estimated solicitation window" in rendered.casefold()
    assert "the estimated r2a start-by window has already elapsed" in rendered.casefold()


def test_upcoming_window_states_no_status_caveat() -> None:
    rendered = _render("2030-01-01", date(2026, 1, 1))
    assert "already elapsed" not in rendered.casefold()
    assert "falls inside" not in rendered.casefold()


def test_deterministic_as_of_is_used_not_the_real_clock() -> None:
    # Two calls with the same as_of must produce byte-identical renders
    # regardless of when the test actually runs.
    first = _render("2028-05-31 00:00:00", date(2026, 7, 19))
    second = _render("2028-05-31 00:00:00", date(2026, 7, 19))
    assert first == second


# --- Provisional policy validation (N5 config-with-effective-date) -----------


def test_policy_rejects_non_positive_or_inverted_lead_months() -> None:
    with pytest.raises(ValueError):
        CaptureWindowPolicy(
            proc_lead_min_months=0, proc_lead_max_months=12,
            pl_addition_lead_min_months=9, pl_addition_lead_max_months=12,
            effective_date="2026-07-19",
        )
    with pytest.raises(ValueError):
        CaptureWindowPolicy(
            proc_lead_min_months=12, proc_lead_max_months=6,
            pl_addition_lead_min_months=9, pl_addition_lead_max_months=12,
            effective_date="2026-07-19",
        )
    # pl-addition-lead min<=0.
    with pytest.raises(ValueError):
        CaptureWindowPolicy(
            proc_lead_min_months=6, proc_lead_max_months=12,
            pl_addition_lead_min_months=0, pl_addition_lead_max_months=12,
            effective_date="2026-07-19",
        )
    # pl-addition-lead inverted (min >= max).
    with pytest.raises(ValueError):
        CaptureWindowPolicy(
            proc_lead_min_months=6, proc_lead_max_months=12,
            pl_addition_lead_min_months=12, pl_addition_lead_max_months=9,
            effective_date="2026-07-19",
        )


def test_policy_rejects_a_non_iso_effective_date() -> None:
    with pytest.raises(ValueError):
        CaptureWindowPolicy(
            proc_lead_min_months=6, proc_lead_max_months=12,
            pl_addition_lead_min_months=9, pl_addition_lead_max_months=12,
            effective_date="not-a-date",
        )
