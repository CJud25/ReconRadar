# ADR-020: Owner-attested domain constants (2026-07-21) replace the codebase's provisional guesses

## Status

Accepted for the A6 (Staffing what-if) and R2a (Determination-support map) slices

## Date

2026-07-21

## Context

Several packet surfaces have been carrying PROVISIONAL, codebase-supplied
placeholder figures explicitly flagged as an owner `[VERIFY]` since they were
first written (ADR-015's capture-window lead times chief among them). This
slice is the first time the owner -- the pilot AbilityOne NPA's compliance
coordinator -- sat down and attested real domain constants in
writing. This ADR is the single place those constants are recorded, so every
module that consumes one (`capture_window.py` today; `staffing_whatif.py` and
`r2a_map.py` in this same slice pair) cites back to one attestation record
instead of re-describing it.

Two items the owner was asked about are **not theirs to attest** -- they are legal
questions for counsel, not compliance-coordinator domain knowledge -- and
stay `[VERIFY]`:

- **C3** -- small-business goal credit for a prime that subcontracts to an
  AbilityOne NPA. (Citation corrected 2026-07-21: the operative statute is
  10 U.S.C. 3903, formerly 2410d, implemented by DFARS 219.703; this ADR
  originally cited '10 U.S.C. 4874', which is a foreign-government-control
  prohibition -- a citation error, found while preparing the counsel review
  packet. The claim itself remains counsel-gated regardless of citation.)
- **C4** -- conditionality of the AbilityOne Limitation-on-Subcontracting
  (LoS) exemption/treatment (13 CFR 125.6).

Neither this ADR nor any module built against it may hardened either claim:
no rendered copy anywhere in the codebase may state a C3 or C4 position as
fact. This ADR records that boundary explicitly so a future slice cannot
accidentally "fill in" a counsel-gated item by treating everything else in
this document as attested license to guess the rest.

## Decision

Record the attested constants verbatim, faithfully, with no embellishment or
extension beyond what the owner actually said on 2026-07-21.

**Attestation provenance:** the pilot AbilityOne NPA's compliance coordinator.
Collected 2026-07-21. Grade: owner-attested domain knowledge from a
compliance practitioner working these ratios and this Commission process day
to day -- not a legal opinion, not a specific CNA's or program's own
negotiated figure for a particular contract (each module built on this ADR
keeps its own caveat saying so), and explicitly NOT the two counsel-gated
items above.

### The two ratios

- **ODLH** -- "Agency/Overall Disabled direct Labor" ratio: disabled direct
  labor hours divided by total direct labor hours (disabled + non-disabled),
  computed agency-wide, per fiscal year. Statutory floor: 75%.
- **PLDLH**, a.k.a. **EDLH** ("Estimated Direct Hours") -- a per-PL-project
  (or product-family) ratio the Commission may approve BELOW 75%, permissible
  only while the agency maintains the 75% ODLH ratio overall.

### Supervisory and indirect hours

Excluded entirely from the ODLH computation -- neither the numerator nor the
denominator.

### Tracking granularity vs. compliance granularity

Agencies track ratios per project/site operationally, but compliance itself
is agency-wide, per fiscal year.

### Available aggregate source data

The owner reported that an analyst can see per-site and company-wide direct-labor-ratio (DLR) and FTE
counts broken out by employee code: `01` non-disabled, `02` disabled, `07`
pending disability documentation.

### What-if entry modes

The owner chose to support BOTH:

1. FTE counts by code `01`/`02`/`07` -- labeled an FTE-based
   **approximation** of the hours-based ratio (a headcount cannot separate a
   person's supervisory/indirect hours from their direct-labor hours, so it
   cannot perform the supervisory/indirect exclusion above).
2. Direct labor hours -- exact.

### Ramp

Site-dependent: an incumbent-workforce transition ramps differently than greenfield
hiring. No single ramp curve is attested or assumed -- render an
end-state delta only, never a ramp curve.

### CNA

SourceAmerica -- nameable in copy.

### Lead times

- **PL-addition lead: 9-12 months** (a band; supersedes ADR-015's original
  provisional single-point 6-month value, effective 2026-07-21 -- see
  ADR-015's dated Update).
- **Procurement lead: 6-12 months** -- confirmed (unchanged from ADR-015's
  original methodology band).

### R2a origination and allocation

- R2a origination can come from **either direction**: agency BD or the CNA.
- Allocation of a Procurement List addition, once made, is
  **CNA-discretionary**. Copy may now say so plainly -- this is not a
  prediction of a specific outcome, it is a statement of who holds the
  discretion.

### (a)(4) impact thresholds

**Unknown to the owner.** No computed share, no named threshold -- side-by-
side facts only. Unchanged from A5/ADR-017.

### Four suitability criteria + FMP-separate framing

**Confirmed.** 41 CFR 51-2.4(a)'s four criteria:

- **(a)(1)** employment potential of persons who are blind or have other
  severe disabilities;
- **(a)(2)** the NPA's qualifications to satisfactorily perform the work (the
  75% ODLH capability question lives here);
- **(a)(3)** capability to meet quality standards and delivery schedules;
- **(a)(4)** impact on the current or most recently prior contractor for the
  requirement.

Fair market price (FMP) is a **separate** determination (41 U.S.C. 8503 / 41
CFR 51-2.7) -- not one of the four criteria and out of scope for this tool
(N2, unchanged).

### C2 -- DOD Mentor-Protege Program (NPA-protege)

Confirmed generally as a real program; whether the pilot NPA itself currently
participates is **unknown** to the owner.

### C3 / C4 -- counsel-gated

See "Context" above. `[VERIFY]`, not attested, must not be hardened anywhere.

### Capability list (owner-attested, for capability-context copy only)

Administrative; Contact center & IT; Contract management; Electronics
recycling; Food services; Fleet management; Healthcare & environmental;
Laundry; Mail management; Records & document management; Secure document
destruction; Retail services; Supply chain management & warehouse; Product
packing; Total facility management; plus cybersecurity, software testing,
information assurance, Section 508 assurance, data entry, document
management, transcription, digital imaging, GPC program support,
audit-readiness support, ready-to-close contract/grant file prep,
pre-/post-award administrative services, switchboard, order processing, help
desk.

Any PSC-to-capability mapping is DERIVED work and must be labeled as such if
ever built; this ADR and the slices built against it do NOT build one -- the
list above renders as attested text only, never a scored or matched
capability determination.

### Readiness context gates

Location (proximity to existing operations) and contract size (within agency
capacity) add as analyst-judged context -- not scored, not thresholded.

### Freshness budgets

Unchanged: 180/90/30.

### Other context

The pilot NPA believed itself prime on some contracts (context, not attested as a
verified fact of record). NPAs participate in FMP negotiation generally
(context only; FMP itself stays out of this tool per N2).

## Consequences

- `capture_window.py`'s `CaptureWindowPolicy` default changes from a
  provisional single-point `pl_addition_lead_months=6` to an owner-attested
  `pl_addition_lead_min_months=9` / `pl_addition_lead_max_months=12` band,
  effective-dated 2026-07-21 -- see ADR-015's dated Update for the module-
  level detail and the R2a start-by band-widening arithmetic this implies.
- `staffing_whatif.py` (A6) cites the ratio definitions, the supervisory/
  indirect exclusion, the two entry modes, and the "never a ramp curve"
  constraint from this ADR.
- `r2a_map.py` (R2a) cites the four criteria, the FMP-separate framing, the
  CNA/allocation/origination facts, and the capability list from this ADR --
  and must keep C3/C4 out of every rendered row.
- Every module built against this ADR keeps its own "this is a generic
  methodology default / general attested fact, not a specific program's or
  CNA's own confirmed figure for a particular contract" caveat; owner
  attestation of a domain constant is not the same claim as a per-contract
  confirmation, and no module may conflate the two.
- A future slice that needs C3 or C4 must obtain a counsel opinion first;
  this ADR is not a substitute for one and creates no license to infer one.

## Alternatives considered

- **Fold these constants directly into each consuming module's own
  docstring, with no central ADR:** rejected; two modules (`capture_window.py`
  today, `staffing_whatif.py` and `r2a_map.py` in this slice) consume
  overlapping facts from the same attestation session, and a single dated
  record keeps them from drifting into slightly different retellings of the
  same conversation.
- **Attempt to infer or estimate C3/C4 from public guidance so the tool has
  "something" to show:** rejected; these are legal questions this codebase
  has no authority to answer, and a plausible-sounding inference would read
  as confirmed guidance to an analyst, which is exactly the harm the
  counsel-gate exists to prevent.
