# ADR-029: Barred gate names the mandatory-source lane

## Status

Accepted; amends the ADR-013 barred render

## Date

2026-07-27

## Context

ADR-013 made the eligibility gate a three-state presentation of set-aside
evidence, not a pursuit verdict. Its `SET_ASIDE_BARRED` render named the
set-aside prime-lane bar and the separate R1 teaming lane, but never mentioned
the Procurement List.

That omission creates finding A1 for ReconRadar's AbilityOne-NPA audience. FAR
8.002 and FAR subpart 8.7 establish a Procurement List addition as a
mandatory-source route. For small-business set-asides, that mandatory-source
priority sits above the set-aside. A barred set-aside prime lane therefore must
not read as "discard": it does not answer whether the requirement is on, or
suitable for addition to, the Procurement List. The interaction with other
set-aside families is also outside this gate's evidence.

## Decision

Add one module-level mandatory-source-lane caveat and render it for all three
`SET_ASIDE_BARRED` rationale families: small business, Buy-Indian, and
unverified codes. The caveat:

- scopes the bar to the prime-as-a-set-aside lane;
- identifies the FAR 8.002 / FAR subpart 8.7 mandatory-source route;
- limits the priority-above-set-aside statement to small-business set-asides
  and leaves other set-aside-family interactions unassessed;
- states that this requirement's Procurement List status and suitability are
  not assessed by the gate; and
- cross-references the R2a determination-support map by name.

Scope the barred headline to
`SET_ASIDE_BARRED (set-aside prime lane)`. The render continues to present
evidence without determining eligibility, suitability, or route availability.

## Alternatives considered

- **Add the caveat to UNKNOWN and UNRESTRICTED:** rejected. UNKNOWN has no
  set-aside fact to caveat, while UNRESTRICTED already names a statutory or
  existing mandatory-source route.
- **Pass the R2b `pl_match` result into the eligibility gate:** rejected. It
  couples two pure modules and risks a half-verdict. An R2b no-match is
  evidence-absence, not proof of Procurement List status, and ADR-022 excludes
  R2b from suitability and gate evidence.
- **Assert that this contract is on, or suitable for, the Procurement List:**
  rejected. That fact is not in the gate's evidence. ReconRadar presents the
  separate lane and leaves the determination to the analyst.

## Consequences

- `SET_ASIDE_BARRED` remains barred for the set-aside prime lane.
- Every barred rationale family names the R2a mandatory-source lane as
  unassessed, rather than implying that it is open or closed.
- The gate remains pure and does not depend on R2b or any Procurement List
  lookup result.
- ADR-013 remains the original eligibility-gate decision; this ADR records the
  later barred-render amendment.
