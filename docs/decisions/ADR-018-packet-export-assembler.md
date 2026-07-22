# ADR-018: The packet export is a composed cited document, never a re-derivation

## Status

Accepted for the A7 packet-export-assembler slice

## Date

2026-07-20

## Context

The Opportunity Packet tab today downloads the raw on-screen Markdown body
under a fixed filename (`opportunity-packet.md`). The house's real
cited-export discipline lives elsewhere, in `bd_page._render_assessment`'s
export block: an as-of stamp, non-claim disclaimers, and a `## Source
manifest` table with pipe-escaped cells. Roadmap A7 ("Packet
assembler/export -- compose sections; extend the existing cited export")
asks for that same discipline on the packet download, without touching the
assessment surface it is modeled on.

Two honesty risks are specific to an export that ADDS content around an
existing rendered document, beyond the general N1/N2 packet-not-score
invariants:

* An appendix that restates a packet fact in different words than the body
  is a drift risk -- two descriptions of "the same" fact can quietly
  diverge over time, and a reader has no way to tell which one is current.
* A ledger row's included/not-included state, if computed by
  string-searching the rendered body Markdown, would silently break the
  moment a heading or bullet wording changed elsewhere -- a fragile, hidden
  coupling between prose and structure.

## Decision

Add a pure `packet_export.py` module (mirrors `capture_window.py` /
`incumbent_leads.py`) that composes around `build_opportunity_packet_markdown`
without re-deriving anything it already computed, with five load-bearing
choices.

1. **Body-verbatim, never restated.** The export embeds the packet body
   returned by `build_opportunity_packet_markdown` as an exact substring,
   unmodified. The appendices reference SECTIONS and SOURCES ("Contract
   Facts (live) -- included"), never a packet FINDING ("the recipient is a
   small business") -- that eliminates the drift risk structurally: there is
   only ever one place a fact is stated.

2. **The Section ledger is structural, never parsed from the rendered body.**
   `derive_section_ledger` takes the same typed inputs the packet builder
   receives (`eligibility`, `contract_facts`, `geography`, `pl_matches`,
   `subawards`, `directory_agency_names`) and derives each of the eight
   (originally seven; extended by ADR-019) fixed D3 rows' included-state
   from THOSE, in the same order every time.
   No string search of the body markdown exists anywhere in this module.
   The gate row carries a pinned predicate from the zero-context brief audit:
   `included = eligibility is not None OR contract_facts is not None`,
   because the builder (`opportunity_packet.py:256-279`) recomputes the gate
   from `contract_facts.set_aside_code` and ignores a `None` eligibility once
   live facts are attached -- the ledger must read the SAME way the body
   actually rendered, not the way a naive "was eligibility passed" check
   would read it.

3. **D1/D2 cuts, with the JSON sidecar named as future work.** This slice
   ships one Markdown document only -- no JSON sidecar, no PDF, no zip (D2).
   A structured JSON packet-payload export is real future work adjacent to a
   future A2 Radar-handoff slice (the ledger/manifest dataclasses already
   have the shape a JSON export would serialize), but is out of scope here;
   building it now would be speculative given no consumer exists yet. The
   ledger and manifest render ONLY in the downloaded file, never as new
   on-screen widgets (D1) -- a single `st.caption` under the download button
   says the export includes them, so the on-screen packet render is
   unchanged.

4. **Filename sanitization is a character allowlist, not a blocklist.**
   `packet_export_filename` filters the PIID to `[A-Za-z0-9._-]` (every other
   character becomes `-`), collapses runs, trims leading/trailing `-`/`.`,
   and caps the result at 40 characters (re-trimmed after the cap, so a cut
   can never leave a bare trailing separator), falling back to `no-piid` when
   nothing survives. An allowlist is chosen over blocking specific hostile
   characters (`/`, `..`, etc.) because an allowlist cannot be bypassed by a
   character the author didn't anticipate; a PIID is analyst-pasted text and
   this slice treats it exactly as hostile as any other web-facing filename
   input. `as_of` is a REQUIRED parameter (no default): the module never
   calls `datetime.now()` / `date.today()` internally, matching
   `capture_window.py`'s determinism discipline.

5. **Assurance rows tell the truth about who attested what.** Every Source-
   manifest row is either `API_RETRIEVED` (a live pull: Contract Facts,
   subawards, ACS geography) or `USER_ATTESTED` (an analyst upload or typed
   value: the NPA directory, the PL Services workbook, a typed set-aside).
   The synthetic PL sample carries an explicit "SYNTHETIC example workbook --
   not real Procurement List data" note (mirrors the R2b renderer's own
   `EXAMPLE DATA` labeling); a truncated subawards pull carries the same
   "more records exist" note the on-screen leads section already uses. The
   analyst-typed set-aside earns its OWN manifest row only under a second
   pinned predicate: `contract_facts is None AND set_aside_value.strip()` --
   a blank typed field is not an attached source (the gate's resulting
   UNKNOWN state is section behavior, not a source), so it must not appear
   as one.

`_render_assessment` (D4) is untouched. "Extend the existing cited export"
means the packet download adopts the assessment export's citation
discipline -- an as-of stamp, non-claim disclaimers, a manifest table with
pipe-escaped cells -- not that the assessment surface's own code changes;
the two exports remain independent renderers over independent case shapes.

## Alternatives considered

- **Derive the Section ledger by searching the rendered body Markdown for
  each section's heading:** rejected; this is exactly the fragile,
  string-search coupling D3 warns against -- a heading-text change anywhere
  in `opportunity_packet.py` would silently break the ledger with no type
  error, and the ledger would tell the truth about the RENDER rather than
  about the EVIDENCE that produced it.
- **Restate each packet finding in the appendices in a shorter form (a
  "summary" ledger):** rejected; any restatement is a second copy of a fact
  that can drift from the body's own wording, and the roadmap explicitly
  scopes this slice to composition, not new analysis (N1/N2).
- **Bundle a JSON payload alongside the Markdown this slice (a zip
  download):** rejected (D2); no consumer for a structured payload exists
  yet, and shipping one speculatively is scope creep on a slice about
  extending an existing citation discipline, not building a new interchange
  format. Recorded as future work above.
- **Block a specific hostile-character set (`/`, `\`, `..`) in the
  filename instead of allowlisting:** rejected; a blocklist only stops
  characters its author thought of, and a PIID is untrusted analyst-pasted
  text -- the same allowlist-over-blocklist reasoning the codebase already
  applies to Markdown escaping (`_MD_ESCAPE`'s narrow, deliberate character
  set) applies here too.
- **Give the analyst-typed set-aside a manifest row whenever a value is
  typed, regardless of whether the gate used it:** rejected; once live
  Contract Facts are attached, the analyst-typed value is COSMETIC (the
  gate no longer runs off it) -- manifesting it as an attached source would
  mislabel dead input as live evidence.
- **Let `assemble_packet_export` compute `as_of` internally (default
  `datetime.now(timezone.utc)`):** rejected; the whole point of this slice is
  that the body's "As of" stamp and the export header's stamp must always
  agree, which is only guaranteed if the SAME caller-resolved value feeds
  both the builder and the assembler -- an internal default would silently
  reintroduce the two-clocks bug this slice exists to close.

## Consequences

- The packet download filename now encodes the PIID and the export date
  (`opportunity-packet-{piid}-{YYYYMMDD}.md`) instead of a fixed
  `opportunity-packet.md`, so successive exports for different awards no
  longer collide or silently overwrite each other in a downloads folder.
- `bd_page._render_opportunity_packet` now resolves ONE `packet_as_of`
  per render and threads it to both `build_opportunity_packet_markdown` and
  the assembler; the previous call site's missing `as_of` (which silently
  defaulted to a second, later `datetime.now()` inside the builder) is
  fixed as part of this wiring.
- No score, tier, rank, or directive vocabulary is introduced; the ledger
  and manifest describe sections and sources only, never findings.
- A future JSON packet-payload export (A2-Radar-handoff-adjacent) has a
  natural home once a real consumer exists: `SectionEntry`/`SourceEntry` are
  already flat, serializable dataclasses.
- Automated coverage remains fully offline and deterministic: every render
  is driven by an explicit `as_of`, with test vectors for the all-absent
  render, the everything-attached render, the analyst-only-gate render, the
  two pinned predicates, hostile-filename/label/PIID escaping, and the
  filename sanitizer's boundary cases.

## Update (2026-07-20, same slice): adversarial-verification corrections

Three findings from the slice's adversarial verification were folded in before
shipping:

1. The module's `_md` flattens line boundaries to spaces before escaping — an
   uploaded filename may legally contain a newline, which split a Source
   manifest table row (structural injection in single-line contexts).
2. The Geography ledger row is always **Included**: the packet builder renders
   that section unconditionally (as an honest placeholder when nothing was
   retrieved), so a "Not included" row misdescribed the document itself. The
   basis distinguishes retrieved context from the placeholder.
3. The directory manifest row requires attached contract facts — without them
   the leads section never renders, so the upload contributed nothing and
   listing it would cite a phantom source.

## Update (2026-07-21): the Section ledger grows an eighth row

A2 (the Radar-handoff intake, ADR-019) adds an Origin (Radar handoff) row as
row 1 of the Section ledger and, when the handoff is attached AND PIID-
matched, a corresponding Source-manifest row. This is an EXTENSION of this
ADR's design, not a reversal: `derive_section_ledger` gains keyword-only
`handoff_attached` / `handoff_piid_matched` booleans (defaulted `False`, so no
existing caller breaks) instead of the already-gated `RadarHandoff | None`
the builder receives, because with only the gated value the ledger cannot
tell "no handoff" and "a handoff whose PIID no longer matches" apart —
the same audit-finding shape D2/§3 of this ADR already applies to the gate
row. `derive_source_manifest` gains `handoff`, `handoff_source_label`, and
`handoff_piid_matched` and emits its row only when attached AND matched,
mirroring the directory row's phantom-source rule (item 3 above) exactly.
See ADR-019 for the handoff's own design (D1-D9).
