# Opportunity Packet demo script

The demo is the packet. One expiring contract goes in; a cited, provenance-tracked,
score-free evidence sheet comes out, routed onto the four suitability criteria for a
human decision. The public app has exactly two pages: **BD Feasibility**, which holds
the packet and case tracker, and **Privacy & Governance**, which closes the walkthrough.

Timing: about 12 minutes for Acts 1–3; Acts 4–5 add about 5 more. The packet works
fully offline with the bundled SYNTHETIC examples; the live pulls need internet.

> The sidebar's "▶ Guided demo" walks this script's spine — six packet beats,
> then the governance close — and can pace the walkthrough. The BD page now
> lands on the **Opportunity Packet** tab, so the packet beats need no manual
> tab click; the tour still switches pages for the governance close.

## Act 1 — Setup (1 minute)

1. Start the app (`.\run_demo.ps1`) and open **BD Feasibility** in the sidebar.
2. Point at the sidebar banner — *PUBLIC EVIDENCE PILOT — ORGANIZATIONAL / CONTRACT
   DIRECTORY DATA ONLY* — and, at the top of the page body, the warning line:
   public directory evidence is discovery evidence only; the scanner never infers
   capacity, candidate supply, a relationship, or an acquisition outcome.
3. The page lands on the **Opportunity Packet** tab — no tab click needed. Read
   the framing caption aloud: the packet "never renders a score, ranking, or
   bid/no-bid recommendation." That sentence is the product thesis; the next
   ten minutes are its proof.

## Act 2 — Assemble the packet (7 minutes)

Work top to bottom. Each input feeds one section of the rendered packet below; the
packet re-renders live as evidence attaches. The say-lines are the honest version of
each beat — the demo's credibility rests on never overclaiming what a section knows.

1. **Origin — Radar handoff intake.** Tick *"Use the bundled SYNTHETIC example
   instead of an upload"* and click **Use handoff** (or upload a `radar-handoff/v1`
   JSON downloaded from GovConRadar's Contract Detail page — see operator notes).
   The PIID, county, state, and worksite city prefill.
   *Say:* the upstream radar found this expiring contract; its file carries labeled
   claims that prefill retrieval inputs only. Nothing from the handoff is treated
   as verified — the analyst re-pulls the contract facts live in the next beat, and
   the handoff never feeds the gate or any other assessment. The rendered section
   is titled "context, not evidence," and that is exactly the design.
2. **Contract PIID (analyst paste).** Already prefilled by the handoff; otherwise
   paste one. Click **Pull contract facts (live)**.
   *Say:* one analyst-initiated request to USAspending, cited with source URL and
   retrieval time. If several awards share the PIID, the app asks the analyst to
   pick the exact award — it never auto-picks. Obligated dollars and the ceiling
   stay distinct; a missing amount reads "not reported," never $0.00. The pull
   also cites the award's reported description and place of performance and
   prefills empty place inputs. **Offline note (ADR-025):** the bundled
   SYNTHETIC PIID (`SYNTH-A2-0001`, prefilled by the handoff above) resolves
   from a committed, invented sample instead of a network call — the section
   still populates fully, labeled "SYNTHETIC example — offline, not a live
   retrieval" throughout, never `Assurance API_RETRIEVED`. A real PIID still
   needs a network connection.
3. **Eligibility gate.** Scroll the rendered packet: the gate sits above all other
   evidence and now reads from the live set-aside code, superseding the analyst
   field.
   *Say:* blank means **Unknown**, never "unrestricted" — the gate fails closed.
   Eligibility is a gate, not a score component.
4. **Capture window.** Rendered automatically once live facts attach.
   *Say:* an honest **band** for the likely follow-on solicitation and the R2a
   start-by date, computed from the contract's potential end date and owner-attested,
   effective-dated lead-time defaults — an estimate labeled as one, not a prediction.
5. **Incumbent & teaming leads.** Optionally click **Pull subaward records (live)**
   (enabled once a single award is resolved) and/or upload an *AbilityOne NPA
   directory workbook (.xlsx)*.
   *Say:* competition-posture codes and reported subawardees are **leads, never
   verdicts** — a subaward is teaming-posture evidence, not proof of a relationship,
   and a directory name match is an exact-name cross-reference, not an endorsement.
6. **Contract staffing scenario inputs.** Enter a baseline and scenario in hours
   mode, or tick the FTE mode checkbox.
   *Say:* the marginal effect on the agency-wide direct-labor ratio, as a labeled
   planning indicator — never an official ODLH compliance determination. FTE mode
   says on its face it is an approximation: a headcount cannot split one person's
   supervisory hours from their direct-labor hours.
7. **Geography context.** County and state are prefilled by the live facts pull
   (or the handoff); confirm them, then click **Pull ACS geography context (live)**.
   *Say:* one cited Census ACS county figure — context for the conversation, not a
   claim about candidate supply.
8. **Procurement List cross-reference (R2b).** Tick *"Use the bundled SYNTHETIC
   example instead of an upload"* (or upload a real *AbilityOne PL Services workbook*
   and attest its retrieval date) and click **Cross-reference the Procurement List**.
   *Say:* an exact city/state match against the workbook. A match is a
   "confirm whose line this is" prompt — the export names no performing agency. A
   no-match is **evidence absence**, not "off the Procurement List": the exact-city
   key cannot see base-named or adjacent-metro worksites.
9. **Federal Register PL-notice pull.** Click **Pull Procurement List activity
   (live)**, optionally with a search term.
   *Say:* the Commission's own notice stream, listed and cited, never interpreted —
   a national list, not a claim about this contract. A search term is a text search,
   not a relevance determination.
10. **R2a determination-support map.** Always the packet's last section.
    *Say:* nothing new is computed here — the map routes whatever evidence attached
    above onto the four suitability criteria of 41 CFR 51-2.4(a), and states plainly,
    per criterion, what is absent. The Commission determines suitability; this sheet
    equips the human making the case.

## Act 3 — The export (2 minutes)

Click **Export Opportunity Packet (Markdown)**. Open the downloaded file next to the
screen and show that the body is verbatim what the room just watched — wrapped in
what the screen doesn't carry: a stamped header with the attestation disclaimers,
the **Section ledger** (every section, included or honestly absent, with the
reason), and the **Source manifest** (every attached source's reference, retrieval
time, and assurance).

*Say:* this file is the deliverable — an analyst can hand it to leadership and every
line in it can be traced to its source or is labeled Unknown.

## Act 4 (optional) — The case tracker (3 minutes)

The same page's other tabs are the repeatable evidence workflow around the packet:
**New Case** (create a public-location case), **Scan & Evidence** (import a current
NIB or SourceAmerica workbook, then separately the AbilityOne Services workbook —
one upload normally cannot satisfy both evidence gates), **Verification**, and
**Assessment** — which reports evidence *readiness*, never a score. Case lifecycle
states are distinct from evidence-readiness labels by design.

## Act 5 (optional) — Governance close (2 minutes)

End on **Privacy & Governance**: the synthetic-data validation, the public-evidence
boundary, and the page's stated decision boundaries and enforcement limits. This is
the governance close: show that the bundled examples pass their synthetic-data
contracts and that public evidence remains isolated, provenance-tracked, and subject
to explicit human review.

## Ask the room

- Could you hand this export to leadership as-is? What's missing from it?
- Which caveat would you phrase differently — and which would you delete? (If the
  answer is "delete," that's a conversation about what the evidence can actually
  support.)
- Does the R2a map match how you'd brief a suitability case today?
- Is the capture-window band honest enough to schedule real work against?
- What evidence would justify a governed pilot with real uploads?

## Operator notes

- **Live pulls:** the packet page has exactly four independent analyst-initiated
  live requests — USAspending contract facts, USAspending subawards, Census ACS,
  Federal Register PL notices. Each fires only on its own explicit button and fails
  loud if the source is unavailable. The ACS pull requires a free Census API key
  (observed live 2026-07-22: keyless requests get a "Missing Key" page): set the
  `TENS_HQ_CENSUS_API_KEY` environment variable before launching, or the pull
  fails loud with sign-up instructions. The key rides only the wire request —
  cited source URLs stay keyless by construction (test-locked). Everything else is offline; for a no-network
  demo, skip them and run on the bundled SYNTHETIC examples. **The Contract
  Facts pull is the one exception (ADR-025): the bundled SYNTHETIC PIID
  `SYNTH-A2-0001` now resolves from a committed offline sample instead of a
  network call, so that section (and the Eligibility Gate and Capture Window
  it feeds) populates fully offline, clearly labeled SYNTHETIC throughout —
  never `Assurance API_RETRIEVED`. Every other PIID still needs a network.**
  The packet stays honest about what's missing — the gate reads Unknown, Geography shows its
  placeholder, and the R2a map states per criterion what is absent; sections whose
  evidence was never attached are omitted from the body and listed as not included,
  with the reason, in the export's Section ledger.
- **Radar handoff:** the upload comes from GovConRadar's Contract Detail page
  ("Download ReconRadar handoff"). Until that producer is deployed to the Radar app
  you're demoing from, use the bundled SYNTHETIC example — same contract shape,
  clearly labeled synthetic.
- **Stale-state guards:** results re-attach only while their inputs still match
  (PIID, award, place, workbook, search term). Editing an input detaches the stale
  result rather than showing it against the wrong contract — expected behavior, not
  a bug.
- **In-app guided tour:** the sidebar "▶ Guided demo" follows this script's
  sequence (packet-first, governance close last). The BD page now lands on the
  Opportunity Packet tab, so the packet beats need no manual tab click; the
  tour still switches pages for the governance close, and its beat captions
  quote the real widget labels, locked by a test against the page source.
- **Counsel-gated content:** the C3/C4 claims (named with their citations in
  ADR-020 and the counsel packet) are with counsel and are excluded from the
  packet's copy. Guard tests lock the whole rendered packet, the full export,
  the guided-tour copy, and every packet module's source text against that
  vocabulary. Do not ad-lib it into the demo.
- **If asked why the page is titled the way it is:** the page is titled to match
  the thesis — it records cited evidence and case state, never a feasibility score.

## What we can do next

- The real-PIID dry run ran 2026-07-22 (a real expiring DoD delivery order,
  live pulls, export reviewed line-by-line); its Census-key catch is handled
  in the operator notes above. Remaining rehearsal gap: R2b with a REAL
  PL Services workbook (an analyst-supplied upload).
- Pilot packaging shipped: see `PILOT_RUNBOOK.md` (`TENS_HQ_PILOT_MODE=1`
  hides the guided tour and planning controls). Its DRAFT success criteria await
  owner sign-off.
