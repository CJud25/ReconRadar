# ADR-022: The R2a map routes citations to the four suitability criteria; it never assesses them

## Status

Accepted for the R2a determination-support-map slice

## Date

2026-07-21

## Context

The Opportunity Packet's roadmap spine ends at R2b. The product owner asked
for one more thing on top of that: a section that shows, at a glance, which
of the packet's ALREADY-COLLECTED evidence speaks to which of the four
suitability criteria a Procurement List addition is actually evaluated
against (41 CFR 51-2.4(a)). This is the single highest-risk section this
codebase has built to date, for a structural reason none of the earlier
packet sections had to face: every prior section presents evidence about
ONE thing (a set-aside code, a solicitation window, a competition posture).
This section's entire JOB is to organize evidence UNDER a legal criterion
label -- and the moment a fact sits under a heading like "(a)(2): the NPA's
qualifications," a reader's eye finishes the sentence for you ("...and
therefore qualifies") whether the text says so or not. AGENTS.md #3 ("Never
score or rank a person...") and N1 ("packet, not score") both predate this
slice, but neither was written with a *criterion-labeled* evidence map in
mind. This ADR is the record of how this slice avoids becoming the
determination it explicitly refuses to make.

Two counsel-gated facts make the stakes concrete: C3 (small-business goal
credit for a prime that subcontracts to an AbilityOne NPA, 10 U.S.C. 3903 /
DFARS 219.703 -- citation corrected 2026-07-21, see ADR-020) and C4 (Limitation-on-Subcontracting conditionality, 13 CFR
125.6) are NOT owner-attested (ADR-020) -- they are legal questions. A map
that organizes evidence by suitability criterion is exactly the kind of
surface where a well-meaning future edit could quietly "fill in" one of
these under a plausible-sounding paragraph. This ADR draws that line
explicitly so it survives future edits, not just this one.

## Decision

Add a pure `r2a_map.py` module (mirrors `capture_window.py` /
`eligibility_gate.py` / `incumbent_leads.py` / `staffing_whatif.py`) with
six load-bearing choices.

1. **Structural citation routing, never assessment.** `derive_r2a_map`
   computes NOTHING new. Every evidence line either cites an
   already-rendered packet section by reference ("see the ... section
   above") or reproduces a standing disclaimer verbatim. No criterion row
   carries a met/unmet marker, a numeric score, a count, or a color --
   there is no scale for any of these four criteria to be measured against
   in the first place, so rendering one would manufacture false precision
   on top of an already-honest absence of data.
2. **(a)(1) reproduces the geography disclaimer INLINE, not by reference
   (audit MAJOR).** Routing a county disability statistic toward
   "employment potential" without restating
   `GEOGRAPHY_CONTEXT_DISCLAIMER` verbatim, right there in the row, invites
   exactly the inference the disclaimer exists to forbid -- a reader
   scanning a criterion-labeled row for "does this county have enough
   people with disabilities to support this contract" would get an
   affirmative-reading impression from placement alone, even from a
   correctly-cited but silently-implied fact. The row states, plainly:
   Geography context is attached, here is the disclaimer verbatim, and
   employment-potential evidence beyond context is analyst work -- not
   something this map, or the Geography panel it cites, provides.
3. **(a)(3) states explicitly that the capability list is unassessed
   (audit MINOR).** The owner-attested capability-areas list (ADR-020) is
   a list of SERVICE CATEGORIES the NPA and its network broadly cover, not
   a claim it can meet THIS contract's specific PSC or scope of work. A
   static list rendered under "(a)(3) Capability" without that caveat
   would read as an implicit "yes, we can do this" the owner never
   attested to. The row's own text says "general attested capability
   areas — NOT assessed against this contract's scope or PSC," so the
   list can never be screenshotted as a capability determination on its
   own.
4. **(a)(2) distinguishes "not entered" from "entered but invalid."** A
   Staffing what-if that reached `CANNOT_COMPUTE` (a partial baseline) is
   not "no packet evidence" -- something WAS typed, it just did not
   validate. Collapsing that into the same "no packet evidence speaks to
   this criterion yet" line as a genuinely untouched section would be a
   small but real loss of honesty (an analyst re-reading this map later
   could not tell "I haven't started this" from "I started this and it
   didn't work"). The row gets its own distinct line for that case, citing
   the Staffing what-if section for the reason, never repeating or
   re-deriving the failed computation's inputs.
5. **No manifest row.** The Source manifest lists ATTACHED sources; this
   map attaches none of its own. Every fact it cites was already sourced,
   cited, and manifested by the section it points back to (Geography,
   Staffing what-if, Incumbent leads). A manifest row here would either
   duplicate an existing citation under a new label (confusing, since the
   underlying source didn't change) or -- worse -- read as though the map
   ITSELF is a source of evidence, which is precisely the "packet, not
   score" line this whole module exists to hold. The Section ledger row is
   sufficient: it records that the SECTION rendered, not that a new source
   was attached.
6. **Renders unconditionally, needing no external builder param.** Unlike
   every other optional packet section, this one has nothing to be absent
   FROM: an all-empty map, with all four criteria showing the honest "no
   packet evidence speaks to this criterion yet" line, is itself a
   perfectly valid, informative render (it tells the analyst exactly how
   thin the current evidence base is). `build_opportunity_packet_markdown`
   therefore computes and renders it internally, at the very end, from
   evidence it already has in scope by that point -- `geography` and
   `staffing` (existing params) plus the newly-HOISTED `capture_window`
   and `incumbent_leads` locals (previously scoped only inside the
   `contract_facts is not None` branch; both now default to `None` before
   that branch so they are always defined, whether or not it runs). No new
   keyword param was added to the builder's own signature.

**Why `contract_facts` and `pl_matches` are NOT separate `derive_r2a_map`
parameters**, even though both are part of "the packet's existing typed
evidence": `incumbent_leads` is only ever non-`None` when the packet
builder already required live Contract Facts to compute it (see
`opportunity_packet.py`), so `contract_facts`'s presence is fully implied
by `incumbent_leads`'s presence -- an independent parameter would be
redundant with no behavior it alone could drive. `pl_matches` (the R2b
Procurement List cross-reference) is opportunity-discovery evidence about
whether THIS worksite already appears on the Procurement List -- it does
not speak to employment potential, NPA qualifications, delivery capability,
or incumbent impact any more directly than it speaks to any of the other
three, and forcing a routing for it would manufacture a connection the
brief never asked for and the evidence does not support.

## What this slice deliberately does NOT do

- **No PSC<->capability mapping table.** Building an actual PSC-to-
  capability crosswalk is derived analytical work with its own methodology
  questions (fuzzy category matching, confidence, false positives) that
  deserves its own slice and its own review -- not a quiet addition inside
  a determination-support map. The (a)(3) row's capability list stays
  prose, not a table, and the row explicitly disclaims that no such
  assessment happened.
- **No C3/C4 content anywhere.** Neither the SB-goal-credit question nor
  the LoS-conditionality question is attested (ADR-020); this module
  never mentions either, in any row, in any render. A test sweeps every
  render combination in this module's own suite for the counsel-gated
  vocabulary and asserts its absence, so a future edit that tries to "fill
  in" either fact breaks the build rather than shipping quietly.
- **No outcome or timing promise.** The epilogue states allocation is
  CNA-discretionary and a case may originate from either direction, but
  never implies that origination predicts allocation, that adding to the
  Procurement List is a foregone conclusion, or that any specific timeline
  is more than an owner-attested generic methodology band (the same
  discipline ADR-015/ADR-020/ADR-021 already hold for the Capture Window
  and the Staffing what-if).

## Alternatives considered

- **A met/unmet marker or a fraction like "2 of 4 criteria have evidence":**
  rejected; a count invites exactly the "how close are we" reading this
  module exists to prevent, and there is no methodology this codebase has
  for weighting the four criteria against each other even if it wanted to.
- **Cite the geography section by reference only ("see Geography above"),
  omitting the disclaimer text:** rejected (the audit MAJOR); a reference
  alone lets the reader supply their own, unguarded interpretation of what
  the cited section means.
- **Let the (a)(3) capability list stand alone, since ADR-020 already
  labels it "for capability-context copy":** rejected (the audit MINOR);
  ADR-020's label is about the SOURCE data's intended use in general, not
  a guarantee that every future render of that list carries its own
  caveat -- this row needed its own explicit statement.
- **A manifest row citing "the packet's other sections" as this row's
  source:** rejected; every fact this map touches is already manifested by
  its origin section, and a second, vaguer citation adds confusion, not
  provenance.
- **Route `pl_matches` to (a)(1) on the theory that PL presence signals
  "this location already sustains AbilityOne-style work":** rejected as an
  inference this codebase has no basis for -- a Procurement List line at a
  location says nothing about who works there or what population lives
  nearby; that is exactly what ACS geography context is for, and blending
  the two would misattribute R2b's discovery evidence as employment
  evidence.
- **Add a `contract_facts` parameter for future extensibility even though
  it is unused today:** rejected; an accepted-but-unused parameter is a
  standing invitation for a future author to wire it into something
  without re-deriving why it was safe not to -- if a future slice needs
  it, that slice can add it deliberately, with its own justification.

## Consequences

- The R2a determination-support map is the ONLY packet section that
  renders on every single packet, regardless of what else is attached --
  it is also the only section for which "empty" is itself a valid,
  informative state rather than an omission.
- The Section ledger grows to TEN rows (ADR-018's seven, ADR-019's eight,
  ADR-021's nine, now ADR-022's ten); the Source manifest is UNCHANGED --
  this slice adds zero new manifest rows.
- `R2A_PRESENTS_NOT_DETERMINES`'s wording avoids the literal word "score"
  even as a negation ("does not assess, rate, or determine," not "...
  score..."): because this text now renders on EVERY packet, the literal
  guarded word collided with several existing whole-packet "score not in
  packet" tests the moment the section became unconditional. This
  codebase's established convention (seen already in `PACKET_FRAMING`) is
  to avoid the guarded word entirely in standing framing text, not merely
  to negate it, precisely so a blanket packet-wide guard never has to be
  rewritten to carve out an exception for a legitimate negation.
- `capture_window` and `incumbent_leads` are no longer builder-local
  variables scoped only inside the `contract_facts is not None` branch;
  both are hoisted to `None` defaults before it, so they are always
  defined by the time the R2a map is computed at the end of
  `build_opportunity_packet_markdown`, whether or not that branch ran.
- Automated coverage: a dedicated suite for `r2a_map.py` (fixed order,
  per-criterion absence/presence, both routing rails, the fixed epilogue,
  the conditional Capture Window citation, a hard C3/C4-absence guard
  across every input combination, and a no-table guard on the capability
  row), plus packet/export/AppTest coverage confirming the section always
  renders last and that a real staffing entry, driven through the actual
  UI widgets, routes into the (a)(2) row.
