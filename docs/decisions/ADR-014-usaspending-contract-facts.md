# ADR-014: Live USAspending contract facts require exact single-award resolution

## Status

Accepted for the A1 live contract-facts slice

## Date

2026-07-19

## Context

The Opportunity Packet currently presents analyst-pasted Contract Facts that are
explicitly not independently verified. The A1 live contract-facts slice adds a
cited pull from the public USAspending API so an analyst can paste a PIID and
retrieve the actual single-award facts needed for review: obligated amount,
ceiling, period of performance, set-aside, extent of competition, offers,
NAICS/PSC, awarding sub-agency, and recipient.

This source cannot be treated as a one-step identifier lookup. USAspending's
award search is a fuzzy keyword POST, a PIID is not globally unique, and the
single-award detail endpoint requires USAspending's generated internal award ID.
Silently accepting a substring result or the first search row could attach facts
from the wrong award. The live detail response also contains domain distinctions
that must survive parsing and rendering: `total_obligation` is money obligated,
`base_and_all_options` is a potential ceiling, competition must be interpreted
from its code, and a null `type_set_aside` is missing evidence rather than an
affirmative unrestricted value.

ADR-011 established the A0.5 public-API retrieve/parse boundary, standard-library
HTTP transport, bounded reads, injected offline test seam, retrieval provenance,
and fail-loud connector errors. ADR-013 established the three-state Eligibility
Gate and its rule that blank set-aside evidence remains `UNKNOWN`. This decision
extends both boundaries without routing the API through the workbook scanner,
joining it to synthetic people or outcomes, or turning the packet into a score
or bid/no-bid decision.

## Decision

Adopt a two-step USAspending single-award connector and cited packet integration
with six load-bearing choices.

1. **Reuse the A0.5 retrieve/parse boundary and add a POST sibling.** The award
   search uses a new bounded stdlib `http_post`; a GET-only client cannot issue
   USAspending's POST search. Network access remains confined to `retrieve_*`
   functions, while `parse_*` functions remain pure and byte-in. `http_post`
   mirrors `http_get` for user agent, timeout, bounded reads, injected opener,
   provenance, and fail-loud error mapping; no new HTTP dependency is added.

2. **Represent USAspending as an API source, never a workbook source.** Add
   `SourceKind.USASPENDING_AWARD` and deliberately exclude it from
   `WORKBOOK_SOURCE_KINDS`, so it cannot be offered as an upload or routed
   through the workbook scanner. Reuse `Assurance.API_RETRIEVED` for provenance
   and add the bounded `AWARD_NOT_FOUND` error for zero exact matches. Existing
   upstream transport, schema, rate-limit, and size error codes remain in force.

3. **Resolve PIID multiplicity before fetching detail.** POST the award search,
   retain only case-insensitive exact `Award ID` matches, and use the generated
   internal award ID to fetch detail. Exactly one exact match resolves and
   proceeds to detail; more than one returns candidates for explicit analyst
   disambiguation and never fetches or auto-picks detail; zero raises
   `AWARD_NOT_FOUND`. Once an analyst selects a candidate, its generated internal
   ID may be supplied directly to fetch that award's detail without repeating
   search. **The search reads a single page (100-row `limit`).** Because a short
   substring-y PIID can match more rows than one page, exact-match completeness
   is not guaranteed under truncation: when the result set is truncated
   (`page_metadata.hasNext`, or a full page) and would otherwise auto-resolve a
   lone page-1 exact match or report zero, the connector instead raises the loud
   `AWARD_SEARCH_TRUNCATED` (refine the PIID or supply the award id) rather than
   silently pick one or falsely report not-found. Full pagination is deferred
   future work; the analyst-supplied award-id path is the exact escape hatch.

4. **Preserve the financial and competition meanings in the source.** Render
   `total_obligation` as “Obligated to date” and `base_and_all_options` as the
   separate “Ceiling (base + all options),” explicitly stating that the ceiling
   is potential value and not money obligated. Read extent competed from the
   reliable FPDS code and treat its description as display text. Missing numeric
   values remain missing; they are never converted to zero.

5. **Feed the retrieved set-aside into the existing Eligibility Gate with honest
   provenance.** The latest transaction's `type_set_aside` supersedes the typed
   value for the gate when live contract facts are attached. A populated code
   follows ADR-013's existing classifier. A null value means not reported and
   therefore produces `UNKNOWN`, never `NONE` or unrestricted. A keyword-only
   `source_lines` seam lets the gate cite the USAspending URL and retrieval time
   instead of falsely labeling the value analyst-entered.

6. **Keep the potential end date as a source string.** USAspending's
   `potential_end_date` may include a `" 00:00:00"` suffix. Store it and display
   it as a string, with at most a safe string-only suffix trim for readability;
   never strict-parse it as a date.

## Alternatives considered

- **Silently select the first matching award:** rejected because a PIID is not
  unique and search order is not evidence that the first row is the intended
  award. Multiple exact matches require analyst disambiguation.
- **Read the ceiling from `base_and_all_options_value`:** rejected because that
  key does not exist on the confirmed-live award detail response. The detail
  field is `base_and_all_options`.
- **Treat a null set-aside as `NONE`:** rejected because null means not reported,
  not unrestricted. Converting it would violate the `NaN != NONE` evidence rule
  and manufacture a permissive eligibility state.
- **Strict-parse `potential_end_date`:** rejected because the live value may
  carry a time suffix and a strict date parser would turn valid source evidence
  into an avoidable failure.
- **Reuse `http_get` for award search:** rejected because USAspending's search
  endpoint requires a POST with a JSON body; GET is reserved for the resolved
  award detail request.

## Consequences

- This slice retrieves and renders facts for one resolved federal award only.
  Parent-IDV or vehicle ceiling rollup, subaward or teaming data, price-to-win or
  competitive-range analysis, backtest or calibration, and multi-award
  recompete-lineage logic remain future work.
- ~~Place-of-performance auto-wiring into the ACS pull remains future work.~~
  **Update (2026-07-22):** shipped. The detail parse now carries the award's
  reported description and place-of-performance components; the live block
  renders them per-component (a county is not a city), and both facts-attach
  paths prefill only BLANK domestic county/state/worksite-city inputs -- never
  overwriting analyst or handoff values, disclosed in the success message.
  The analyst-entered location and Contract Facts block remain visible and
  distinct from the cited live award-facts block.
- No score, rank, tier, PWin, recommendation, or automated bid/no-bid output is
  introduced. The connector supplies cited evidence for human review and does
  not establish capability, partner availability, acquisition route, or whether
  to pursue.
- Every resolved record carries the detail endpoint URL and retrieval timestamp.
  Missing, malformed, unavailable, oversized, rate-limited, and not-found
  responses fail loud rather than becoming empty or fabricated facts.
- Automated coverage remains fully offline through hand-authored search and
  detail fixtures plus an injected opener. The connector is coded to the
  confirmed-live shapes from the PM capture; consistent with ADR-011, the live
  endpoint must be verified on the first real run.
