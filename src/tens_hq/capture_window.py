"""Capture-window band for the cited Opportunity Packet (roadmap spine: N6 ->
Contract Facts -> **Capture Window** -> R2b).

Given a contract's live **potential period end date** (USAspending
``ContractFactsRecord.period_potential_end_date``) and ``as_of`` ("today"),
estimate an honest BAND for when the follow-on solicitation is likely to post,
and, from that, a BAND for when an R2a Procurement-List addition should be
started to beat it.

The domain crux (roadmap SS4.2): a follow-on solicitation typically posts
**6-12+ months BEFORE** the contract's potential end date, not at the end date
itself. Anchoring runway to the end date overstates it by that lead time. This
module therefore:

* Anchors every estimate to the SOLICITATION clock, never the contract end
  date, and says so in the render.
* Never emits a single-value runway, score, rank, percent, or "you have N
  days" point estimate -- everything is a date-range BAND (N1).
* Treats its lead-time assumptions as effective-dated planning defaults (N5):
  the procurement-lead band (6-12 months) and the R2a Procurement-List-
  addition lead band (9-12 months) are OWNER-ATTESTED methodology defaults
  (ADR-020, 2026-07-21; supersedes ADR-015's original provisional 6-month
  point value) -- confirmed by the pilot NPA's compliance coordinator as reasonable
  generic planning bands, never as a specific program's or CNA's own
  negotiated lead time for a particular contract, which the render still
  directs the analyst to confirm.
* Parses ``period_potential_end_date`` SAFELY: it is a RAW string that may
  carry a trailing time-of-day suffix (e.g. ``" 00:00:00"``) and may be blank
  or garbled. An unparseable/missing date renders an honest "capture window
  unknown" line -- never a crash, never a fabricated window (AGENTS #13).
* Renders a band that has already fully passed as PASSED, plainly, rather than
  hiding a negative runway (roadmap SS4.2).
* Never determines eligibility, competability, or a pursue/no-pursue verdict
  (AGENTS #8): this is planning context for a human to confirm.

This module is pure (no Streamlit, no network, no case-store imports) and
deterministic: callers supply ``as_of`` explicitly; nothing here calls
``date.today()``.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from enum import Enum

# Average month length used ONLY to express a date band as an approximate
# "months from today" range for display. The band bounds themselves are
# computed with calendar-correct month arithmetic (see ``_shift_months``); this
# constant never drives a date computation, only rounded display text.
_APPROX_DAYS_PER_MONTH = 30.44


class CaptureWindowState(str, Enum):
    """Whether a usable capture-window band could be estimated."""

    UNKNOWN = "UNKNOWN"
    ESTIMATED = "ESTIMATED"


class BandStatus(str, Enum):
    """A date band's relationship to ``as_of`` -- never hidden (roadmap SS4.2)."""

    UPCOMING = "UPCOMING"
    CURRENT = "CURRENT"
    PASSED = "PASSED"


@dataclass(frozen=True, slots=True)
class DateBand:
    """An honest date range. Never reduced to a single point (N1)."""

    start: date
    end: date

    def status(self, as_of: date) -> BandStatus:
        if as_of < self.start:
            return BandStatus.UPCOMING
        if as_of > self.end:
            return BandStatus.PASSED
        return BandStatus.CURRENT

    def months_from(self, as_of: date) -> tuple[float, float]:
        """Approx (start, end) months-from-``as_of``, rounded for display.

        Negative values are expected and intentional when the band is in the
        past relative to ``as_of`` -- a negative runway is honest, not hidden.
        """

        return (
            round((self.start - as_of).days / _APPROX_DAYS_PER_MONTH, 1),
            round((self.end - as_of).days / _APPROX_DAYS_PER_MONTH, 1),
        )


@dataclass(frozen=True, slots=True)
class CaptureWindowPolicy:
    """OWNER-ATTESTED, effective-dated procurement-lead-time defaults (N5, ADR-020).

    These are METHODOLOGY DEFAULTS attested by the pilot NPA's compliance coordinator
    (ADR-020, 2026-07-21) as reasonable generic planning bands -- not a
    specific agency's, program's, or Central Nonprofit Agency's (CNA's) own
    negotiated figure for a particular contract. ``proc_lead_min_months`` /
    ``proc_lead_max_months`` bound how many months before a contract's
    potential end date a follow-on solicitation typically posts (6-12,
    confirmed); ``pl_addition_lead_min_months`` / ``pl_addition_lead_max_months``
    bound the assumed lead time an R2a Procurement-List addition needs to
    start ahead of that solicitation window (9-12 months, confirmed;
    supersedes ADR-015's original provisional single-point 6-month value --
    see ADR-015's 2026-07-21 Update). ``effective_date`` records when this
    default took effect so a rendered band can be reproduced and audited. The
    render still directs the analyst to confirm the real, program-specific
    lead time with their own CNA/program before relying on this for a
    particular contract; the two counsel-gated items (C3 and C4, named in
    ADR-020) are unrelated to this policy and stay [VERIFY] wherever they
    appear.
    """

    proc_lead_min_months: int
    proc_lead_max_months: int
    pl_addition_lead_min_months: int
    pl_addition_lead_max_months: int
    effective_date: str

    def __post_init__(self) -> None:
        if self.proc_lead_min_months <= 0 or self.proc_lead_max_months <= 0:
            raise ValueError("capture-window lead months must be positive")
        if self.proc_lead_min_months >= self.proc_lead_max_months:
            raise ValueError("proc_lead_min_months must be less than proc_lead_max_months")
        if self.pl_addition_lead_min_months <= 0 or self.pl_addition_lead_max_months <= 0:
            raise ValueError("pl-addition-lead months must be positive")
        if self.pl_addition_lead_min_months >= self.pl_addition_lead_max_months:
            raise ValueError(
                "pl_addition_lead_min_months must be less than pl_addition_lead_max_months"
            )
        try:
            date.fromisoformat(self.effective_date)
        except (TypeError, ValueError) as exc:
            raise ValueError("capture-window policy effective_date must be an ISO date") from exc


# OWNER-ATTESTED planning defaults (ADR-020, 2026-07-21) -- methodology
# assumptions confirmed by the pilot NPA's compliance coordinator as reasonable generic
# bands, NOT this program's or CNA's own confirmed lead time for a particular
# contract. Supersedes the ADR-015-original provisional pl_addition_lead_months=6
# point value with an owner-attested 9-12 month band; see ADR-015's 2026-07-21
# Update.
DEFAULT_CAPTURE_WINDOW_POLICY = CaptureWindowPolicy(
    proc_lead_min_months=6,
    proc_lead_max_months=12,
    pl_addition_lead_min_months=9,
    pl_addition_lead_max_months=12,
    effective_date="2026-07-21",
)


@dataclass(frozen=True, slots=True)
class CaptureWindowBand:
    """One capture-window assessment for a single contract's potential end date."""

    raw_potential_end_date: str | None
    as_of: date
    state: CaptureWindowState
    policy: CaptureWindowPolicy
    potential_end_date: date | None = None
    solicitation_window: DateBand | None = None
    r2a_start_by_window: DateBand | None = None


def _parse_potential_end_date(raw: str | None) -> date | None:
    """Safely parse a RAW USAspending potential-end-date string.

    The source value may be blank, ``None``, carry a trailing time-of-day
    suffix (space- or ``T``-separated, e.g. ``"2028-05-31 00:00:00"``), or be
    otherwise garbled. This never raises: an unparseable or missing value
    returns ``None`` so the caller can render an honest "unknown" band instead
    of crashing or fabricating a window.
    """

    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    date_part = text.split("T", 1)[0].split(" ", 1)[0]
    try:
        return date.fromisoformat(date_part)
    except ValueError:
        return None


def _shift_months(value: date, months: int) -> date:
    """Shift ``value`` back by ``months`` calendar months (day-of-month clamped).

    Dependency-free calendar-correct month arithmetic (stdlib ``calendar``
    only): e.g. 2028-05-31 shifted back 6 months is 2027-11-30 (November has
    no 31st, so the day clamps to the month's last day).
    """

    total = value.year * 12 + (value.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def assess_capture_window(
    potential_end_date_raw: str | None,
    as_of: date,
    *,
    policy: CaptureWindowPolicy = DEFAULT_CAPTURE_WINDOW_POLICY,
) -> CaptureWindowBand:
    """Estimate the capture-window band from a raw potential-end-date string.

    Pure and deterministic: ``as_of`` is always the caller-supplied "today",
    never ``date.today()``. An unparseable or missing ``potential_end_date_raw``
    returns an ``UNKNOWN`` band rather than raising or fabricating a window.
    """

    potential_end = _parse_potential_end_date(potential_end_date_raw)
    if potential_end is None:
        return CaptureWindowBand(
            raw_potential_end_date=potential_end_date_raw,
            as_of=as_of,
            state=CaptureWindowState.UNKNOWN,
            policy=policy,
        )

    solicitation_window = DateBand(
        start=_shift_months(potential_end, policy.proc_lead_max_months),
        end=_shift_months(potential_end, policy.proc_lead_min_months),
    )
    # The R2a start-by band WIDENS relative to the solicitation window: its
    # earlier bound (start) shifts back by the LONGER pl-addition lead
    # (pl_addition_lead_max_months), and its later bound (end) shifts back by
    # the SHORTER lead (pl_addition_lead_min_months) -- composing a band with
    # a band, rather than a single point, honestly widens the result instead
    # of narrowing it (ADR-020).
    r2a_start_by_window = DateBand(
        start=_shift_months(solicitation_window.start, policy.pl_addition_lead_max_months),
        end=_shift_months(solicitation_window.end, policy.pl_addition_lead_min_months),
    )
    return CaptureWindowBand(
        raw_potential_end_date=potential_end_date_raw,
        as_of=as_of,
        state=CaptureWindowState.ESTIMATED,
        policy=policy,
        potential_end_date=potential_end,
        solicitation_window=solicitation_window,
        r2a_start_by_window=r2a_start_by_window,
    )


# --- Rendering ---------------------------------------------------------------
#
# Caveat-first: the attested-methodology/effective-date, anchor-to-solicitation,
# and never-a-determination statements always precede any date, so a band can
# never be read in isolation as a confirmed deadline or a verdict.

CAPTURE_WINDOW_HEADER = "## Capture window (estimated solicitation + R2a start-by band)"

CAPTURE_WINDOW_ANCHOR_NOTE = (
    "Anchored to the estimated FOLLOW-ON SOLICITATION date, NOT the contract's "
    "potential period end date. A follow-on solicitation typically posts months "
    "BEFORE the contract ends; treating the end date itself as the deadline "
    "overstates the real runway."
)

CAPTURE_WINDOW_NEVER_DETERMINATION = (
    "This is planning context, never a determination or a pursue-or-not "
    "recommendation — the human decides."
)

CAPTURE_WINDOW_UNKNOWN = (
    "Capture window unknown — no usable potential period end date is "
    "available to estimate a solicitation window."
)


def _methodology_note(policy: CaptureWindowPolicy) -> str:
    # OWNER-ATTESTED describes the band's epistemic status (a generic
    # methodology default the product owner attested, ADR-020) -- it is still
    # NOT a specific program's or CNA's confirmed figure for a particular
    # contract, which is why the confirm-with-your-CNA guidance stays.
    return (
        f"OWNER-ATTESTED planning defaults (generic methodology band, effective "
        f"{policy.effective_date}, ADR-020), NOT this program's or Central Nonprofit "
        "Agency's confirmed lead times for a particular contract: an "
        f"estimated procurement lead time of {policy.proc_lead_min_months}–"
        f"{policy.proc_lead_max_months} months before the potential end date, and an "
        f"attested {policy.pl_addition_lead_min_months}–{policy.pl_addition_lead_max_months}-month "
        "R2a Procurement-List-addition lead time. Confirm the real lead times with your "
        "CNA / program before relying on this."
    )


def _months_num(months: float) -> str:
    # Normalize signed zero so a near-boundary value prints "0", not "-0".
    return f"{(months if months != 0 else 0.0):g}"


def _band_range_text(band: DateBand, as_of: date) -> str:
    start_months, end_months = band.months_from(as_of)
    # "to" (not an en-dash) keeps a negative/past range readable, e.g.
    # "-88.5 to -83.1 months from today" instead of a "-88.5–-83.1" collision.
    return (
        f"{band.start.isoformat()} to {band.end.isoformat()} "
        f"(approx. {_months_num(start_months)} to {_months_num(end_months)} months from today)"
    )


def _status_note(label: str, band: DateBand, as_of: date) -> str | None:
    status = band.status(as_of)
    if status is BandStatus.PASSED:
        # A neutral timing FACT only -- no pursue/teaming/route recommendation
        # (this surface never makes a determination; the human decides).
        return (
            f"The estimated {label} window has already elapsed as of today "
            "(the runway shown is negative)."
        )
    if status is BandStatus.CURRENT:
        return f"Today falls inside the estimated {label} window."
    return None


def capture_window_lines(band: CaptureWindowBand) -> list[str]:
    """Render the capture-window band as caveat-first Markdown lines (pure)."""

    lines: list[str] = [
        CAPTURE_WINDOW_HEADER,
        "",
        f"- {CAPTURE_WINDOW_ANCHOR_NOTE}",
        f"- {_methodology_note(band.policy)}",
        f"- {CAPTURE_WINDOW_NEVER_DETERMINATION}",
        "",
    ]
    if band.state is CaptureWindowState.UNKNOWN:
        lines.append(f"- {CAPTURE_WINDOW_UNKNOWN}")
        lines.append("")
        return lines

    assert band.potential_end_date is not None
    assert band.solicitation_window is not None
    assert band.r2a_start_by_window is not None

    lines.append(f"- Potential period end date: {band.potential_end_date.isoformat()}")
    lines.append(
        "- Estimated follow-on solicitation window: "
        f"{_band_range_text(band.solicitation_window, band.as_of)}"
    )
    sol_note = _status_note("solicitation", band.solicitation_window, band.as_of)
    if sol_note:
        lines.append(f"- {sol_note}")
    lines.append(
        "- R2a Procurement-List-addition start-by band: "
        f"{_band_range_text(band.r2a_start_by_window, band.as_of)}"
    )
    r2a_note = _status_note("R2a start-by", band.r2a_start_by_window, band.as_of)
    if r2a_note:
        lines.append(f"- {r2a_note}")
    lines.append("")
    return lines


__all__ = [
    "CAPTURE_WINDOW_ANCHOR_NOTE",
    "CAPTURE_WINDOW_HEADER",
    "CAPTURE_WINDOW_NEVER_DETERMINATION",
    "CAPTURE_WINDOW_UNKNOWN",
    "DEFAULT_CAPTURE_WINDOW_POLICY",
    "BandStatus",
    "CaptureWindowBand",
    "CaptureWindowPolicy",
    "CaptureWindowState",
    "DateBand",
    "assess_capture_window",
    "capture_window_lines",
]
