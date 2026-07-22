# ADR-023: Federal Register PL notices are a cited national notice list, never a claim about this contract

## Status

Accepted for the A4 Federal Register slice

## Date

2026-07-21

## Context

The roadmap's A4 remainder is "Federal Register (PL add/delete notices) --
clean API, free, no key." The AbilityOne Commission publishes its own
Procurement List add/delete notices (and other Commission notices --
meetings, etc.) to the Federal Register, indexed by a clean, unauthenticated,
free public API (`www.federalregister.gov/api/v1`). This is exactly the
"public evidence base" shape every other connector in this codebase already
holds (Census ACS, USAspending): retrieve live, cite the source and
retrieval time, never editorialize.

Two live-probed facts turned into audit-BLOCKER-severity corrections against
an earlier draft of this slice, both load-bearing enough to record here
rather than only in the code comments:

1. **A raw space in the search term is not survivable.** `census_acs.py`'s
   established URL-builder style is a raw f-string interpolation
   (`f"{ACS_API_BASE}/{year}/acs/acs5?get=NAME&for=county:*&in=state:{state_fips}"`).
   That style is safe for `census_acs` because every interpolated value is
   either a fixed enum-like code or a FIPS digit string -- never analyst
   free text. Copying that style for `conditions[term]=<analyst text>` is
   NOT safe: `urllib.request.Request(...)` builds fine with an unencoded
   space in the URL, but `http.client`'s `putrequest` raises `InvalidURL`
   the moment `urlopen` actually sends the request line -- and `InvalidURL`
   subclasses `http.client.HTTPException` -> `Exception` directly, NOT
   `URLError`/`TimeoutError`/`OSError`/`ValueError`, which is exactly
   `http_get`'s catch tuple (`connectors/api.py:158`). An analyst typing a
   two-word search term ("procurement list") would have crashed the pull
   with a raw, uncaught exception instead of a bounded `ConnectorError`.
   Live-confirmed against the real host both ways: the fix's
   `urlencode`-built URL for `"procurement list additions"` returned HTTP
   200 with 20 real, on-topic results; the same term hand-built as a raw
   f-string interpolation, `urlopen`'d directly, raised exactly the
   predicted `InvalidURL` during live verification.
2. **The zero-match envelope is SMALL, not empty-`results`.** The documented
   (and live-confirmed) non-empty envelope is `{count, total_pages,
   next_page_url, results, description}`. A naive parser might assume a
   zero-match search returns the same five keys with `results: []`. It does
   not: a genuine zero-match search returns ONLY `{count: 0, description:
   ...}` -- `results`, `total_pages`, and `next_page_url` are ALL absent.
   A parser coded to "results must be a list, no exceptions" would raise
   `UPSTREAM_SCHEMA` on every legitimate zero-match search -- turning an
   honest "nothing matched your term" into a scary, wrong "the public data
   source returned an unexpected response" error. Live-reconfirmed with a
   deliberately-nonexistent term: the
   raw response body was exactly
   `{"description":"Documents matching '...', from Committee for Purchase
   From People Who Are Blind or Severely Disabled, and of type Notice",
   "count":0}`, and the shipped parser's `results absent + count == 0 ->
   legitimate empty result` branch handled it correctly, no exception
   raised.

## Decision

Add a new API connector, `connectors/federal_register.py`, mirroring
`census_acs.py` / `usaspending.py`'s `retrieve`/`parse`/`pull` split, plus a
new pure render module `pl_activity.py` (mirrors `pl_match.py` /
`radar_handoff.py`'s "LOCAL `_md` copy, caveat-first render" shape), with six
load-bearing choices.

1. **D1 -- one connector, page-1-only, newest-first, `per_page=20` pinned.**
   No pagination UI in v1. The stream is 3,070 total Commission notices as of
   this build; an analyst investigating a specific window can already narrow
   with the search term. Adding pagination is real UI/UX surface (a "load
   more" affordance, a page-state reuse-guard key, more manifest-notes
   complexity) that this slice's honest scope -- "surface the notice list,
   cited" -- does not need to justify. Cut; a future slice can add it if an
   analyst workflow demonstrates the need.
2. **D2 -- new `SourceKind.FEDERAL_REGISTER_NOTICES`, `Assurance
   API_RETRIEVED`.** Follows the `USASPENDING_AWARD`/`USASPENDING_SUBAWARD`
   precedent exactly: excluded from `WORKBOOK_SOURCE_KINDS` (this is a live
   API pull, never routed through the workbook scanner).
3. **D3 -- ONE canonical section-name string (audit correction).** An
   earlier draft let the section heading and the Section-ledger row name
   drift toward two similar-but-not-identical strings. Fixed: both are the
   literal string `"Procurement List activity (Federal Register)"`
   (`pl_activity.PL_ACTIVITY_SECTION_NAME`, imported by both the render
   module's own heading constant and `packet_export.py`'s ledger row), so
   the two can never silently diverge under a future edit. The Source
   manifest row uses the house live-source form,
   `"Procurement List activity (live, Federal Register)"` -- a THIRD,
   deliberately distinct string, matching every other manifest row's own
   `"<name> (live, <source>)"` convention (`"Contract Facts (live,
   USAspending award detail)"`, `"ACS geography context (Census, live)"`).
   Position: after R2b, before the always-last R2a map (mirrors R2b's own
   packet placement as the most recently-added optional evidence section
   before this one). Presence-gated exactly like R2b: rendered ONLY when the
   analyst pulled it (`pl_notices is not None`); a real, empty pull (0
   notices) still renders, since the analyst DID pull it.
4. **D4 -- the Section ledger grows to ELEVEN rows.** New row
   `"Procurement List activity (Federal Register)"`, absence basis `"No
   Federal Register pull attached."` (the pinned literal string,
   `pl_activity.PL_ACTIVITY_NO_PULL`). The Source manifest row's `notes`
   carry BOTH the truncation disclosure ("Showing the newest N of TOTAL
   total notices.") AND the search term (`'Search term: "..."'.`) when both
   apply to the same pull -- not either/or, since a truncated,
   term-narrowed pull is a common real state.
5. **D5 -- the R2a determination-support map does NOT consume notices in
   v1.** Routing a NATIONAL notice stream (not scoped to this contract's
   location, PSC, or any other identifying fact) onto one of the four
   suitability criteria would manufacture a connection this slice's evidence
   does not support -- the exact overclaim ADR-022 (§"What this slice
   deliberately does NOT do") already refused for `pl_matches` (R2b), for
   the identical reason: presence of a Commission notice, national or
   location-scoped, says nothing on its own about employment potential, NPA
   qualifications, delivery capability, or incumbent impact. Cut, recorded
   here rather than silently mirroring ADR-022's `pl_matches` omission.
6. **D6 -- UI: a 4th live-pull block under the R2b section, with a
   canonicalized reuse-guard (audit MAJOR).** An optional search-term text
   input plus a "Pull Procurement List activity (live)" button. The stored
   pull's reuse-guard key and the render-time compare key are BOTH computed
   as `(term or "").strip().casefold()` -- the identical expression on both
   sides, so `None`/`""`/whitespace-only all canonicalize to the same `""`.
   Without this, a no-term pull could accidentally attach to a term-search
   render (or vice versa) if the two sides used even slightly different
   blank-handling. The three "N independent analyst-initiated live requests"
   captions at `bd_page.py`'s Origin-intake docstring, the contract-facts
   caption, and the ACS-pull caption all go three -> four; the UI's own
   intake heading (`"#### Federal Register PL-notice pull"`) deliberately
   avoids reusing the packet body's real `"## Procurement List activity
   (Federal Register)"` section-heading text, mirroring the Staffing
   what-if intake/section pair's own established avoidance of the same
   `"####"`-contains-`"##"`-as-a-leading-substring containment-check
   collision (`bd_page.py`'s own comment on that precedent).

## The zero-match envelope contract (pinned)

`parse_pl_notices` recognizes exactly two live-probed envelope shapes and
fails loud (`ConnectorError("UPSTREAM_SCHEMA")`, no response-body echo) on
any deviation:

- **Non-empty:** `count` (a non-negative int) and `results` (a list of
  objects) are both present. Every result object's fields map to
  `FRNoticeRecord` with a missing/unknown field becoming an honest `None`
  (rendered "Not reported" at the presentation layer), never a fabricated
  placeholder.
- **Legitimate empty (the live-probed zero-match shape):** `count == 0` and
  `results` is ABSENT (not present-and-empty). This is a real, honest
  `PLNoticesResult(records=(), count_total=0, truncated=False, ...)`, never
  a schema fault.
- **Everything else fails loud:** `count` missing, non-int, or negative;
  `results` absent while `count != 0` (an envelope that claims a non-empty
  stream but supplies none); `results` present but not a list; any result
  entry that is not an object.

`truncated` is computed once, by the connector, as `count_total >
len(records)` -- never re-derived by the renderer. Because `len(records)` is
always `>= 0`, `count_total == 0` can never satisfy `> len(records)`, so
"showing the newest 20 of 0" is structurally impossible, not merely
avoided by a separate guard.

## What this slice deliberately does NOT do

- **No add/delete classification, no PL-line parsing from notice bodies.**
  The `documents.json` response this slice reads carries only the fields
  listed in §"Decision" above (title, document number, publication date,
  URL, type) -- never the notice's full text/body, which is a separate
  Federal Register endpoint out of scope for this slice. A title like
  "Procurement List; Proposed Deletions" is rendered exactly as the
  Commission wrote it; this codebase never infers which specific PL line(s)
  a notice adds or deletes.
- **No relevance matching, no score, no route.** A search term is
  explicitly labeled a text search, never a relevance determination, and
  no notice's presence is ever framed as evidence about the packet's
  specific contract unless the analyst draws that connection themselves.
- **No silent filtering of non-PL Commission notices.** The Commission's
  Federal Register stream also carries meeting notices and other
  non-Procurement-List items; this connector and renderer keep every one
  the API returns. Filtering them out would be an editorial judgment this
  slice has no basis to make silently.
- **No pagination, no caching layer** (D1).
- **No R2a map wiring** (D5).

## Alternatives considered

- **Copy `census_acs.py`'s raw f-string URL-builder style for the whole
  query, including the term:** rejected (the audit BLOCKER); safe for fixed
  codes, unsafe for analyst free text (see Context #1).
- **Treat `results` absent as always an error, requiring callers to special-
  case a zero-match search before calling `parse_pl_notices`:** rejected;
  that would push the live-probed envelope knowledge out to every caller
  instead of encoding it once, correctly, in the parser -- exactly the kind
  of knowledge a connector's `parse_*` function exists to own.
- **Add a page/pagination control in v1:** rejected (D1); real surface area
  with no demonstrated analyst need yet.
- **Route the notice list onto the R2a map's (a)(1) or (a)(4) criteria (a
  national stream "shows PL activity is ongoing"):** rejected (D5); the
  same overclaim ADR-022 already refused for the location-scoped `pl_matches`
  R2b evidence, and a NATIONAL stream is an even weaker basis for a
  criterion-labeled routing than a location-matched one.
- **Give the UI intake block the same `"#### Procurement List activity
  (Federal Register)"` heading as the packet's own section:** rejected (D6);
  live-caught during T3 by the very AppTest this slice added -- a `"####"`
  Markdown heading contains `"##"` as a leading substring, so the intake
  heading would have false-positived any `"## Procurement List activity
  (Federal Register)" in packet` presence/absence check run against the
  combined on-screen Markdown.

## Consequences

- The Opportunity Packet page now has FOUR independent analyst-initiated
  live network requests (contract facts, subaward records, ACS geography
  context, and Federal Register PL-notice activity); ADR-017:182 and
  ADR-019:181 both gained an inline "(four as of ADR-023)" clarifier rather
  than being rewritten (the Phase-3 precedent: fix stale inline literals in
  place, keep the historical ADR text otherwise intact).
- The Section ledger grows to ELEVEN rows (ADR-018's seven, ADR-019's eight,
  ADR-021's nine, ADR-022's ten, now ADR-023's eleven); `packet_export.py`'s
  three "ten" literals (module docstring, the ledger-derivation comment, and
  `derive_section_ledger`'s own docstring) and the fixed-order test's name
  and 10-name list were all updated in the same commit that added the row,
  matching the ten -> eleven twin the brief flagged.
- The Source manifest gains a live `API_RETRIEVED` row, `"Procurement List
  activity (live, Federal Register)"`, emitted whenever `pl_notices is not
  None`, with no live-supersession branch (nothing else in the packet
  supersedes a Federal Register pull).
- One live verification was performed under ADR-011's first-run rule: the
  agency slug, a plain page-1 pull, the zero-match
  envelope (with a fresh nonexistent term, not the original audit's term),
  a multi-word term pull, and the raw-space `InvalidURL` failure mode
  itself, all against the real `www.federalregister.gov` host.
- Automated coverage: 26 tests in the connector's own offline, socket-guarded
  suite (envelope validation for every documented failure mode, URL-encoding
  for multi-word/bracketed/Unicode terms, the zero-match legitimate-empty
  branch, never-echoes-body/term); the render module's own suite (caveat
  ordering, the three-state disclosure including the structural
  never-"newest 20 of 0" guarantee, search-term caveat presence, non-PL
  notice retention, newline-injection flattening); packet-level
  presence/absence/order/injection tests; ledger and manifest predicate and
  combined-order tests; one wired-button-only AppTest under the CI-parity
  `.venv` (streamlit 1.46.1).
