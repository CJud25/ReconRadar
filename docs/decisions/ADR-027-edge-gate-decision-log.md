# ADR-027: EDGE is an append-only gate-decision log, external to the packet, for calibration not attribution

## Status

Accepted for the EDGE gate-decision-log kit (log kit + future-app spec; no calibration app built)

## Date

2026-07-24

## Context

The Opportunity Packet equips a human pursue/pass call but deliberately makes
none (N1: no score/ranking/bid-no-bid). Those human calls are today
unrecorded, so the team can never check whether its stated confidence is
honest or which factors actually carry. EDGE ("Evidence-Driven Gate
Evaluation") is the capture lifecycle's "learn" stage: log the call +
factors + decision-time confidence now so a corpus accrues; the calibration
read comes only after real decisions exist. Two settled constraints frame
the design: **corpus before app** (build the habit, not the UI) and
**calibration, not a leaderboard** (aggregate, opt-in, never rank people).

## Decision

1. **Append-only two-record event log (`decision` + `outcome`), JSONL.** The
   outcome is a separate appended line, so nothing legitimate ever edits a
   decision line -- removing the hindsight-revision path that would corrupt
   calibration. At pilot scale this immutability is a discipline
   (append-only by convention on a hand-appended, gitignored file), enforced
   technically only when a future append/validate helper arrives; the
   design's contribution is removing any *reason* to edit. Matches the
   house append-only discipline. (Ref `docs/edge/GATE_DECISION_LOG.md` §2.1.)
2. **EDGE is external to the packet -- no contamination.** Nothing EDGE
   captures feeds back into `opportunity_packet`; the packet stays a cited
   evidence sheet with no score. A source-sweep test proves no packet-side
   module references the log (`tests/test_edge_boundary.py`). The log
   records the human's call *after*, and *about*, the packet -- never
   inside it.
3. **Confidence is a decision-time subjective PWin in [0,1] (`p_win`), plus
   a `basis` band.** This is the calibration key. Recorded as deciles
   (bands not points).
4. **Factors use a controlled vocabulary grounded in the packet's real
   sections**, plus a separate, honestly-labeled set of non-packet capture
   factors (relationship, past-perf fit, B&P capacity, competitive field)
   that public data cannot see -- so the future read can tell
   packet-evidenced factors from analyst-brought ones.
5. **Decider is opt-in, a controlled TEAM alias only (never a role alias --
   1:1 with a person at pilot scale -- never a person id), self-recorded,
   aggregate-only, and never a segmentation dimension (no leaderboard,
   structurally).** Reuses `cases.py`'s controlled-alias rule so the log
   cannot become an employee directory; the future read never cuts on
   `decider`.
6. **Corpus before app: no calibration read is built now.** The future
   read is *specified* (`docs/edge/GATE_DECISION_LOG.md` §6) so the schema
   captures the right fields today, but no UI/analysis ships in this
   slice.
7. **The corpus is an internal, non-public store**, gitignored under
   `data/runtime/edge/`, distinct from the packet's public-data-only rule
   (see Consequences). ADR-027 and the spec docs are governance docs and
   may ship to the public mirror; the corpus never does.

## Alternatives considered

- *Fold a computed pursuit/PWin score back onto the packet:* rejected --
  violates N1 and the whole point of EDGE (log the human's call, don't make
  one).
- *One editable row per decision (CSV/spreadsheet):* rejected -- an
  editable confidence can be silently revised after the outcome, destroying
  calibration honesty; and CSV invites formula injection and cannot hold
  the `factors[]` array.
- *Attribute and rank deciders ("who calls best"):* rejected -- the settled
  decision is calibration-not-attribution; ranking people is explicitly
  out, forever.
- *Build the calibration app now:* rejected -- corpus before app; with zero
  decisions logged a reliability curve would be fabricated precision
  (govcon rule: "directional only -- load more data").
- *A new SQLite table in the case ledger:* rejected for this slice -- it
  re-introduces the "build a writer/app" problem this slice defers; a
  hand-appended JSONL is right at pilot scale, and a future EDGE writer is
  the natural first app increment.

## Consequences

- The packet surface is byte-unchanged; N1 remains true and is now guarded
  by an all-sections-populated no-score test.
- A per-opportunity logging habit is added to the pilot runbook (step 11).
- A future calibration read has an exact field contract to compute against
  and cannot ask the log for a field it never captured.
- **Two distinct data governances now coexist and must not be conflated:**
  the *packet* is public-organizational/contract data only, no person-level
  data (its public-mirror rule); the *EDGE corpus* is an internal,
  non-public pilot store that may name a decider only by an opt-in
  controlled TEAM alias, self-recorded, and never segmented on. Neither
  ever joins to a person. Real (non-pilot) use of the corpus requires the
  same production controls the SQLite ledger does (retention,
  authorization, audit -- `PRIVACY_AND_GOVERNANCE.md`); noted as future
  work.
