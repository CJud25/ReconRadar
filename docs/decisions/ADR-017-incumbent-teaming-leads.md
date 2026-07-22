# ADR-017: Incumbent & teaming leads are a cited packet, never a computed share

## Status

Accepted for the A5 incumbent-and-teaming-leads slice

## Date

2026-07-20

## Context

The Opportunity Packet's roadmap spine runs Eligibility Gate -> Contract Facts
-> Capture Window -> **Incumbent & teaming leads / PL-impact context** ->
Geography -> R2b. ADR-014 deliberately deferred "subaward or teaming data" as
future work; this slice fills that gap using fields the USAspending contract-
facts connector already parses (`extent_competed_code`,
`number_of_offers_received`) plus two new pieces of evidence: the recipient's
public `business_categories` (registration facts) and a new subawards
retrieval for the resolved award (teaming-posture evidence).

Four honesty risks are specific to this evidence, beyond the general N1
packet-not-score invariant:

* Extent-of-competition and offers data are public *signals*, not proof of
  entrenchment, willingness, or capability -- treating them as anything
  stronger would misrepresent public procurement data as a competitive
  assessment.
* Subaward (FSRS/FFATA) reporting has a real-world reporting threshold
  (roughly $30K) and is materially under-reported. A zero-subaward result is
  common for contractors who DO subcontract; presenting it as "no teaming"
  would be a confident, false negative.
* A directory-name match against a subawardee name is a string coincidence,
  not evidence of a relationship, capacity, or willingness to team (AGENTS
  #11's "never imply partner availability... or relationship" rule, extended
  here from the public-evidence scanner to the packet).
* The roadmap sketches a PL-impact "share of the incumbent's federal
  obligations" figure for suitability criterion (a)(4). The only public
  denominator available (USAspending recipient-profile trailing-12-month
  totals) does not window-match a single award's lifetime `total_obligation`,
  and the Commission's real (a)(4) test uses TOTAL sales including commercial
  business, which is not public at all. Computing a ratio here would be
  fabricated precision presented as a suitability metric.

## Decision

Add a pure `incumbent_leads.py` module (mirrors `capture_window.py` /
`eligibility_gate.py`) and extend the USAspending connector, with five
load-bearing choices.

1. **D1 -- Subaward scope is THIS award only.** The teaming-posture evidence
   is the incumbent prime's reported subawards on the resolved award (one
   `POST /api/v2/subawards/` call, keyed to `generated_unique_award_id`). A
   market-wide "which primes team with NPAs" sweep would require a
   recipient-search fan-out across many awards and is explicitly deferred
   future work -- this slice only ever answers "does THIS award show reported
   subawards, and to whom."

2. **D2 -- Directory cross-reference is normalized EXACT match only.**
   Subawardee names are compared against an optional analyst-uploaded
   AbilityOne NPA directory export by casefold + trim + collapsed-whitespace
   equality -- the same discipline R2b established (`pl_match.py`,
   `service_location_matches`). No fuzzy/substring matching. A match renders
   as the **Coincident** band with explicit analyst-confirm framing ("a name
   COINCIDENCE, not a confirmed relationship, partnership, capacity, or
   willingness to team"); a miss is NOT evidence of no NPA teaming (subaward
   reporting is incomplete regardless of whether a directory was uploaded),
   and the honest no-match line says so.

3. **D3 -- No computed federal-share ratio this slice.** The PL-impact
   context block renders side-by-side CITED facts only -- this award's
   obligated-to-date, period of performance, and the recipient's
   registration-derived business categories -- with a standing label stating
   why no share is computed: the public denominator (trailing-12-month
   recipient totals) does not window-match this award's period, and the
   Commission's (a)(4) impact test uses total sales including commercial
   business, which is not public. **What would make a share honest:** a
   FY-windowed recipient-total figure that actually matches this award's
   period of performance, obtained either from a future USAspending
   recipient-profile pull scoped to the matching fiscal years or from an
   authoritative non-public source the owner supplies; until then, any
   computed percentage here would be fabricated precision.

4. **Band vocabulary encodes evidentiary strength, structurally enforced.**
   Every rendered lead carries exactly one of four bands: **Observed** (a
   directly-cited field value restated without interpretation), **Lead-
   corroborated** (>=2 genuinely independent Observed signals named in the
   text -- reserved; no currently-derived signal pair qualifies, because on
   a not-competed award the offers count is ENTAILED by the sole-source
   designation and entailment is not corroboration), **Lead-single**
   (exactly 1 Observed signal, named in the text), or **Coincident** (the
   directory match). A single offer on a COMPETED award and a low/no offer
   count on a NOT-competed award are two DIFFERENT signals and are never
   conflated -- the former is `Lead-single` independently; the latter is
   named inside the sole-source `Lead-single` as consistent with (not
   independent of) the designation, never as its own standalone claim and
   never as a band upgrade. (Adversarial verification corrected an earlier
   draft of this design that treated the entailed pair as corroboration.) `extent_competed_code` classification is
   code-driven (A/D/F competed; B/C/G not-competed/sole-source), never from
   the free-text description; an unrecognized code renders as "competition
   posture not classified here," never a guess. No-citation-no-render is
   enforced STRUCTURALLY: the `Lead` dataclass's `__post_init__` rejects an
   empty `text`/`source_url`/`retrieved_at`, and a non-Observed lead also
   requires a non-empty `basis` naming its underlying signal(s) -- a
   programming error that tries to render an uncited or unexplained
   interpretation fails loud at construction, not silently in the UI.

5. **Truncation is CARRIED on subawards, not raised (contrast award
   resolution).** `pull_contract_facts` raises `AWARD_SEARCH_TRUNCATED`
   because a truncated PIID search could hide a second exact match and break
   the "never silently pick one" uniqueness guarantee. Subawards have no such
   uniqueness contract -- a partial list of real, retrieved subaward records
   is still honest evidence even when more exist upstream. `SubawardsResult.
   truncated` is carried through and the renderer states "more subaward
   records exist than were retrieved (first 100 shown)" rather than the pull
   failing.

Supporting connector change: `ContractFactsRecord` gains
`recipient_business_categories: tuple[str, ...] | None` from the award-
detail `recipient.business_categories` list (absent/null stays `None`,
never `()`, so "not reported" and "reported as empty" remain
distinguishable; a present-but-non-list value fails loud with
`UPSTREAM_SCHEMA`). A new `SourceKind.USASPENDING_SUBAWARD` is added,
excluded from `WORKBOOK_SOURCE_KINDS` like `USASPENDING_AWARD`.

## Live-verify status (ADR-011 first-run discipline)

Both new shapes were verified against the REAL, live USAspending API before
shipping:
`recipient.business_categories` on the award-detail endpoint, and the
subawards endpoint's `page_metadata` (`hasNext`) and per-row keys
(`subaward_number`, `recipient_name`, `amount`, `action_date`,
`description`). Both matched the documented shape and the hand-authored
fixtures exactly; no parser correction was needed (contrast the awards
endpoint's ADR-014, where a first-run correction WAS needed -- this
slice's first run needed none).

## Alternatives considered

- **Compute a "% of incumbent obligations from this award" ratio anyway,
  caveated as approximate:** rejected (D3); an approximate ratio computed
  from a window-mismatched denominator is not "approximate," it is wrong in
  a way a reader cannot detect, and the (a)(4) test's real denominator
  (total sales including commercial business) is not public at all -- no
  caveat rescues a number built on the wrong base.
- **Fan out a market-wide subaward/recipient search to find ALL NPA
  teaming relationships, not just this award's:** rejected as D1 scope
  creep; that is a materially larger connector (recipient search, pagination
  across many awards) that deserves its own slice and its own review, not a
  quiet expansion here.
- **Fuzzy or substring directory-name matching (e.g. token overlap):**
  rejected (D2); this codebase has held exact-match-only for every prior
  name/location cross-reference (R2b's `service_location_matches`) precisely
  because fuzzy matching manufactures false positives an analyst cannot
  audit.
- **Treat a zero-subaward result as a stored boolean "no teaming":**
  rejected; FSRS under-reporting makes zero-is-absence, not zero-is-negative
  evidence, a hard invariant (N2) with its own mandatory caveat.
- **Fold the directory-match Coincident leads into the same citation group
  as the subaward Observed leads (single Source/Retrieved-at/Assurance
  footer):** rejected; the underlying subawardee FACT is API_RETRIEVED but
  the cross-reference itself depends on an analyst-uploaded, USER_ATTESTED
  directory -- collapsing the two would mislabel the weaker-provenance half
  of the claim as API-retrieved. The renderer keeps them as a visually
  separate block with its own `Assurance: USER_ATTESTED` footer even though
  each `Lead`'s own citation still points at the (real, non-empty) subawards
  source for no-citation-no-render purposes.
- **Give every `Lead` its own `assurance` field instead of deriving it at
  render time:** considered, but the section only ever has two real
  evidentiary sources (the Contract Facts pull and the subawards pull, both
  `API_RETRIEVED`) plus the directory upload's `USER_ATTESTED` overlay on
  the Coincident leads specifically -- deriving assurance from band +
  citation grouping at render time avoids a field that would otherwise
  always hold one of two constants.

## Consequences

- The new section only ever appears when live Contract Facts are attached
  (same precedent as Capture Window); it needs no extra pull to show its
  competition and registration-facts leads, and enriches with subaward/
  directory evidence only once the analyst pulls/uploads them.
- The Opportunity Packet page now has THREE independent analyst-initiated
  live network requests (contract facts, subaward records, ACS geography
  context); the page's captions were reworded to say so honestly rather
  than each claiming to be "the only" network step (four as of ADR-023).
- No score, tier, rank, percentage, or recommendation is introduced by this
  slice. Every lead is framed as candidate evidence for analyst review; any
  outreach decision is explicitly the analyst's.
- A real, FY-windowed recipient-total figure that would make a PL-impact
  share honest is an owner [VERIFY] this slice does not have and must not
  claim to have; a future slice may add it once that figure is sourced.
- Automated coverage remains fully offline and deterministic (subaward
  ordering has no dict/set nondeterminism); the sanctioned live call was
  separately verified before shipping.
