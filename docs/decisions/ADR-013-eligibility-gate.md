# ADR-013: The N6 eligibility gate presents set-aside evidence, never a pursuit verdict

## Status

Accepted for the A1 N6 eligibility-gate slice

## Date

2026-07-19

## Context

The cited Opportunity Packet needs to put the contract's prime-eligibility
constraint ahead of downstream geography and Procurement List evidence. For a
nonprofit agency (NPA), the relevant first fact is the contract's reported
set-aside status: a small-business or socioeconomic set-aside structurally bars
the NPA from priming, while an affirmative `NONE` value means a set-aside does
not create that structural bar.

This fact is easy to overstate. A blank FPDS-style value is missing evidence,
not evidence of full-and-open competition. A record with no reported set-aside
restriction can still fail other pursuit gates, and a barred prime lane does
not establish whether a
subcontract or teaming lane is suitable. ADR-003 also requires ReconRadar to
present status without independently determining eligibility. AGENTS.md #8,
#11, and #13 prohibit automated bid/no-bid decisions, unsupported route or
capability claims, and converting unknown evidence into positive or negative
evidence. Invariant N1 prohibits a numeric rating.

## Decision

Add a pure, three-state Eligibility Gate as the first substantive section of
the Opportunity Packet. It classifies only the raw analyst-entered set-aside
value, preserving that value verbatim for the cited render:

1. A blank, whitespace-only, or absent value is `UNKNOWN`. The packet says the
   status was not reported, explicitly states that blank is not unrestricted,
   and directs the analyst to verify SAM.gov or USAspending before relying on
   it.
2. A trimmed, case-insensitive `NONE` value is `UNRESTRICTED`. This is the most
   permissive state, but it means only that no set-aside restriction was
   reported and that priming is not barred by a set-aside. It does not establish
   that the work is competable or full-and-open: extent of competition is a
   separate, unprovided fact, and a `NONE` set-aside can still be sole-source or
   not available for competition through a statutory or existing
   mandatory-source route. It is never green and never a pursuit or bid
   recommendation.
3. Every other non-empty value remains `SET_ASIDE_BARRED`, but the packet splits
   the rationale by set-aside family. Recognized small-business and
   socioeconomic codes cite the rule that a nonprofit agency is not a "small
   business concern" under 13 CFR 121.105. Buy-Indian codes instead state that
   the NPA is not an Indian Economic Enterprise and expressly do not rely on
   the 13 CFR 121.105 small-business rule. An unrecognized or other code remains
   barred but unverified: the packet directs the analyst to verify the exact
   set-aside type and makes no 13 CFR 121.105 claim. Every barred render also
   notes that an R1 subcontract or teaming lane may still apply, without
   assessing or recommending that route.

Common FPDS set-aside codes receive a friendly display label alongside the
always-shown raw value. An unrecognized non-empty code is labeled as
unrecognized and treated as a set-aside; the tool does not guess its meaning.
The value is labeled analyst-entered and not independently verified. The render
states that it presents a cited set-aside status plus a structural rule and that
the human decides; it does not independently determine eligibility. No score,
rank, percentage, PWin, or bid/no-bid output is introduced.

## Alternatives considered

- **Treat a blank value as unrestricted:** rejected because it converts missing
  evidence into a positive state and violates the FPDS `NaN != NONE`
  discipline and AGENTS.md #13.
- **Render unrestricted as green or as a pursuit recommendation:** rejected
  because the set-aside fact resolves only one structural constraint; other
  acquisition, capability, evidence, and business gates still apply.
- **Turn a barred prime lane into a teaming recommendation:** rejected because
  the set-aside fact does not establish partner availability, capability,
  relationship, commitment, job-family fit, or an appropriate route.
- **Calculate a composite eligibility or pursuit rating:** rejected because it
  would create false precision, violate N1, and drift into automated
  bid/no-bid.
- **Pull live set-aside data in this slice:** rejected because the Opportunity
  Packet remains paste-driven and offline-safe apart from its existing explicit
  ACS action; a live source requires a separately governed source contract,
  provenance, failure, and freshness design.

## Consequences

- Every rendered packet now exposes the set-aside evidence gap or structural
  rule before Contract Facts; a blank input can no longer disappear into an
  apparently open lane.
- `UNRESTRICTED` remains a never-green, human-review state. It means no
  set-aside only; it does not establish full-and-open or competable work because
  extent of competition is a separate fact not provided to this gate, and it
  does not answer whether to pursue.
- `SET_ASIDE_BARRED` closes only the NPA prime lane addressed by this gate. Its
  rationale is family-specific: small-business and socioeconomic codes cite 13
  CFR 121.105, Buy-Indian codes cite the Indian-Economic-Enterprise bar, and an
  unrecognized or other code stays barred but unverified with a direction to
  verify the type and no 13 CFR 121.105 claim. The R1 teaming note prevents a
  false dead end but does not route or recommend the opportunity.
- Friendly code labels aid reading but do not upgrade analyst-entered data into
  authoritative evidence or a determination-grade eligibility answer.
- A determination-grade set-aside-eligibility answer, including recognition of
  local-area and disaster set-asides and every FPDS code, is future work
  requiring the owner's domain confirmation and a new governed decision. The
  same applies to adding a live SAM.gov or USAspending set-aside pull.
