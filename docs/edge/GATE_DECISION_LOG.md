# EDGE -- gate-decision log: canonical schema (`edge/v1`)

EDGE ("Evidence-Driven Gate Evaluation") is the capture lifecycle's "learn"
stage. It logs the human's pursue/pass/watch call made *after* an
Opportunity Packet -- the call, the decision-time confidence, and the
factors behind it -- into a durable, append-only, machine-parseable corpus,
so that once enough decisions accrue a future read can check whether the
team's stated confidence was honest and which factors actually carried.

This document is the authoritative field reference for `edge/v1`. See
`docs/decisions/ADR-027-edge-gate-decision-log.md` for the decision record,
`docs/edge/gate-decision-log.template.md` for the analyst-facing capture
template, and `docs/edge/gate_decisions.example.jsonl` for a worked example.

**What EDGE is not:** no scorer, no ranking, no Streamlit page, no network
pull, and nothing that feeds back into the Opportunity Packet. EDGE logs the
*human's* decision AFTER the packet and stays external to it (ADR-027
decision 2).

---

## 1. Design shape -- an append-only two-record-type event log

The corpus is a single **append-only JSONL** file: one JSON object per line.
There are **two record types**, distinguished by `record_type`:

- a **`decision`** record -- written once, at decision time, and **never
  edited**; and
- an **`outcome`** record -- appended later, referencing the decision by
  `decision_id`.

**Why append-only two-record, not one editable row:** for calibration to be
honest the analyst's confidence must be captured *before* the outcome and
stay unedited -- no hindsight revision. You never rewrite a decision line;
the outcome is a *new* line, so there is no *legitimate* edit path at all --
outcomes never touch decision lines. (Be precise about the guarantee: at
pilot scale, on a hand-appended, gitignored file with no writer and no
history, immutability is a **discipline** -- append-only by convention --
not a technical lock; a future append/validate helper is where it becomes
enforced. The design's real contribution is removing any *reason* to edit.)
This matches the house's standing discipline ("Preserve append-only decision
history; supersede ADRs instead of deleting them" -- `CLAUDE.md` line 62;
the SQLite ledger migration is additive with no DROP/DELETE -- `001_cases.sql`).

**Why JSONL, not CSV or SQLite:** JSONL holds the nested `factors[]` array
cleanly (CSV cannot), is append-only by nature, has no formula-injection
surface that a CSV/Excel export would (a leading `=`/`+`/`-`/`@` in a JSON
string value is inert -- it is not a spreadsheet formula), and is trivially
parseable by the future read line-by-line. (The packet export guards a
*different* risk -- Markdown **structural** injection -- via `_md`/`_cell`
in `packet_export.py` (~lines 589/606: backslash-escape Markdown
metacharacters, flatten line breaks, and swap `|`->`/` in table cells). It
emits no CSV and has **no** formula guard, because it exposes no CSV
surface to protect; EDGE's JSONL exposes none either.) A SQLite table would
re-introduce the "build an app to write it" problem this slice defers --
the pilot analyst appends a line by hand (5-10 decisions), corpus before
app.

**Storage location:** the live corpus is written to
`data/runtime/edge/gate_decisions.jsonl` -- alongside the SQLite case
ledger under `data/runtime/` (the same directory the ledger uses,
overridable by convention). It is **gitignored**: it is an internal,
non-public store, exactly like the SQLite ledger ("It is ignored by Git...
not suitable for CUI/FCI" -- `PRIVACY_AND_GOVERNANCE.md`). The committed
`*.example.jsonl` is a labeled worked example only.

---

## 2. `decision` record -- fields

| Field | Type | Req? | Enum / format | Why it exists (ties to the future read) |
|---|---|---|---|---|
| `record_type` | string const | **req** | `"decision"` | Discriminates the two record types on one stream. |
| `schema_version` | string const | **req** | `"edge/v1"` | Lets the future read handle format evolution without guessing; every record is self-describing. |
| `decision_id` | string | **req** | `EDGE-{YYYYMMDD}-{piid-sanitized}-{NN}` | Primary key; the `outcome` record joins on it; corpus dedupe. PIID sanitized with the SAME allowlist the packet filename uses (`[A-Za-z0-9._-]`, `packet_export._sanitize_piid_for_filename`) so IDs are filesystem/URL-safe and consistent with the filed export. |
| `logged_at` | string | **req** | ISO-8601 datetime **with timezone offset** | The **decision-time** stamp -- recorded when the call is made, before any outcome. Calibration honesty depends on this preceding the outcome; also enables decision->outcome lead-time analysis. |
| `piid` | string | **req** | raw PIID as pasted | Joins the decision to its evidence (the packet), to USAspending facts, and lets the read segment by agency/NAICS/set-aside carried in the packet. |
| `packet_export_filename` | string | **req** | `opportunity-packet-{piid}-{YYYYMMDD}.md` | **The evidence link.** The decision must point at the cited packet it was made from -- this is the honesty spine: the call is logged AFTER, and EXTERNAL to, the packet. If no export was filed, record the literal `"none-filed"` and say so in `rationale` (an honest absence, never a fabricated filename). |
| `case_id` | string \| null | opt | SQLite `cases.case_id` or `null` | Links to the durable case tracker (ADR-007) when a case is open; `null` when the analyst worked packet-only. |
| `supersedes_decision_id` | string \| null | opt | a prior `decision_id`, or `null` (default) | Makes a supersede **explicit** rather than inferred from a shared PIID. Set it only when this decision *replaces* an earlier call on the same opportunity (a revised confidence, a reversed pursue); leave `null` for a fresh decision -- **including a new recompete cycle logged under the same predecessor PIID**, which is its own forecast, not a supersede. The read (§8.1) treats a decision as superseded **only** when a later decision names it here -- so a genuinely resolved forecast is never silently dropped, and a resolved decision is never superseded. |
| `call` | string | **req** | `"pursue"` \| `"pass"` \| `"watch"` | The gate decision. See §4 for the enum justification (why a three-state, and why the sub-lane is a separate field). |
| `pursuit_lane` | string \| null | opt | `"prime"` \| `"sub"` \| `"jv"` \| `"undecided"` \| `null` | Captures "no-bid as prime, pursue as sub" without inflating the `call` enum. `null` when not applicable (e.g. a `pass`). |
| `confidence` | object | **req** | see §3 | **The calibration key.** The analyst's decision-time subjective PWin + how grounded it is. |
| `factors` | array<object> | **req** (>=1) | each `{section, stance, weight?}`; see §5 | Structured, controlled-vocabulary factors grounded in the packet's REAL sections plus the honestly-external capture factors. Feeds the "which factors carry" analysis. |
| `rationale` | string | **req** | free text | The named-drivers sentence ("pass as prime: barred 8(a) set-aside; pursue teaming with X"). Human-auditable context; the future read **never parses it for a computed field** (truth-discipline: no fabricated computable field). |
| `decider` | object \| null | opt (**opt-in**) | `{alias, consent:true}` or `null`; see §6 | Calibration-not-attribution. `alias` is a **controlled TEAM alias only** (never a role alias -- 1:1 with a person at pilot scale -- never a person id); recorded only by that decider for their own call; `null` = anonymous (the default). Never segmented, never ranked. |
| `notes` | string \| null | opt | free text \| `null` | Anything else (e.g. a shaping note, a trigger date to re-evaluate a `watch`). |

---

## 3. `confidence` object -- the calibration key (defined precisely)

```json
"confidence": { "p_win": 0.3, "basis": "some_evidence" }
```

- **`p_win`** -- number in **[0.0, 1.0]**, **required**. The analyst's
  decision-time subjective probability that, **if pursued**, this
  opportunity would be **won**. It is defined "if pursued" for *every*
  call, so a `pass` still carries a meaningful number ("I pass because I
  judge PWin ~ 0.10"). This is the single value the reliability curve and
  Brier score are computed against (§8). **Record it as a decile** (0.1,
  0.2, ... 0.9; 0.05/0.95 allowed at the extremes) -- the read bins anyway,
  and false precision (0.63) is discouraged (govcon honesty rule: bands not
  points).
- **`basis`** -- enum, **required**: `"gut"` | `"some_evidence"` |
  `"strong_evidence"`. How grounded the number is. Lets the read segment
  calibration by evidence depth (are our *gut* calls worse-calibrated than
  our *evidenced* ones?) without discarding any decision.

**Immutability rule:** once written, `confidence` is never edited. A
revised view is a *new* `decision` record (a superseding call), not an edit
-- the same "supersede, don't delete" discipline ADRs use.

---

## 4. `call` enum -- justified against real capture practice

- **`pursue`** -- commit bid-and-proposal (B&P) resources; the opportunity
  is in the active pursuit pipeline.
- **`pass`** -- decline this opportunity (as prime; a teaming lane may
  still be noted via `pursuit_lane` = `sub`/`jv` + `rationale`). B&P is
  finite; a small NPA can write few serious bids -- a `pass` is a real,
  logged decision, not the absence of one.
- **`watch`** -- neither commit nor drop: keep in the pipeline and
  re-evaluate at a trigger (solicitation drop, option-year decision,
  shaping window opening). Justified by the capture lifecycle (identify ->
  qualify -> **shape** -> propose): the decisive work happens before an RFP
  exists, so "not yet, monitor" is a first-class call, not a non-answer.
  The `notes`/`rationale` should carry the re-evaluate trigger.

**Why not fold "pursue as sub" into the enum:** it would double the enum
and muddy the calibration axis (which is confidence-vs-outcome on the
pursue/pass decision). Prime-vs-sub is a *lane*, captured in the optional
`pursuit_lane` field, so the call stays clean and the sub lane is not lost.

---

## 5. `factors[]` -- grounded in the packet's ACTUAL sections

Each factor object: `{ "section": <enum>, "stance": <enum>, "weight":
<enum, optional> }`.

**`section` controlled vocabulary.** The first ten map **exactly** to the
Opportunity Packet's real eleven sections (verified against
`packet_export.derive_section_ledger` and the `opportunity_packet.py`
docstring -- the packet has eleven *ledger* rows because Contract Facts
splits into live + analyst-entered; EDGE collapses those two into one
`contract_facts` factor). The last four are **honestly external** capture
factors the packet cannot see -- real bid/no-bid drivers (relationships,
past-performance fit, B&P capacity, the competitive field) that are
**never in public data** (govcon skill: CPARS, shaping, pricing are
non-public). Marking them separately lets the future read distinguish
"factors the packet evidenced" from "factors the analyst brought."

Packet-grounded sections:
`origin_radar_handoff`, `eligibility_gate`, `contract_facts`,
`capture_window`, `incumbent_teaming_leads`, `staffing_whatif`,
`geography_acs`, `pl_crossref_r2b`, `pl_activity_fedreg`, `r2a_map`.

Non-packet (analyst-brought) factors:
`customer_relationship`, `past_performance_fit`, `bnp_capacity`,
`competitive_landscape`.

**`stance` enum:** `"favorable"` | `"unfavorable"` | `"blocking"` |
`"informational"`. `blocking` encodes the domain reality that eligibility
is a **binary gate, not a score** (govcon skill): a barred set-aside is
`{section:"eligibility_gate", stance:"blocking"}`, which the read treats
categorically, never as a weighted point.

**`weight` enum (optional):** `"minor"` | `"major"` | `"decisive"`.
Optional so the analyst isn't forced to invent precision; when present it
lets the factor-signal read weight factor influence.

---

## 6. `decider` object -- opt-in, self-recorded, aggregate-only, never segmented

```json
"decider": { "alias": "bd", "consent": true }   // or  null
```

- **`alias`** -- a **controlled TEAM alias only**, drawn from `cases.py`'s
  `TEAM_ALIASES` (bd/business_development/capture/compliance/operations/
  research/admin). **Never a person id, name, or username** --
  reusing the case tracker's controlled-alias rule keeps the log from
  becoming an employee directory (`cases.py`: "a stable alias set is
  preferable to person IDs"). **Role aliases are deliberately excluded
  here.** At pilot size a `cases.py` role alias (`capture_manager`,
  `compliance_reviewer`, ...) maps 1:1 to a single person, so a
  role-alias cut would be a per-person score -- exactly what is banned.
  Only the coarser team aliases are admissible, and even those are never
  segmented on (last bullet).
- **`consent`** -- must be literally `true` when `decider` is present;
  `decider` is `null` (anonymous) by default. Recording a decider is
  **opt-in**.
- **Self-attribution only.** A `decider` field may be recorded **only by
  that decider, about their own call** -- you never log a `decider` about
  someone else's decision. Consent is first-person and cannot be given on
  another's behalf.
- **Aggregate-only, never segmented -- no leaderboard, structurally.** The
  future read (§8) pools ALL decisions together; `decider` is
  **consent/provenance metadata, not an analysis dimension.** The read
  **never** groups, filters, ranks, or renders any per-decider or
  per-alias surface, and a single-alias cut never renders -- so there is
  nothing to compare. This is enforced by keeping `decider.alias` **out of
  §8.3's segmentation set**, not by policy alone. (Should a decider cut
  ever be added in a future version, §8.2 pins the guardrails it must
  first clear: team aliases only, and a floor of >=K *distinct consenting
  deciders* per cell -- never a decision count, never a single alias.)

---

## 7. `outcome` record -- fields (appended later)

| Field | Type | Req? | Enum / format | Why |
|---|---|---|---|---|
| `record_type` | string const | **req** | `"outcome"` | Discriminator. |
| `schema_version` | string const | **req** | `"edge/v1"` | Self-describing. |
| `outcome_id` | string | **req** | `EDGE-OUT-{YYYYMMDD}-{NN}` | Unique id for the outcome event. |
| `decision_id` | string | **req** | FK -> a `decision` record | Joins the outcome back to its decision-time confidence. |
| `logged_at` | string | **req** | ISO-8601 datetime w/ tz | When the outcome was recorded (audit; distinct from `outcome_date`). |
| `outcome` | string | **req** | `"won"` \| `"lost"` \| `"cancelled_no_award"` \| `"no_bid_confirmed"` \| `"not_pursued"` \| `"still_open"` \| `"unknown"` | The realized result. Each value defined precisely below. |
| `outcome_date` | string \| null | opt | ISO-8601 date \| `null` | When the outcome became known/effective (e.g. successor award date). |
| `outcome_basis` | string | **req** | `"public_award_record"` \| `"analyst_knowledge"` \| `"agency_confirmation"` | Observed-vs-inferred marker (govcon skill). A public successor-award record is the gold standard for calibration; `analyst_knowledge` is lower trust and the read can segment/weight it. |
| `note` | string \| null | opt | free text \| `null` | Successor PIID, protest, cancellation, etc. |

**`outcome` enum, each value defined precisely:**

*Terminal, feeds calibration (a `pursue` forecast that resolved to a
win/loss):*
- **`won`** -- we pursued, a proposal was submitted, and we won. **Public
  award data supplies the label after the fact** (the successor award
  tells you who won; govcon backtest rule).
- **`lost`** -- we pursued, a proposal was submitted, and a competitor won
  the award.

*Terminal, EXCLUDED from calibration (the "if pursued, would win" forecast
was never testable -- there was no award to win, or no pursuit):*
- **`cancelled_no_award`** -- a *pursued* opportunity that produced **no
  award to anyone**: the solicitation was cancelled, the requirement was
  bridged/insourced, or it was folded into another vehicle. The forecast is
  unfalsifiable (nobody won), so it is excluded from the reliability curve
  exactly as `still_open` is -- but it is a real, common terminal end state
  that `won`/`lost`/`still_open`/`unknown` would each misrepresent.
- **`no_bid_confirmed`** -- the decision was a **`pass`** and the decline
  **stood**: we confirmed no proposal was submitted (e.g. a barred
  set-aside held, or a conscious decline that was not reversed). An
  *active* non-pursuit.
- **`not_pursued`** -- the decision was a **`watch`** that **lapsed**: the
  re-evaluate trigger never fired (or the window closed) and we never
  moved to pursue. A *passive* non-pursuit, distinct from an active
  `pass`. (The `pass`->`no_bid_confirmed` vs `watch`->`not_pursued` split
  is what keeps these from being synonyms.)

*Non-terminal, EXCLUDED from calibration:*
- **`still_open`** -- **known** to be unresolved: the procurement is
  genuinely in progress and a result is expected later. Record an
  `outcome` line again when it resolves.
- **`unknown`** -- **cannot determine / lost track**: we tried to resolve
  it and cannot -- no observable public award record and no analyst
  knowledge. (Contrast `still_open`, where the lack of a result is
  expected, not a gap in our tracking.)

**Reversed `pursue` (pursued at the gate, then no-bid *before* a proposal
is submitted).** A `pursue` has no valid terminal outcome unless a proposal
was actually submitted (`won`/`lost`), so a call reversed before submission
is **not** stamped `lost` -- that would fabricate a loss that never
happened -- and it fits no other value either (`no_bid_confirmed` is
`pass`-only, `not_pursued` is `watch`-only, `cancelled_no_award` requires
no award to *anyone*). Route it by **supersede-then-resolve**: append a new
superseding `decision` line for the same `piid` with `call:"pass"`, and
resolve **that** pass with `no_bid_confirmed`. The superseded `pursue`
record keeps no outcome and is honestly excluded from calibration (its "if
pursued, would win" forecast was never tested -- no proposal went out).
This is the same supersede-not-edit discipline as §1/§3, and the read
scores only the operative (latest) decision of the chain (§8.1).

The calibration read (§8) feeds **only** resolved `won`/`lost` on `pursue`
decisions into the reliability curve; every other value is dropped from
both numerator and denominator (truth-discipline: never impute a missing
outcome).

---

## 8. The future-calibration-app spec (specified, not built)

**8.1 What the read computes (all aggregate, opt-in, no leaderboard):**
- **Aggregate calibration.** Over resolved `pursue` decisions (outcome in
  {won, lost}), bin by `confidence.p_win` decile and plot observed win-rate
  per bin -- a **reliability curve** -- and report an overall **Brier
  score** = mean((p_win - won?)^2). Show each bin's **n** and a **Wilson
  interval**; render nothing where n is below the small-cell floor. This
  answers "are our stated confidences honest?" -- not who is best.
  - **The unit of a forecast is a resolved pursue `decision` that no later
    decision supersedes.** A revised call is a *new* `decision` line that
    names the one it replaces via `supersedes_decision_id` (supersede, not
    edit -- §1/§3/§7); a decision is treated as superseded **only** when a
    later decision explicitly names it there, never merely because another
    decision shares its PIID. The read **drops any superseded decision**
    and scores only the surviving (unsuperseded) resolved pursue
    decisions, so a supersede chain contributes **at most one** forecast
    and one award event never enters the Brier mean **twice** with
    correlated outcomes. Two rules pinned now: **(a) a resolved decision
    is never superseded** -- once a decision carries a `won`/`lost`
    outcome, a later call on the same opportunity (e.g. the next recompete
    cycle) is a *new* forecast with `supersedes_decision_id:null`, not a
    supersede, so genuinely resolved forecasts are never silently
    discarded; **(b) the operative outcome of a decision is its latest
    `outcome` line** -- if an outcome is later revised (a `still_open`
    that resolves, or a `won` overturned on protest to `lost`), append a
    new `outcome` line and the read takes the most recent by `logged_at`.
    (Consistent with the reversed-`pursue` route in §7, where the
    superseding `pass` is operative and the superseded `pursue` is
    excluded.)
- **Factor-signal analysis.** For each `factors[].section` x `stance`,
  compare its presence in won vs lost pursued decisions (and its `weight`
  distribution) -- which factors correlate with good calls. Report as
  directional associations with n, never as fitted weights. Keep
  packet-grounded factors and analyst-brought factors in separate views
  (the packet cannot see the latter).
- **Base rates & drift.** Pursue/pass/watch mix over time; `basis`-
  segmented calibration (gut vs evidenced).

**8.2 Honesty rules the read must obey (pinned now so the schema supports them):**
- **Exclude, never impute.** Everything except resolved `won`/`lost` on a
  `pursue` decision -- `cancelled_no_award`, `no_bid_confirmed`,
  `not_pursued`, `still_open`, `unknown`, and any not-yet-resolved decision
  -- is dropped from BOTH numerator and denominator, never filled with a
  neutral 0.5 (govcon rule #2). `cancelled_no_award` in particular is a
  *terminal* end state that is still excluded: with no award to anyone,
  the "would win if pursued" forecast is unfalsifiable.
- **Calibration is conditional on pursuit.** p_win is scored against
  outcomes only on the PURSUED subset, so the read measures
  pursue-forecast honesty, not pass-quality. A systematically
  over-confident-on-passes analyst is **never falsified here** -- the
  counterfactual of a declined bid is unobservable (we never learn what a
  `pass` would have done). Every calibration figure is therefore reported
  as **conditional-on-pursuit**, with that selection caveat attached.
- **Self-suppress under thin data.** Below a pinned n (e.g. an overall
  floor of ~20 resolved decisions, and a per-bin floor), publish **no
  number** -- render the literal "directional only -- load more decisions."
  A pilot's 5-10 decisions is below the floor by design; the honest output
  is the note, not a curve.
- **Small-cell suppression on factor cuts** (e.g. suppress any cell with n
  < 5 *decisions*) -- the read is aggregate; it must be structurally unable
  to expose an individual.
- **No decider segmentation -- no leaderboard, structurally.**
  `decider.alias` is **not** a segmentation dimension (it is absent from
  §8.3's list on purpose): the read pools all decisions and renders no
  per-decider or per-alias surface, so a single-alias cut cannot exist and
  there is nothing to rank. **Should** a future version ever add a decider
  cut, it must clear ALL of: (a) **team aliases only** -- never role
  aliases, which are 1:1 with a person at pilot scale; (b) a floor of
  **>=K distinct consenting deciders** per cell (K>=3), counted as
  *distinct deciders*, never as a decision count; (c) it never renders a
  single-alias / single-decider cell. None of this is in the specified
  read -- the surface simply does not exist.
- **Disclose known bias.** Beyond the pursuit-conditioning above, public
  outcome labels detect some results more readily than others (e.g. a
  retained incumbent's successor award is easier to observe than a quiet
  no-award); the measured calibration carries that caveat with its
  direction.

**8.3 Exactly which fields make each computation possible (captured NOW):**
- Reliability curve / Brier <= `confidence.p_win` (decision-time,
  immutable) + `outcome` (resolved won/lost) + `decision_id` join +
  `logged_at` (proves confidence preceded outcome).
- Factor-signal <= `factors[]` (controlled `section`/`stance`/`weight`) +
  `outcome`.
- Segmentation <= `confidence.basis`, `call`, `pursuit_lane` -- all
  captured fields. `decider.alias` is **deliberately not a segmentation
  field** (§6, §8.2): it is consent/provenance metadata the read never
  cuts on.
- **Agency / NAICS / set-aside segmentation is an *external join*, not a
  captured field.** These are not stored in `edge/v1`; the read would
  recover them by joining `piid` back to the packet / USAspending at read
  time. That join is explicit and cited -- never fabricated -- but it is a
  join, so this cut degrades gracefully to "unavailable" when the source
  can't be re-reached. (If self-contained agency/NAICS/set-aside cuts are
  wanted later, the clean fix is to add optional `agency`/`naics`/
  `set_aside` fields snapshotted at decision time -- noted as a future
  `edge/v*` addition, not built now.)
- For every computation that uses only captured fields (calibration,
  factor-signal, the basis/call/lane cuts), the read invents nothing; the
  only externally-joined cut is the agency/NAICS/set-aside one just noted,
  and it is labeled as such.

**8.4 Non-goals (explicit):** no per-person scoring, no packet feedback, no
automated outcome scraping in this spec (outcomes are analyst-entered with
an `outcome_basis`), no publication of any number before its pinned n-gate
passes.
