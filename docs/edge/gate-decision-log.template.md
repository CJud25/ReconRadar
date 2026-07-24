# EDGE — gate-decision log: capture template

Log every pursue / pass / watch call you make off an Opportunity Packet. One JSON
object per line, appended to `data/runtime/edge/gate_decisions.jsonl` (create the
folder if it does not exist). **Append only — never edit or delete a line.** To revise
a call, append a new `decision` line; to record how it turned out, append an `outcome`
line that references the `decision_id`. If you logged a `pursue` and later no-bid it
*before submitting a proposal*, do **not** stamp the pursue `lost` — append a superseding
`pass` line and resolve that one with `no_bid_confirmed`; the original pursue stays
outcome-less and is honestly excluded.

This log is calibration, not a scoreboard. It records the *team's* decision so we can
later check whether our stated confidence was honest — never who decides best. Naming a
decider is optional; the default is anonymous.

This log is internal and non-public. It never joins to any person, and the packet is
never changed by anything you write here — the packet stays a cited evidence sheet with
no score.

## Step 1 — when you make the call, append a `decision` line

Copy this skeleton, fill it, put it on ONE line, append it to the file:

```json
{"record_type":"decision","schema_version":"edge/v1","decision_id":"EDGE-YYYYMMDD-PIID-01","logged_at":"YYYY-MM-DDThh:mm:ss-04:00","piid":"","packet_export_filename":"opportunity-packet-PIID-YYYYMMDD.md","case_id":null,"supersedes_decision_id":null,"call":"pursue","pursuit_lane":"prime","confidence":{"p_win":0.3,"basis":"some_evidence"},"factors":[{"section":"eligibility_gate","stance":"favorable","weight":"major"}],"rationale":"","decider":null,"notes":null}
```

- **Keep people out of the free text.** `rationale` and `notes` name *companies* and *team aliases* only — never an individual's name. This log records "the team," never a person.
- `call`: `pursue` (commit B&P) · `pass` (decline as prime) · `watch` (monitor, re-evaluate at a trigger — put the trigger in `notes`).
- `supersedes_decision_id`: leave `null` for a fresh call (including a new recompete cycle on the same PIID). Set it to the earlier `decision_id` **only** when this line replaces that call (revised confidence, or a reversed pursue → superseding `pass`).
- `confidence.p_win`: your decision-time PWin *if pursued*, as a decile 0.1–0.9 (0.05/0.95 allowed at the extremes). `basis`: `gut` · `some_evidence` · `strong_evidence`.
- `factors[].section`: one of the packet's own sections — `origin_radar_handoff, eligibility_gate, contract_facts, capture_window, incumbent_teaming_leads, staffing_whatif, geography_acs, pl_crossref_r2b, pl_activity_fedreg, r2a_map` — or a factor the packet can't see: `customer_relationship, past_performance_fit, bnp_capacity, competitive_landscape`.
- `factors[].stance`: `favorable · unfavorable · blocking · informational` (`blocking` = a hard gate, e.g. an ineligible set-aside). `weight` (optional): `minor · major · decisive`.
- `pursuit_lane` (optional): `prime · sub · jv · undecided`. Use `sub`/`jv` to log "no-bid as prime, pursue as teammate."
- `decider` (optional, opt-in): `{"alias":"bd","consent":true}` using a **team** alias only (bd/business_development/capture/compliance/operations/research/admin) — never a name, never a role. **Record it only for your OWN call** — never fill in a decider about someone else's decision. Leave `null` to stay anonymous (the default).

## Step 2 — later, when you learn how it turned out, append an `outcome` line

```json
{"record_type":"outcome","schema_version":"edge/v1","outcome_id":"EDGE-OUT-YYYYMMDD-01","decision_id":"EDGE-YYYYMMDD-PIID-01","logged_at":"YYYY-MM-DDThh:mm:ss-04:00","outcome":"won","outcome_date":"YYYY-MM-DD","outcome_basis":"public_award_record","note":null}
```

- `outcome`: `won · lost · cancelled_no_award · no_bid_confirmed · not_pursued · still_open · unknown`. Only `won`/`lost` on a pursued bid feed calibration; `cancelled_no_award` = pursued but nobody got the award (cancelled/bridged/insourced); `no_bid_confirmed` = your `pass` stood; `not_pursued` = a `watch` that lapsed; `still_open` = known-unresolved; `unknown` = lost track / cannot determine. Use `still_open`/`unknown` honestly — the future read excludes everything but `won`/`lost` rather than guessing.
- `outcome_basis`: `public_award_record` (a successor award you can cite — the best kind) · `analyst_knowledge` · `agency_confirmation`.

See `docs/edge/gate_decisions.example.jsonl` for a filled, worked pair, and
`docs/edge/GATE_DECISION_LOG.md` for the full schema and the future-calibration spec.
