# ADR-019: The Radar handoff is an uploaded claim, gated onto the packet tab

## Status

Accepted for the A2 radar-handoff-intake slice

## Date

2026-07-21

## Context

The roadmap's literal wording for this phase ("JSON schema -> `create_case`")
predates the cited Opportunity Packet surface. `cases.py` is a location-scoped
scanner-workflow store keyed on city/state with a Draft -> Scanning -> ...
lifecycle (`cases.py:128-136`); it does not model a contract-scoped
opportunity, and every packet slice since A1 (R2b, the Eligibility Gate, live
Contract Facts, the Capture Window, A5 leads, A7 export) has deliberately been
packet-local and non-persisted, matching AGENTS #14 ("SQLite persistence is a
local, unencrypted, unauthenticated pilot store"). Writing a handoff into
`create_case` would be the first packet slice to persist anything, and would
persist it into a store built for a different shape of record.

Meanwhile GovConRadar (a separate, already-shipped repo:
`CJud25/GovConRadar`) is exactly the kind of source an analyst would want to
hand off FROM: it already screens and ranks recompete signals. An analyst
who finds a promising opportunity in Radar and wants to build a cited packet
for it today has to re-type the PIID and place by hand. A2 closes that gap
with the smallest artifact that can cross a process boundary without
crossing a trust boundary: a versioned JSON file the analyst downloads from
Radar and uploads here.

The central risk is not technical, it's epistemic: GovConRadar is a screening
tool over public award data, and a screened candidate is not the same thing
as a confirmed opportunity. If a Radar claim (a NAICS code, a set-aside
guess, an obligated amount) crossed into this packet looking exactly like
this packet's own retrieved facts, the packet would silently inherit Radar's
confidence level without inheriting Radar's caveats -- the same
provenance-blending risk every other packet slice (R2b, the gate, the leads
section) already guards against by labeling every fact with where it came
from and how sure that source is.

## Decision

A2 lands on the packet tab as a pure, offline parser plus a UI intake, with
nine load-bearing choices.

1. **D1 -- packet tab, not `create_case`.** The handoff is a NEW section on
   `bd_page._render_opportunity_packet`, not a write to the case store. This
   deviates from the roadmap's literal wording (`create_case`) for the
   reasons in Context above; it keeps A2 consistent with A1/R2b/A5/A7's own
   precedent of packet-local, non-persisted evidence, and avoids building a
   persistence shape for a record type `cases.py` was never designed to hold.

2. **D2 -- prefill set is retrieval inputs only.** Exactly four fields
   prefill: `op_packet_piid`, `op_packet_county`, `op_packet_state`,
   `op_packet_worksite_city`. These are inputs TO retrieval/matching (what to
   look up), never evidence themselves. Nothing else auto-populates --
   critically, `type_of_set_aside_code` is never written into
   `op_packet_set_aside`, which would launder a Radar guess into
   "analyst-entered" and feed it straight into the Eligibility Gate.

3. **D3 -- the Origin section renders FIRST.** Immediately after the
   header/framing lines and before the Eligibility Gate, because it explains
   WHERE this packet's target came from before any evidence about the target
   itself. The Section-ledger row becomes row 1 of eight (ADR-018's ledger is
   "always in packet order").

4. **D4 -- no field-by-field drift diff in v1.** A table comparing the
   handoff's claimed obligated amount against a live-retrieved obligated
   amount would elevate the handoff into a second source of truth and
   manufacture expected noise (obligated amounts move daily; a diff would
   "diverge" on every re-pull even when nothing is wrong). Instead there is
   ONE standing line, rendered only when live Contract Facts are attached:
   live values govern, snapshot claims are context. A real diff view is
   real future work once there is a concrete reason to want one, logged
   below as a cut.

5. **D5 -- no `SourceKind`/`Assurance` enum change.** The handoff is not
   connector-routed: it never goes through `WorkbookConnector.parse`, never
   gets a `SourceKind`, and is not scanned by anything in `scanner.py`. It is
   a packet-local pure parse, exactly like `pl_match.py` consuming an
   already-parsed workbook. The Source-manifest row it earns uses the
   literal string `USER_ATTESTED` the manifest already uses for every other
   analyst-supplied source (the typed set-aside, the PL workbook, the NPA
   directory) -- there is no new provenance CONCEPT here, just a new row.

6. **D6 -- versioned schema, fail closed.** `schema_version` must equal
   `"radar-handoff/v1"` exactly; anything else is a fixed-message parse
   error, never a best-effort partial parse. This is the same posture the
   codebase already takes toward `SourceKind`/`Assurance` coercion
   (`connectors/base.py`'s `coerce_source_kind`): an unrecognized shape is
   refused, not guessed at. Unknown FIELDS (not unknown schema versions) are
   the opposite case -- forward-compatibility noise, not a parse failure --
   so they are ignored but counted, and the Origin section discloses the
   count ("N unrecognized field(s) ignored") so the analyst can tell the
   parse was lossy without the parse having to fail over it.

7. **D7 -- the export layer takes richer inputs than the builder.** The
   builder receives one value, `radar_handoff: RadarHandoff | None`, already
   PIID-gated by `bd_page` -- it has no way to distinguish "no handoff" from
   "a handoff attached but no longer PIID-matched" from a single `None`. The
   Section ledger needs to tell those two absences apart (an honest ledger
   describes WHY a section is missing, not just THAT it is), so
   `derive_section_ledger` takes the two booleans directly:
   `handoff_attached` and `handoff_piid_matched`, both keyword-only and
   defaulted `False` so no existing caller breaks. `derive_source_manifest`
   takes the richer `handoff: RadarHandoff | None` (for `snapshot_date` and
   `synthetic_sample`) plus `handoff_source_label` (the filename/sample
   label, carried through session state exactly as `directory_source_label`
   already is -- the parsed dataclass itself carries no filename) plus
   `handoff_piid_matched`, and emits its row only when attached AND
   matched -- the same phantom-source rule the directory manifest row
   already follows (`packet_export.py`, ADR-018 item 3).

8. **D8 -- a bundled SYNTHETIC sample.** `scripts/make_sample_radar_handoff.py`
   generates `data/samples/sample_radar_handoff.json` and a "use the bundled
   SYNTHETIC example" checkbox mirrors the R2b upload pattern
   (`bd_page.py:782-786` pre-A2) exactly. The sample PIID (`SYNTH-A2-0001`)
   is obviously fake, `synthetic_sample: true` renders a loud note in both
   the Origin section and the manifest notes, and its `type_of_set_aside_code`
   is deliberately `null` (not merely absent) so the bundled example
   exercises the "not reported in snapshot (null)" render path -- the one
   claim in this schema closest to the Eligibility Gate's own honesty
   discipline -- out of the box, without requiring a hand-crafted test fixture
   to see it demoed.

9. **D9 -- PIID-match gating, strip-only.** The Origin section (and its
   ledger/manifest rows) render only while the packet's CURRENT PIID input
   equals the handoff's claimed PIID, compared with `.strip()` on both sides
   and no casefold -- exactly mirroring the live-facts reuse-guard at
   `bd_page.py:583`. The parser stores the handoff's `piid` VERBATIM (not
   pre-stripped), so the prefill writes the exact handoff value and the gate
   only breaks on an actual analyst edit to the PIID field, never on parser
   normalization. Retargeting the packet to a different contract silently
   drops the Origin section -- the same "dropping context is the safe
   direction" philosophy every other stale-result reuse-guard on this page
   already holds (`bd_page.py:580-586, 659-666, 743-750, 840-850`).

## Alternatives considered

- **Write the handoff into `create_case` (the roadmap's literal wording):**
  rejected (D1); `cases.py` is a location-scoped scanner-workflow store with
  a Draft -> Scanning lifecycle, not a contract-scoped opportunity record,
  and persisting the handoff would be the first packet slice to persist
  anything at all -- a much bigger change than "let an analyst carry one
  opportunity across a tab boundary" requires.
- **Prefill the analyst set-aside input from the handoff's
  `type_of_set_aside_code`:** rejected (§1.1/D2); this would launder a
  Radar claim into "analyst-entered" and feed it directly into the
  Eligibility Gate, which is exactly the failure mode the "never feeds any
  assessment" invariant exists to prevent.
- **Render a field-by-field drift diff between the handoff's claims and live
  Contract Facts:** rejected (D4); manufactures expected noise (obligated
  amounts and dates legitimately move) and elevates a snapshot claim into a
  second source of truth. One supersession line instead; a real diff is
  logged as future work.
- **Route the handoff through the existing connector layer
  (`WorkbookConnector`/`SourceKind`):** rejected (D5); the handoff is not a
  workbook, is not scanned, and adding a `SourceKind` member for a
  packet-local pure parse would blur the line `connectors/base.py`'s own
  docstring already draws around API-retrieved vs. workbook-routed kinds.
  `pl_match.py`'s own precedent (consume already-parsed records, no
  connector of its own) is the closer analogy.
- **Best-effort parse an unrecognized `schema_version` (skip unknown
  top-level shape and try anyway):** rejected (D6); a schema is a contract,
  and guessing at an unrecognized version risks silently misreading a future
  Radar export shape as this one. Fail closed with a fixed message instead;
  unknown FIELDS (a different, additive case) are still tolerated and
  counted.
- **A Radar-side producer script/endpoint in this repo:** out of scope; A2 is
  the consumer half only. Building the emitter belongs in the `GovConRadar`
  repo as separate follow-up (its own PIID-based award lookup already knows
  the shape of the source data this schema would export).

## Consequences

- The Opportunity Packet tab gains a fourth optional evidence input
  (alongside the analyst-typed set-aside, the directory upload, and the PL
  workbook) that is explicitly NOT a live network pull -- the page's
  existing "three independent analyst-initiated live requests" captions
  (`bd_page.py`) remain literally true; the handoff adds no live request
  (four as of ADR-023).
- The Section ledger grows from seven fixed rows to eight (ADR-018 updated
  with a dated note and its own stale "seven" corrected in place, matching
  the Phase-3 precedent on ADR-010 of correcting stale inline literals).
- The schema PARSES more claim fields than the Origin section RENDERS:
  `referenced_idv_piid`, `awarding_subagency`, `extent_competed_code`, and
  `number_of_offers_received` are validated and available on
  `RadarHandoffClaims` but deliberately not rendered, keeping the Origin
  block terse and visually distinct from the live-retrieved Contract Facts
  block that asserts those same facts WITH citations (rationale in
  `radar_handoff.py`'s module docstring). A future version may render them;
  accepting them now keeps `radar-handoff/v1` stable for the Radar-side
  producer.
- A future structured JSON packet-payload EXPORT (distinct from this JSON
  handoff INTAKE) remains real future work, as ADR-018 already flagged --
  this slice does not build one.
- A Radar-side producer for `radar-handoff/v1` is real future work in the
  `GovConRadar` repo; this repo only ever needs to keep consuming the
  version(s) it declares support for.
- Automated coverage is fully offline and deterministic: the parser is pure
  (no network, no clock, no filesystem beyond the caller-supplied bytes) with
  test vectors for every required-field failure, wrong types, null vs.
  absent semantics, unknown-field counting, the two hard size/length caps,
  Markdown-injection escaping, and the PIID-match gate's drop-out behavior;
  the UI wiring is covered by AppTest through the bundled-sample
  checkbox+button path (verified green under both system streamlit and the
  CI-parity `.venv` pin, streamlit 1.46.1, where `file_uploader` is
  unreachable by AppTest).
