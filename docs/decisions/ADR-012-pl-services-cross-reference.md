# ADR-012: The R2b Procurement List cross-reference is a cited location fact-pair, never a verdict

## Status

Accepted for the A1 R2b cross-reference slice

## Date

2026-07-19

## Context

The A1 walking skeleton renders a cited Opportunity Packet from a pasted contract
identifier and place (ADR-011). This slice adds the roadmap's "buildable-now"
R2b lead: cross-referencing the pasted worksite against an analyst-uploaded
AbilityOne **PL Services** directory and surfacing any Procurement List service
line at the **same city/state** — *"this expiring service matches a service
already on the Procurement List at [loc] — confirm it's yours."*

Public data funds *evidence*, not a *verdict*, and this cross-reference sits in a
particularly easy place to overclaim. A BD reader who sees "a PL line here" plus
"an expiring contract here" naturally infers the expiring work is convertible to
the Procurement List or winnable — which is the R2a addition route, a separate
suitability determination this tool deliberately stubs until domain constants
are confirmed. The Services export also has **no column naming which nonprofit
agency performs a line** (its `cna` column is the Central Nonprofit Agency
intermediary — NIB/SourceAmerica — not the holder), and the exact-city match key
has large, systematic blind spots (base/installation-named worksites, adjacent
metro cities, statewide/regional lines). AGENTS.md #10 requires a decision record
for a material surface change; #11 forbids implying a route/relationship/
capability; #13 forbids converting missing evidence into positive or negative
evidence. Invariants N1 (no score), N3 (provenance), and N4 (exact city/state,
no fuzzy) also bind.

Constraints this decision has to respect:

- The Opportunity Packet surface is deliberately case-independent and
  paste/upload-driven; the cross-reference must not touch the SQLite case store
  or the scanner workflow (ADR-006, ADR-007, AGENTS #16–#17).
- Location matching must reuse the connector's existing exact primitive; no
  second location matcher, no fuzzy/proximity/substring inference (N4).
- The whole surface is discovery evidence; it must never render a numeric rating
  (N1) or a resolved pursuit/route conclusion (AGENTS #11).
- Every fact carries provenance and a freshness posture; the Procurement List is
  a point-in-time set amendable by Federal Register notices (N3).

## Decision

Add a small pure module `pl_match.py` and a caveat-first render, with five
load-bearing choices.

1. **Exact city/state via the existing primitive.** `find_pl_service_matches`
   reuses `connectors.abilityone.service_location_matches` for the location gate.
   That primitive fails closed on any row whose location did not parse, so
   statewide/regional and otherwise-unparsed lines can never be a silent match.
   No new location logic is introduced. The worksite city is a **separate input**
   from the packet's ACS County (a county is not a city); the state is shared.

2. **Pure, offline, no case store.** The matcher takes already-parsed
   `NormalizedRecord`s and returns a frozen `PLMatchResult`. The UI parses an
   uploaded workbook offline through `AbilityOneServicesConnector` (bytes-in,
   `USER_ATTESTED` by default) and never opens a socket, touches the ledger, or
   routes through the scanner. This keeps the packet surface case-independent and
   the match logic independently testable.

3. **Caveat-first render.** `pl_service_match_lines` emits the standing honesty
   statements *before* any fact-pair: discovery-evidence-only; the
   **non-convertibility** caveat (a PL line is not evidence the pasted contract
   is competable, convertible, or winnable — R2a is a separate CNA-submitted
   determination); the **whose-line** caveat (the export names no performing
   agency, and the `cna` shown is the intermediary, not the holder); and a
   provenance + **Federal Register staleness** stamp.

4. **Service-type equality is a labeled string fact.** When the analyst supplies
   a service type, a `normalize_service_type` (casefold + whitespace-collapse,
   no fuzzy) equality is surfaced as a *character-equal string fact, not a
   same-service or capability finding*. A blank/whitespace-only query never
   manufactures a match (no blank-equals-blank). Same-location lines with a
   different service type are shown strictly subordinate, labeled "presence, not
   relevance," as a plain count — never ranked and never counted as matches.

5. **No-match is evidence-absence; the sample is synthetic.** When a PL workbook
   was searched but nothing parsed to the exact city/state, the render states
   the absence and names the exact-city blind spots (base-named worksites,
   adjacent metro cities, statewide/regional lines, stale/partial uploads) — it
   never emits "not on the Procurement List." A bundled example workbook is
   marked SYNTHETIC both inside the file (a title row) and in the packet output,
   so an illustrative match can never be screenshotted as a real finding.

## Alternatives considered

- **Match the packet's County directly against the PL city:** rejected — a
  county is not a city; feeding County as the city argument would fabricate
  precision and produce coincidental hits/misses a domain expert would spot.
- **State-only or fuzzy/proximity/substring matching:** rejected — it violates
  N4 and the connector's deliberate anti-fuzzy design, and would inflate a metro
  area's unrelated lines into false "matches."
- **Fold the matcher into `opportunity_packet.py`:** rejected — the matcher needs
  the connector layer (`NormalizedRecord`, `service_location_matches`); a
  separate module keeps the pure packet builder's dependency surface small and
  the match logic independently testable. The builder takes an already-computed
  `PLMatchResult`.
- **Render a match as an "R2b lead"/"pursue" route or a numeric match score:**
  rejected — a route/pursuit conclusion violates AGENTS #11 (and decouples a
  pursuit signal from the deferred eligibility gate), and any score violates N1.
  The surface stays discovery evidence with counts, not ratings.
- **Treat a no-match as "not on the Procurement List":** rejected — exact-city
  matching is blind to base-named/adjacent/statewide worksites, so a no-match is
  missing evidence, not negative evidence (AGENTS #13).
- **Read already-scanned Services rows from the case store:** rejected — it would
  couple the case-independent packet to a prior scan and to the ledger; an
  offline upload keeps the surface self-contained.
- **Surface the `cna` value as the line's owner:** rejected — the CNA is the
  NIB/SourceAmerica intermediary, not the performing NPA; it is shown only with
  an explicit "not the performing agency" label.

## Consequences

- Exact-city matching has systematic, expected false negatives (base/installation
  worksite names, adjacent metro-area cities, statewide/regional PL lines that
  parse UNPARSED). These are disclosed on the no-match render and never converted
  to a negative "off the Procurement List" conclusion.
- "Whose line is this" and whether an expiring contract is convertible to the
  Procurement List (R2a) remain **analyst determinations**; the tool asserts only
  the location fact-pair and a labeled service-type string coincidence.
- The bundled sample is illustrative only; a real cross-reference requires an
  analyst-uploaded approved PL Services export.
- Any future service-type correspondence beyond exact string equality (synonyms,
  a PSC/service crosswalk), any proximity/commute-shed matching, or any R2a
  determination-grade content is a **new ADR** and depends on the domain
  constants owed by the program owner (roadmap §10).
