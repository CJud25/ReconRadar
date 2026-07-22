# ADR-021: The Staffing what-if is an agency-wide ODLH planning indicator, never a determination

## Status

Accepted for the A6 Staffing-what-if slice

## Date

2026-07-21

## Context

The Opportunity Packet's roadmap spine has, so far, only ever computed
things FROM live or analyst-entered evidence ABOUT a specific contract
(Capture Window, Incumbent leads). A6 is different: it is the first packet
surface that computes a NUMBER from purely hypothetical analyst input --
"if we win this contract and staff it this way, what happens to our ODLH
ratio?" That is exactly the shape of computation AGENTS.md #4 exists to
guard: "Site ratios are labeled planning indicators. Do not describe them
as official ODLH compliance determinations." A ratio delta that LOOKS like
a compliance calculation, sitting inside a "cited evidence packet," could
easily be mistaken for one if it is not caveated as insistently as every
other number this codebase renders.

Two things make this slice tractable and honest at the same time:

1. The pilot NPA's compliance coordinator attested the real domain constants
   this computation needs on 2026-07-21 (ADR-020) -- the ODLH ratio
   definition, the supervisory/indirect exclusion, the two owner-observed
   entry shapes (hours-exact and FTE-approximate), and the PLDLH/EDLH
   per-project exception. Without that attestation this slice would have
   had to either guess at the ratio's real construction or ship nothing.
2. The what-if's INPUT is deliberately narrow: it consumes ONLY the numbers
   an analyst types on this packet tab (AGENTS #1) -- never the synthetic
   demo data, never `metrics.py`'s pandas pipeline, never the case store.
   Mirroring `metrics.safe_ratio`'s NaN-honesty *idiom* with a local copy
   (rather than importing the module) keeps that boundary structurally true,
   not just documented.

## Decision

Add a pure `staffing_whatif.py` module (mirrors `capture_window.py` /
`eligibility_gate.py` / `incumbent_leads.py`) with five load-bearing
choices, three of them PINNED by the brief with no SME discretion (the
audit-caught MAJORs/contract items).

1. **An explicit mode discriminator, never inferred.** `WhatIfMode.HOURS` /
   `WhatIfMode.FTE` travels with every `StaffingWhatIfInput`. The module
   REJECTS an input whose populated fields disagree with its declared mode
   (`REASON_MODE_DISAGREEMENT`) rather than silently ignoring the
   mismatched fields or guessing which mode was "really" meant. This
   matters specifically because Streamlit session state persists a
   widget's last value even when that widget isn't rendered this run: a UI
   mode toggle alone, without this check, could let a stale HOURS-mode
   number leak into an FTE-mode computation the moment the analyst
   switches modes. `bd_page.py`'s own wiring never actually triggers this
   path (its `if/else` branches construct a `StaffingWhatIfInput` with only
   the active mode's kwargs, leaving the other mode's fields at their
   dataclass default `None`) -- the check is a structural invariant the
   module enforces regardless of caller discipline, not a UI workaround.
2. **Scenario qualifying entry is share XOR count, fail-closed on both.**
   The scenario's qualifying portion of a staffing ADDITION is inherently a
   forward-looking assumption (you don't know in advance exactly who you'll
   hire), so it is entered as EITHER an assumed share (a fraction of the
   addition) OR an assumed count (exact hours/FTEs) -- never both, and
   never silently preferring one over the other. Supplying both returns the
   pinned message verbatim: "cannot compute — supply either an assumed
   qualifying share or a qualifying count, not both."
3. **Per-mode completeness gates every partial entry to an honest
   `CANNOT_COMPUTE`, never a fabricated number.** The BASELINE (the
   agency's current, analyst-entered state) must be exact and complete
   for its mode; the SCENARIO's total must be present and its qualifying
   portion resolved from share XOR count. Any gap -- including a zero
   denominator, a lone code-07 entry with no code-01/02, a negative or
   non-finite value, or a qualifying amount that would exceed its total --
   renders the honest partial-entry message. Nothing is ever clamped to fit.
4. **The supervisory/indirect-exclusion note is MODE-AWARE (audit MAJOR).**
   HOURS mode states the exclusion is PERFORMED ("enter DIRECT labor hours
   only — supervisory and indirect hours are excluded from the ODLH
   computation"). FTE mode states the exclusion CANNOT be performed by this
   entry mode at all: a headcount cannot separate one person's
   supervisory/indirect hours from their direct-labor hours, which is a
   core reason the FTE result is only an APPROXIMATION of the hours-based
   statutory ratio, never the ratio itself. A single mode-invariant
   "excluded" line would be FALSE in FTE mode, so the module renders two
   genuinely different sentences gated on `result.mode`, never one shared
   string.
5. **Ratio math sums numerator/denominator across baseline + addition,
   never averages** (AGENTS #5), via a local `_safe_ratio` copy that
   mirrors `metrics.safe_ratio`'s NaN-honesty idiom without importing the
   module (the same established anti-cross-boundary-import convention as
   `incumbent_leads.py` / `packet_export.py`'s local `_md` copies).
   Formula version `WHATIF-1.0` is carried on every result and always
   rendered (AGENTS #10).

Supporting UI change (`bd_page.py`): the mode toggle is a **checkbox**, not
a radio -- `test_app_runtime.py`'s page-navigation tests key off
`app.radio[0]` being the sidebar nav radio, and a second top-level radio
widget elsewhere in the app changes `AppTest`'s positional radio ordering
and silently breaks that assumption. A checkbox has no such collision and
matches this page's existing binary-toggle convention (the R2b/handoff
"use the bundled SYNTHETIC example" checkboxes). Every numeric input uses
`value=None` so "not yet typed" is distinguishable from "typed zero" --
the section computes and renders only once ANY baseline field is entered
(`baseline_entered`), tracking "was a baseline entered," never "did it
validate."

## What this slice deliberately does NOT do

- **No ramp curve.** Ramp timing is site-dependent (an incumbent-workforce
  transition ramps differently than greenfield hiring -- owner-attested,
  ADR-020) and is not modeled; this renders an END-STATE delta only.
  Modeling a specific ramp shape would require assumptions this codebase
  has no basis for and the owner did not attest to.
- **No per-project PLDLH/EDLH calculator.** The owner-attested PLDLH/EDLH
  exception (a per-project ratio may be Commission-approved below 75% while
  agency-wide ODLH holds) is rendered as CONTEXT only. Building an actual
  per-project calculator is out of scope for this slice -- it would need a
  project/product-family allocation model this codebase does not have and
  was not asked to build.
- **No supply claim.** The scenario's qualifying share/count is explicitly
  labeled an ANALYST ASSUMPTION about a workforce not yet hired --
  UNVERIFIED supply, never evidence that such workers are available,
  reachable, or willing (the same discipline `GEOGRAPHY_CONTEXT_DISCLAIMER`
  already holds for a county population statistic).
- **No blending with the synthetic side** (AGENTS #1). The module imports
  nothing from `synthetic.py`, `metrics.py`'s pandas pipeline, or the case
  store.

## Alternatives considered

- **Infer the entry mode from which fields are populated, rather than an
  explicit discriminator:** rejected; this is exactly the audit-pinned
  contract item -- inference would silently misclassify a stale-session-
  state partial entry instead of failing closed.
- **Let a share OR a count silently win when both are supplied (e.g. count
  takes precedence):** rejected; a silent precedence rule hides a genuine
  analyst mistake (they meant to clear one field and didn't) behind a
  plausible-looking number instead of surfacing it.
- **One mode-invariant supervisory/indirect-exclusion sentence, worded
  generically enough to "cover" both modes:** rejected (the audit MAJOR);
  any wording that reads as "excluded" in FTE mode is false, because FTE
  mode structurally cannot perform that exclusion at all.
- **Compute a ramp-adjusted or per-project figure anyway, caveated as
  approximate:** rejected, mirroring ADR-017's D3 reasoning exactly -- an
  approximate number built on an assumption this codebase has no basis for
  is not "approximate," it is a plausible-looking number nobody can audit.
- **Clamp an over-limit qualifying value to its total instead of failing
  closed:** rejected; clamping silently substitutes a different (smaller)
  analyst input than the one actually typed, which is a more dangerous
  failure mode than an honest "cannot compute" message.

## Consequences

- The Staffing what-if section renders independently of live Contract
  Facts -- an analyst can use it on a packet with no PIID resolved at all.
- The Section ledger grows to NINE rows (ADR-018/ADR-019's eight, now
  extended with this row); the Source manifest gains a
  `Staffing what-if inputs (analyst-entered)` `USER_ATTESTED` row with NO
  live-supersession branch (unlike the analyst-typed set-aside row) --
  the staffing inputs are never superseded by anything else in the packet.
- No score, tier, rank, or bid/no-bid vocabulary is introduced; every
  what-if output line carries the planning-indicator-not-determination
  framing (AGENTS #4) and the (a)(2)-evidence-only framing.
- Automated coverage remains fully offline and deterministic: 29
  hand-computed + edge-vector tests in `staffing_whatif.py`'s own suite,
  plus packet/export/AppTest coverage confirming the section's placement,
  ledger/manifest predicates, and the mode-aware exclusion note render
  correctly through the real UI widgets (checkbox + number_input; no
  `file_uploader` involved, so no `AppTest` version-skew workaround is
  needed here).
