# ADR-015: The Capture Window is an honest BAND anchored to the solicitation, never the contract end date

## Status

Accepted for the A1 Capture Window slice

## Date

2026-07-19

## Context

The Opportunity Packet's roadmap spine runs Eligibility Gate -> Contract Facts
-> **Capture Window** -> R2b. Given a contract's live **potential period end
date** (`ContractFactsRecord.period_potential_end_date`, ADR-014) and the
packet's `as_of`, an analyst needs to know roughly when a follow-on
solicitation is likely to post and how much runway remains to begin an R2a
Procurement-List addition.

This is easy to overstate. A follow-on solicitation typically posts
**6-12+ months BEFORE** the contract's potential end date, not at the end date
itself; a naive "months until the end date" calculation therefore overstates
the real runway by that lead time. The lead times themselves (how far before
end date a solicitation posts; how long an R2a Procurement-List addition takes
to prepare) are not a number this codebase owns -- they vary by CNA and
program and are not present in USAspending data. AGENTS.md #10 requires a
version change, test vectors, and a decision record for a material formula
change; #13 requires that unknown or partial evidence never becomes zero or
positive evidence; invariant N1 prohibits a numeric rating. ADR-014 also
established that `period_potential_end_date` is a RAW string (may carry a
`" 00:00:00"` suffix, may be blank or garbled) and deliberately deferred strict
date parsing.

## Decision

Add a pure `capture_window.py` module and a caveat-first render, integrated
into the existing Opportunity Packet builder with **no new keyword-only
parameter** -- it derives entirely from the `contract_facts` and `as_of`
parameters the builder already accepts.

1. **Extend ADR-014's string-only stance to a safe, best-effort date parse,
   scoped to this module only.** ADR-014 decision #6 deliberately kept
   `period_potential_end_date` a display string and declined to strict-parse
   it. Estimating a capture window requires date arithmetic, so this slice
   adds a narrow, non-raising parser: strip a trailing `" 00:00:00"` or
   `"T..."` time-of-day suffix, then `date.fromisoformat` the remainder. A
   missing, blank, or garbled value returns `None` rather than raising, and the
   render then states "capture window unknown" -- never a crash, never a
   fabricated window (AGENTS #13). The Contract Facts display itself is
   unchanged and still never strict-parses the raw string.

2. **Anchor every band to the solicitation clock, not the contract end date,
   and say so in the render.** `est_solicitation_window = [potential_end -
   PROC_LEAD_MAX, potential_end - PROC_LEAD_MIN]`; the R2a start-by band is
   that window shifted back by `PL_ADDITION_LEAD`. The render's first
   substantive line states this anchoring explicitly so the contract's end
   date is never mistaken for the deadline.

3. **Every quantity is a BAND, never a point (N1).** Both the estimated
   solicitation window and the R2a start-by window render as date-range pairs
   plus an approximate "months from today" range; there is no single-value
   runway, score, rank, percent, or "you have N days" estimate anywhere on
   this surface.

4. **Provisional, effective-dated lead-time constants (N5), never presented as
   an agency's or CNA's confirmed figures.** A `CaptureWindowPolicy` frozen
   dataclass (`proc_lead_min_months=6`, `proc_lead_max_months=12`,
   `pl_addition_lead_months=6`, `effective_date="2026-07-19"` --
   **superseded 2026-07-21 by ADR-020's owner attestation; the single
   `pl_addition_lead_months=6` point value is now a
   `pl_addition_lead_min_months=9` / `pl_addition_lead_max_months=12` band,
   `effective_date="2026-07-21"`; see the Update below**) mirrors the
   validated, effective-dated shape of `case_store.FreshnessPolicy`. The
   render's second line states these are PROVISIONAL methodology defaults and
   directs the analyst to confirm the real lead times with their CNA/program.
   **[VERIFY] owed by the owner:** the real PL-addition lead time, the real
   procurement-lead-time band for the agency, and whether to adjust the
   potential-end date for observed option-exercise behavior were all real
   numbers this slice did not have. **The PL-addition lead and the
   procurement-lead band were subsequently attested by the owner (ADR-020,
   2026-07-21, see the Update below); whether to adjust for observed
   option-exercise behavior remains a genuinely open [VERIFY].**

5. **Calendar-correct, dependency-free month arithmetic.** Shifting a date
   back N calendar months is done with stdlib `calendar.monthrange` (year/month
   carried via `divmod`, day clamped to the shifted month's length -- e.g.
   2028-05-31 minus 6 months is 2027-11-30, since November has no 31st; the
   `6` here is the still-current, unchanged `proc_lead_min_months` figure --
   it is not affected by the `pl_addition_lead` band the 2026-07-21 Update
   below introduces). No new dependency (no `python-dateutil`) is added. A
   separate, coarser
   days-per-month constant is used ONLY to express a band as an approximate
   "months from today" range for display; it never drives the date bounds
   themselves.

6. **A past window is rendered honestly, never hidden or omitted.** Each band
   independently compares itself to `as_of` (`UPCOMING` / `CURRENT` /
   `PASSED`) and states the result in the render. A negative runway (the
   estimated window's later bound is already before `as_of`) renders "the
   likely ... window has already passed as of today -- pursue as a teammate
   this cycle, R2a next," consistent with roadmap SS4.2. Because the two bands
   are checked independently, the R2a start-by window can (and, close to a
   contract's end, often will) read PASSED while the solicitation window is
   still CURRENT or UPCOMING -- a genuinely useful and honest signal that
   R2a prep should have already started even though the solicitation itself
   has not yet posted.

7. **Deterministic; no `date.today()` inside the module.** `as_of` is always
   caller-supplied (the builder's existing `as_of` parameter, converted to a
   `date`), matching the pattern already established for the rest of the
   packet.

8. **Section placement and omission mirror the Eligibility Gate precedent.**
   The section renders only when `contract_facts` is supplied (there is
   nothing to compute from otherwise) and appears between the analyst-entered
   Contract Facts block and the Geography context panel. Unlike the
   Eligibility Gate's blank-input UNKNOWN, an *unparseable/missing date within
   an attached `contract_facts` record* still renders the section -- as the
   honest "unknown" state -- rather than disappearing, so a garbled or absent
   live date is never silently swallowed.

## Alternatives considered

- **Compute a single "months of runway" number:** rejected; violates N1 and
  manufactures false precision out of two provisional lead-time assumptions.
- **Anchor the runway to the contract's potential end date:** rejected; this
  is the exact overstatement the roadmap identifies (a follow-on solicitation
  posts months before the end date, not at it).
- **Add `python-dateutil` for month arithmetic:** rejected; a dependency-free
  `calendar.monthrange`-based shift is sufficient and the constraint is no new
  runtime dependencies.
- **Strict-parse `period_potential_end_date` everywhere (amend ADR-014):**
  rejected; ADR-014's display-string stance for Contract Facts is unchanged.
  Only this module adds a narrow, non-raising, module-local parse for its own
  arithmetic.
- **Omit the section on an unparseable/missing date (treat it like "no
  contract_facts"):** rejected; a live record that resolved but carries a bad
  or absent potential-end date is itself evidence worth surfacing honestly
  ("capture window unknown"), not silence that could be misread as "nothing to
  report."
- **Hide or omit a past-window result:** rejected; a negative runway is
  planning-relevant information (roadmap SS4.2) and hiding it would be the
  kind of quiet overclaim this codebase's honesty invariants exist to prevent.
- **Store precomputed `passed`/`current` booleans on the result dataclass:**
  rejected in favor of a `DateBand.status(as_of)` method, so there is one
  source of truth for a band's bounds and no risk of a stored flag drifting
  out of sync with them.

## Consequences

- The Capture Window section only ever appears when live Contract Facts are
  attached; the analyst-entered-only packet path is unchanged.
- The lead-time constants -- originally provisional (6/12/6 months, effective
  2026-07-19) -- are now OWNER-ATTESTED methodology defaults (proc-lead 6-12
  months, PL-addition-lead 9-12 months, effective 2026-07-21; ADR-020, see
  the Update below): the pilot NPA's compliance coordinator confirmed both bands as
  reasonable generic planning figures. They remain generic methodology
  defaults, not this specific program's or CNA's own negotiated figure for a
  particular contract, and the render still directs the analyst to confirm
  the real, contract-specific lead time with their CNA/program. A live
  SAM.gov solicitation-date lookup, option-exercise behavior modeling, and
  any score/point estimate remain explicitly deferred future work.
- No score, rank, tier, or bid/no-bid output is introduced; the section is
  planning context for a human to confirm, exactly like the rest of the
  packet.
- Automated coverage remains fully offline and deterministic: every band is
  computed from an explicit `as_of`, with test vectors for round-number
  band math, calendar day-clamping, unknown/garbled dates, and independent
  past/current/upcoming status on both bands.

## Update (2026-07-21): PL-addition lead becomes an owner-attested 9-12 month band

ADR-020 records the pilot NPA compliance coordinator's 2026-07-21 attestation
of real domain constants, including the PL-addition lead time and the
procurement-lead band this module has carried as provisional defaults since
2026-07-19. This is an EXTENSION of this ADR's design, not a reversal: the
policy stays a validated, effective-dated dataclass (decision #4); only its
values and their epistemic status change.

1. **`pl_addition_lead_months` (a single point value, default 6) is replaced
   by a band:** `pl_addition_lead_min_months=9` / `pl_addition_lead_max_months=12`,
   with the same positive/non-inverted validation `proc_lead_min_months` /
   `proc_lead_max_months` already had. `proc_lead_min_months=6` /
   `proc_lead_max_months=12` are unchanged in value but change in status --
   from provisional to owner-confirmed. `DEFAULT_CAPTURE_WINDOW_POLICY`'s
   `effective_date` moves to `"2026-07-21"`.
2. **The R2a start-by band composition WIDENS, not narrows.** Composing a
   band (the solicitation window) with another band (the pl-addition lead)
   correctly produces a WIDER result than composing a band with a single
   point did: the start-by window's earlier bound (`start`) shifts back by
   the LONGER lead (`pl_addition_lead_max_months`, 12), and its later bound
   (`end`) shifts back by the SHORTER lead (`pl_addition_lead_min_months`,
   9). Narrowing (the reverse pairing) would silently manufacture false
   precision out of two independently uncertain quantities -- the same
   honesty failure mode N1 already guards against for a single-point runway.
3. **The rendered caveat's status changes, but not its practical guidance.**
   The docstrings and this ADR's language move from "PROVISIONAL... the real
   numbers are owed by the owner" to "OWNER-ATTESTED (ADR-020)... generic
   methodology defaults, confirmed by the pilot NPA's compliance coordinator as
   reasonable planning bands." The rendered `_provisional_note` caveat
   itself is UNCHANGED in substance (still "PROVISIONAL planning defaults...
   NOT this program's or Central Nonprofit Agency's confirmed lead times...
   confirm the real lead times with your CNA / program"), because an
   owner-attested GENERIC band is still not a specific program's or CNA's
   own negotiated figure for a particular contract -- those two claims are
   not the same thing, and only the source-code commentary describing the
   band's PROVENANCE needed to change.
4. **Option-exercise behavior modeling remains a genuinely open [VERIFY].**
   ADR-020 did not attest an adjustment for observed option-exercise
   behavior; that item stays deferred future work, unchanged by this Update.

### Update 2026-07-21 (second, same day): the rendered caveat DID then change

Decision 3 above is superseded in one respect by a same-day
adversarial-verification fix pass, applied hours after this Update was written: all
three review lenses converged on the PROVISIONAL-vs-attested contradiction,
and the rendered caveat now leads "OWNER-ATTESTED planning defaults (generic
methodology band, effective 2026-07-21, ADR-020)" -- the word PROVISIONAL no
longer renders anywhere. The function was renamed `_provisional_note` ->
`_methodology_note`. Decision 3's practical-guidance half still stands
unchanged: the render keeps "NOT this program's or Central Nonprofit Agency's
confirmed lead times for a particular contract" and the confirm-with-your-CNA
guidance, because an owner-attested generic band is still not a
program-specific negotiated figure.

See ADR-020 for the full attested-constants record (including the two
counsel-gated items, C3/C4, which are unrelated to this module and must not
be inferred from anything in this Update).
