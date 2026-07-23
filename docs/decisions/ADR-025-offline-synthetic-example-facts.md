# ADR-025: The bundled synthetic PIID resolves into honestly-labeled offline Contract Facts

## Status

Accepted for the product-legibility one-shot

## Date

2026-07-23

## Context

The offline guided demo's flagship moment — the Contract Facts + Eligibility
Gate + Capture Window sections populating from a real pull — could not be
reached without a network connection. The bundled synthetic Radar handoff
(`data/samples/sample_radar_handoff.json`, PIID `SYNTH-A2-0001`) prefills the
packet's retrieval inputs, but clicking "Pull contract facts (live)" against
that made-up PIID with no network either hung on a socket-guard failure in
tests or, live, returned `AWARD_NOT_FOUND`/`UPSTREAM_UNAVAILABLE` — an
honest but unresolved red box, not a flagship moment (§5.3 / §15-#3).

The fix must not weaken any evidence/citation-discipline invariant this
codebase enforces everywhere else: every packet fact carries a source URL,
retrieval timestamp, and assurance label, and `Assurance.API_RETRIEVED` means
exactly one thing — a real live retrieval. A resolvable offline PIID that
silently *looked* like a live pull would be a worse defect than the red box
it replaces: a plausible-looking fabrication is more dangerous than an honest
failure (the same reasoning ADR-017/ADR-021 already apply to computed
numbers).

## Decision

Serve a bundled, invented, unmistakably-SYNTHETIC award record for the
single PIID `SYNTH-A2-0001`, honestly labeled across all three surfaces the
packet exposes — never `API_RETRIEVED`, never a live award URL — never
resembling a real retrieval anywhere it appears.

1. **A committed fixture, not test-fixture reuse (Finding drift #2).**
   `data/samples/sample_usaspending_award.json` is a new, award-detail-shaped
   JSON authored by copying the STRUCTURE of
   `tests/fixtures/usaspending_award_detail_set_aside.json` and replacing
   every value with invented content: recipient "SYNTHETIC EXAMPLE SERVICES
   LLC", obligated `180000` kept distinct from ceiling `420000` (matching the
   bundled handoff's own claims), place Denver/CO/USA, potential end date
   `2028-05-31 00:00:00`, PIID `SYNTH-A2-0001`. Shipping under `data/samples/`
   (not `tests/`) means it survives `.dockerignore` and never couples
   `src` to the test tree.
2. **A `synthetic_example: bool = False` flag on `ContractFactsRecord`**
   (default-False, so every existing keyword-based construction — parser,
   tests — stays valid unchanged) is the single source of truth every
   downstream renderer switches on. It also round-trips through
   `to_public_payload()`.
3. **`load_synthetic_example_facts()`** (`connectors/usaspending.py`) reads
   the bundled JSON, builds a `RetrievedPayload` whose `source_uri` is an
   honest, non-URL marker string ("bundled SYNTHETIC example (offline) — not
   a live USAspending retrieval") rather than a `usaspending.gov` URL, parses
   it through the same `parse_contract_facts` a live pull uses, then marks
   the result `synthetic_example=True`. No network call is made; this
   function is exercised by the existing autouse socket guard exactly like
   every other offline path in this codebase.
4. **Three independent honesty surfaces, all switched together.** A record
   is invisible in one place and mislabeled in another is worse than
   invisible everywhere, so all three had to change in the same commit:
   - **Packet body** (`opportunity_packet.py`): the Contract Facts heading
     and provenance line switch to "SYNTHETIC example — offline, not a live
     retrieval" / "does not carry an API_RETRIEVED assurance label" when the
     flag is set -- deliberately worded so the literal substring "Assurance
     API_RETRIEVED" never appears in that section, letting the honesty test
     be a clean substring ban rather than relying on a human to parse a
     negation correctly.
   - **Section ledger** (`packet_export.py::_contract_facts_live_row`): the
     synthetic row is named "Contract Facts (SYNTHETIC example)" with a basis
     deliberately worded without the token "live" anywhere, so a reader (or a
     test) can ban that token as a clean substring check. The row the
     ledger emits when a REAL record is attached, or when none is attached,
     is byte-for-byte unchanged.
   - **Source manifest** (`packet_export.py::derive_source_manifest`): a new
     `SYNTHETIC_EXAMPLE` assurance constant (added as a third permitted value
     alongside `API_RETRIEVED`/`USER_ATTESTED`) labels the synthetic row;
     its `reference` is the same non-URL marker, never a live award URL. The
     manifest row for a real record is unchanged.
5. **Wired to exactly one PIID.** `bd_page.py`'s "Pull contract facts (live)"
   handler checks `piid.strip() == SYNTHETIC_EXAMPLE_PIID` (a module
   constant, `"SYNTH-A2-0001"`, re-exported from `connectors`) BEFORE calling
   the network function; only that exact PIID takes the offline branch, with
   a distinct success message ("Loaded the bundled SYNTHETIC example contract
   facts (offline) — not a live retrieval."). Every other PIID's live path is
   unchanged in observable behavior: `resolution.record.synthetic_example` is
   `False` by default for any real parsed record, so the original "Attached
   live USAspending contract facts." message and the original
   `pull_contract_facts` call are exactly what still runs.

## Alternatives considered

- **Reuse an existing `tests/fixtures/` USAspending JSON at runtime**
  (report §12.1's original suggestion): rejected (Finding drift #2) —
  `tests/` is excluded by `.dockerignore`, so this would break the built
  container, and importing test fixtures from `src` at runtime is exactly
  the src→tests coupling this codebase's connector modules otherwise avoid.
- **Label the synthetic record as a lower-confidence live retrieval instead
  of a distinct third state** (e.g. keep `API_RETRIEVED` with a caveat):
  rejected — `Assurance.API_RETRIEVED` means "a live pull happened" every
  other place it appears in this codebase; reusing it for a fixture read
  would be the exact half-truth this ADR exists to prevent.
- **Leave the Section ledger's row name/basis unchanged (only fix the body
  and manifest):** rejected — the ledger sits one row above the manifest in
  the same export; a reader comparing them would see the ledger claim "Live
  USAspending contract-facts pull attached" one row above a manifest row
  honestly labeled `SYNTHETIC_EXAMPLE` — a self-contradicting document,
  exactly the class of defect ADR-024 fixed on the governance page.
- **Skip the honest fallback and leave S11's inline reconciliation as the
  final state (the plan's documented descope switch):** not needed — the
  honesty tests below landed clean across all three surfaces without
  touching any existing assertion.

## Consequences

- Following the in-app guided demo offline (tick the bundled handoff → Use
  handoff → Pull contract facts (live)) now reaches a populated, clearly-
  SYNTHETIC Contract Facts + Eligibility Gate + Capture Window render with no
  red error, using only the bundled synthetic PIID.
- `ContractFactsRecord` gains one field; every other connector and packet
  code path that constructs or reads it is unaffected because the field
  defaults to `False` and only three render sites branch on it.
- The Source manifest's `assurance` set grows from two values to three
  (`API_RETRIEVED`, `USER_ATTESTED`, `SYNTHETIC_EXAMPLE`); no existing test
  asserted the set was closed to two, so this is additive, not a breaking
  change to the export contract.
- Automated coverage: an offline unit test on `load_synthetic_example_facts`
  (resolved, `synthetic_example is True`, obligated distinct from ceiling,
  `source_url` contains neither `usaspending.gov` nor `api.usaspending`); a
  packet-body test asserting the SYNTHETIC heading/provenance render (and
  that a normal record's live heading is unchanged); a Section-ledger test
  asserting the synthetic row's name and basis both exclude the substring
  "live" (and that a real record's row is unchanged); a manifest test
  asserting the synthetic row's assurance is `SYNTHETIC_EXAMPLE` with no live
  award URL in `reference` (and that a real record's row is unchanged); and
  an `AppTest` driving the real widgets offline (handoff → Pull contract
  facts (live)) to confirm no `app.exception` and a populated, labeled
  render through the actual UI.
