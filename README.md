# ReconRadar

**A cited, score-free Opportunity Packet for AbilityOne NPA business development.**
Part of the TENS HQ product family, downstream of
[GovCon Recompete Radar](https://github.com/CJud25/GovConRadar): the Radar finds an
expiring federal contract; ReconRadar assembles the evidence a human needs to decide
whether to pursue it.

One expiring contract goes in. A provenance-tracked evidence sheet comes out — routed
onto the four suitability criteria of 41 CFR 51-2.4(a) for a **human** decision.
Nothing in this app renders a score, ranking, PWin, or bid/no-bid recommendation,
and nothing here is a suitability determination — the Commission determines
suitability.

## What you get

One expiring contract in; this document out. Below is a byte-verbatim excerpt of
[`docs/examples/example-packet.md`](docs/examples/example-packet.md) — the real, unedited
output of the export path, generated offline from the repo's bundled SYNTHETIC samples by
`py scripts/generate_example_packet.py`. Nothing in it was typed by hand.

**Section ledger** — every section, included or honestly absent, with the reason:

| Section | Included | Basis |
|---|---|---|
| Origin \(Radar handoff\) | Yes | A Radar handoff snapshot is attached and its PIID matches this packet's current PIID. |
| Eligibility gate | Yes | Gate fed by the LIVE retrieved set-aside value \(USAspending FPDS type_set_aside\), which supersedes any analyst-typed value once live Contract Facts are attached. |
| Contract Facts \(SYNTHETIC example\) | Yes | Bundled SYNTHETIC example facts attached — offline, not a real USAspending API retrieval. |
| Contract Facts \(analyst-entered\) | Yes | Always rendered from the analyst-pasted PIID and place of performance, independent of any other evidence attached. |
| Capture window | Yes | Computed from the attached live Contract Facts pull's potential period end date. |
| Incumbent & teaming leads / PL-impact | Yes | Evidence attached: facts + directory. |
| Staffing what-if | Yes | An analyst-entered staffing baseline was attached to this render. |
| Geography \(ACS\) | Yes | Section rendered as a placeholder -- no ACS context retrieved \(not yet pulled\). |
| PL cross-reference \(R2b\) | Yes | A PL workbook was cross-referenced against this render's worksite. |
| Procurement List activity \(Federal Register\) | Not included | No Federal Register pull attached. |
| R2a determination-support map | Yes | Always rendered -- routes whatever evidence is currently attached above onto the four suitability criteria of 41 CFR 51-2.4\(a\). |

**Source manifest** — every attached source, its reference, retrieval time, and assurance:

| Source | Reference | Retrieved at | Assurance | Notes |
|---|---|---|---|---|
| Radar handoff \(analyst upload\) | sample_radar_handoff.json \(SYNTHETIC example\) | 2026-07-15 | USER_ATTESTED | The handoff's claimed snapshot retrieval time; not independently verified. Live Contract Facts, where attached, supersede this claim. SYNTHETIC example handoff — not real Radar output. |
| Contract Facts \(SYNTHETIC example, offline\) | bundled SYNTHETIC example \(offline\) -- not a live USAspending retrieval | 2026-07-22T12:00:00+00:00 | SYNTHETIC_EXAMPLE | SYNTHETIC example — not real USAspending data. |
| AbilityOne NPA directory \(analyst upload\) | sample_nib_npa.xlsx \(SYNTHETIC example\) | Not supplied \(analyst attestation absent\) | USER_ATTESTED |  |
| Staffing what-if inputs \(analyst-entered\) | HOURS mode entry | Not supplied \(analyst attestation absent\) | USER_ATTESTED |  |
| Procurement List cross-reference workbook \(R2b\) | sample_pl_services.xlsx \(SYNTHETIC example\) | 2026-07-24 | USER_ATTESTED | SYNTHETIC example workbook — not real Procurement List data |

The full file adds the stamped header, the attestation disclaimers, and the packet body
those two tables describe.

## The Opportunity Packet

Work one page, top to bottom; the packet re-renders as evidence attaches:

1. **Origin** — optional `radar-handoff/v1` JSON from GovConRadar's Contract Detail
   page. Prefills retrieval inputs only; nothing from it is treated as verified.
2. **Contract facts (live)** — one analyst-initiated USAspending pull: obligated
   vs. ceiling kept distinct, award description, place of performance (a county is
   not a city), set-aside, offers — every fact cited with source URL and retrieval
   time. A PIID shared by several awards is disambiguated by the analyst, never
   auto-picked.
3. **Eligibility gate** — reads the live set-aside code. Blank means Unknown,
   never "unrestricted." A gate, not a score.
4. **Capture window** — an honest band for the likely follow-on solicitation and
   the R2a start-by date. Negative runway is reported, not hidden.
5. **Incumbent & teaming leads** — subaward records and NPA-directory
   cross-reference. Leads, never verdicts.
6. **Staffing what-if** — a labeled planning indicator, never an ODLH
   determination.
7. **Geography context** — one cited Census ACS county figure.
8. **Procurement List cross-reference** — exact match against an
   analyst-attested PL Services workbook. A no-match is evidence absence.
9. **PL activity** — the Commission's Federal Register notice stream, cited,
   never interpreted.
10. **R2a determination-support map** — routes the evidence above onto
    41 CFR 51-2.4(a), stating plainly what is absent.
11. **Export** — a Markdown deliverable: verbatim body + Section ledger (honest
    absences included) + Source manifest.

Every live pull **fails loud**. Editing an input detaches any stale result built
on it. A missing value reads "Not reported" — never $0.00.

## Quickstart

```powershell
.\run_demo.ps1          # provisions a venv and launches the app
```

A default Windows 11 execution policy blocks that script (`.ps1 files are
disabled on this system`). Either run it as:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_demo.ps1
```

or install manually — this also works on any OS: `pip install -r requirements.txt`
then `streamlit run app.py` (Python 3.11+). The packet works fully offline on the
bundled SYNTHETIC examples; the four live pulls (USAspending ×2, Census ACS,
Federal Register) need internet, and the ACS pull needs a free Census API key in
`TENS_HQ_CENSUS_API_KEY` (the key rides only the wire request — cited URLs stay
keyless by construction).

**Hosting note.** The case ledger (`data/runtime/tens_hq.sqlite3`) is local,
single-user, and unauthenticated — it is not an identity, access-control, or
multi-tenant boundary. A shared hosted URL running this app would commingle every
visitor's cases and let one visitor read or mutate another's. Run the full app
locally (or per pilot analyst), or host only the packet-only surface, until
per-identity isolation and auth land (see `docs/ARCHITECTURE.md` §"Trust and
storage boundaries").

- `docs/DEMO_SCRIPT.md` — a guided walkthrough (the in-app "▶ Guided demo"
  follows it).
- `docs/PILOT_RUNBOOK.md` — how to run a governed discovery pilot.
- `docs/decisions/` — the ADR lineage behind every honesty rule.

## Data and governance

Public organizational/contract-directory data and analyst-uploaded official
exports only — no person-level data. The bundled demo data is synthetic and
validated on every test run. Counsel-gated regulatory claims are excluded from
every rendered surface, test-enforced.

The suite is 585 tests as of this commit (`py -m pytest`), including dedicated
guards for markdown-injection, counsel-gated vocabulary, and the no-score rule.
CI runs that suite plus `ruff check .` and `py scripts/validate_demo_data.py` on
Python 3.11 and 3.12, on every push and pull request.

## How this was built

Chris Judkins specified this system, decomposed it into gated slices, and
verified each one; AI agents wrote most of the line-level code. The commit
history shows it — most commits here carry a `Co-Authored-By: Claude` trailer.

The loop was the same every slice: nothing merged until the repo's own gate was
green (`py -m pytest` and `ruff check .`, both run in CI on every push and pull
request), and each slice went through an independent adversarial review before
merge. ADR-015, ADR-017 and ADR-018 record what those reviews changed.

One catch the model missed. In the incumbent-leads slice, the generated design
treated "sole-source award" and "one or zero offers received" as two signals
corroborating each other. They are not independent: on a sole-source award the
government solicits one vendor by definition, so the offers count is *entailed*
by the designation and adds no evidence. The `Lead-corroborated` band was
reserved instead; that pair now renders `Lead-single`, with the offers count
named as consistent with — not corroborating — the designation (ADR-017,
Decision 4; `src/tens_hq/incumbent_leads.py`).

The judgment calls — what to refuse to compute, what to delete, which label was
wrong — are the part worth evaluating.

## License

MIT — see [LICENSE](LICENSE).
