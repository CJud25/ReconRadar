# Opportunity Packet — pilot runbook

How to run a governed discovery pilot: real expiring contracts in, cited
evidence packets out. The packet is the deliverable. Nothing in this build
renders a score, ranking, or bid/no-bid recommendation, and nothing here is
a suitability determination — the Commission determines suitability.

## Prerequisites

- **Environment**: Python 3.11+. `run_demo.ps1` provisions its own venv from
  `requirements-dev.txt` on first run; for a manual install,
  `pip install -r requirements.txt` (runtime deps only) is enough. The
  `Dockerfile` is the third option. Network access for the four live pulls.
- **Census API key** (required for the ACS geography pull): free signup at
  `api.census.gov/data/key_signup.html`, then set `TENS_HQ_CENSUS_API_KEY`.
  Without it the pull fails loud with instructions; the rest of the packet
  still works. The key rides only the wire request — cited source URLs stay
  keyless by construction.
- **Pilot mode**: set `TENS_HQ_PILOT_MODE=1`. The public app already contains
  only **BD Feasibility** and **Privacy & Governance**. Pilot mode keeps both
  pages available and narrows presentation by hiding the guided tour and
  planning controls; it is not an access-control boundary.
- **Case ledger location** (optional): `TENS_HQ_DB_PATH` overrides where the
  SQLite case/evidence ledger is written (default `data/runtime/`).
- **Case tracker, offline (optional, ADR-026)**: the **Cases** / **Scan &
  Evidence** tabs are the repeatable evidence workflow around the packet
  (`DEMO_SCRIPT.md` Act 4). With no network or real workbook on hand, tick
  "Use the bundled SYNTHETIC NIB/NPA example instead of an upload" on the
  Scan tab to run the NIB/NPA lane against the same bundled Denver/Aurora,
  CO rows the packet's PL cross-reference sample uses.
- **Inputs the analyst brings per opportunity**:
  - A `radar-handoff/v1` JSON from GovConRadar's Contract Detail page
    ("Download ReconRadar handoff") — or a pasted PIID with no handoff.
  - A current **AbilityOne PL Services workbook** (analyst-retrieved; the
    upload asks you to attest the retrieval date — attest honestly, it is
    printed in the export).
  - Optionally a current **NPA directory workbook** (.xlsx) for
    incumbent/teaming cross-reference.

## Launch

```powershell
$env:TENS_HQ_PILOT_MODE = "1"
$env:TENS_HQ_CENSUS_API_KEY = "<your key>"
.\run_demo.ps1
```

**Docker, with a persistent ledger.** `Dockerfile` declares
`/app/data/runtime` (where the case ledger lives) as a volume mount point, but
a container recreated with no volume attached loses the ledger silently. Mount
a named volume so a redeploy does not wipe cases:

```bash
docker build --tag reconradar:ci .
docker run -p 8501:8501 \
  -e TENS_HQ_PILOT_MODE=1 -e TENS_HQ_CENSUS_API_KEY=<your key> \
  -v reconradar_runtime:/app/data/runtime \
  reconradar:ci
```

## Per-opportunity workflow

Work the **Opportunity Packet** tab top to bottom; the packet re-renders as
evidence attaches. This is the operational version of `DEMO_SCRIPT.md` Act 2:

1. **Origin**: upload the Radar handoff (`Use handoff`). It prefills
   retrieval inputs only; nothing from it is treated as verified.
2. **Contract facts**: `Pull contract facts (live)`. If several awards share
   the PIID, pick the exact award — the app never auto-picks. Confirm the
   obligated/ceiling figures read sensibly; they are cited with URL and
   retrieval time.
3. **Eligibility gate**: reads the live set-aside. Blank = Unknown, never
   "unrestricted". A barred gate still leaves the teaming lane and the R2a
   mandatory-source lane (FAR 8.7 Procurement-List addition) — those
   assessments are yours, not the tool's.
4. **Capture window**: an estimate band from owner-attested lead times.
   Confirm real lead times with the CNA/program before scheduling work
   against it. A negative runway (window already elapsed) is a real and
   common finding on near-term expirations — report it, don't hide it.
5. **Leads**: `Pull subaward records (live)` once the award is resolved;
   upload the NPA directory if you have one. Leads are never verdicts.
6. **Staffing what-if**: real baseline hours only, direct-labor hours only.
   The output is a planning indicator, never an ODLH determination.
7. **Geography**: the live facts pull cites the award's place of performance
   and prefills EMPTY county/state inputs (and the R2b worksite city); the
   analyst confirms them. A county is not a city — a base-named worksite can
   sit in a county whose name never appears on the award. Then `Pull ACS
   geography context (live)` (needs the Census key).
8. **R2b cross-reference**: upload the PL Services workbook, attest its
   retrieval date, `Cross-reference the Procurement List`. A no-match is
   evidence absence, not "off the Procurement List".
9. **PL activity**: `Pull Procurement List activity (live)` — the
   Commission's notice stream, cited, never interpreted.
10. **Export**: `Export Opportunity Packet (Markdown)`. File the download
    with the case; it carries the Section ledger (honest absences included)
    and the Source manifest.
11. **Gate decision (EDGE)**: after you file the export, log your call. Append one
    `decision` line to `data/runtime/edge/gate_decisions.jsonl` using
    `docs/edge/gate-decision-log.template.md` — the call (`pursue`/`pass`/`watch`), your
    decision-time confidence (`p_win` as a decile, *if pursued*), the factors that drove
    it (tied to the packet's own sections), and a one-line rationale. Point the record at
    the export you just filed (`packet_export_filename`). The log is append-only: never
    edit a line; to revise, append a new one. Later, when you learn how the opportunity
    resolved, append an `outcome` line. This is the packet's downstream memory: the packet
    equips the call, EDGE records it so we can later check whether our confidence was
    honest — it never changes the packet and never scores a person.

### The decision log accrues into a corpus
Each opportunity adds one `decision` line (and later one `outcome` line) to the same
append-only file. Across the pilot's real opportunities the file becomes the EDGE
corpus. No calibration is computed yet — corpus before app. Once enough decisions
resolve, `docs/edge/GATE_DECISION_LOG.md` §6 specifies the aggregate, opt-in calibration
read (reliability curve, Brier score, factor-signal) that the corpus will support. At
pilot scale the honest output is "directional only — load more decisions," by design.

## Failure modes (all deliberate)

- Every live pull **fails loud** — a friendly-looking empty result is never
  substituted. Rate limiting says so; a missing Census key says so; an
  unrecognizable upstream response says so.
- Editing an input **detaches** any stale result built on it (PIID, award,
  place, workbook, search term). Re-pull rather than trusting a stale panel.
- One upload cannot satisfy two evidence gates; the scanner never infers
  capacity, candidate supply, a relationship, or an acquisition outcome.

## Governance boundaries

- Public organizational/contract-directory data only. No person-level data.
- Workbook bytes are not retained; the ledger stores derived evidence and
  provenance only.
- Counsel-gated C3/C4 content stays out of the packet, the export, and the
  operator script (test-enforced). Do not ad-lib it.
- The **EDGE gate-decision log** (`data/runtime/edge/gate_decisions.jsonl`) records the
  analyst's own pursue/pass/watch call *after* the packet — it is internal, gitignored,
  and non-public (same posture as the SQLite ledger). It never joins to a person, names a
  decider only by an opt-in team alias for the decider's own call, and never feeds anything
  back into the packet. See `docs/edge/GATE_DECISION_LOG.md` for the schema and governance.

## Success criteria — DRAFT, owner sign-off required

Proposed measures for the discovery phase; the owner edits/approves these before
the pilot starts. Targets are placeholders, not commitments:

1. **Throughput**: N real expiring contracts (suggest 5–10) carried from
   Radar handoff to filed export.
2. **Traceability**: in a line-by-line review of each export, every factual
   line traces to its cited source or is labeled Unknown/absent — zero
   unsourced claims.
3. **Honesty under absence**: at least one packet filed with a failed or
   absent section, shown honestly in the Section ledger (the 2026-07-22 dry
   run is the reference example).
4. **Analyst time**: time per packet recorded (suggest: target under 30
   minutes once familiar).
5. **Decision usefulness**: for each packet, the analyst records whether it changed or
   confirmed a next action **as an EDGE `decision` line** (pursue / pass / watch, with
   decision-time confidence and the factors behind it) — the packet's job is equipping
   that call, not making it.
6. **Zero overclaim incidents**: no packet line quoted onward as a claim the
   packet does not support (the export's own caveats travel with it).
7. **Decision-log completeness**: every filed packet has a matching EDGE `decision` line
   that references its export, with a decision-time `p_win` and at least one factor —
   the corpus seed for a future calibration read. (Calibration itself is not a pilot
   success criterion; the corpus is too small to read honestly yet.)

## Reference

- `DEMO_SCRIPT.md` — the demonstration walkthrough (synthetic-safe).
- Dry-run evidence (2026-07-22): a real expiring DoD delivery order was carried
  from handoff through live pulls to a cited export; the Census key requirement
  was discovered live and is now handled as above.
