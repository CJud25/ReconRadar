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

or manually: `pip install -r requirements.txt` then `streamlit run app.py`
(Python 3.11+). The packet works fully offline on the bundled SYNTHETIC examples;
the four live pulls (USAspending ×2, Census ACS, Federal Register) need internet,
and the ACS pull needs a free Census API key in `TENS_HQ_CENSUS_API_KEY` (the key
rides only the wire request — cited URLs stay keyless by construction).

- `docs/DEMO_SCRIPT.md` — a guided walkthrough (the in-app "▶ Guided demo"
  follows it).
- `docs/PILOT_RUNBOOK.md` — how to run a governed discovery pilot.
- `docs/decisions/` — the ADR lineage behind every honesty rule.

## Data and governance

Public organizational/contract-directory data and analyst-uploaded official
exports only — no person-level data. The bundled demo data is synthetic and
validated on every test run. Counsel-gated regulatory claims are excluded from
every rendered surface, test-enforced.

563 tests run in CI, including mutation-tested guards for markdown-injection,
counsel-gated vocabulary, and the no-score rule.

## License

MIT — see [LICENSE](LICENSE).
