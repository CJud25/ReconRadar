# ReconRadar architecture

## Purpose

ReconRadar (part of TENS HQ) is a packet-only Streamlit application for AbilityOne NPA business development. It assembles a cited, score-free Opportunity Packet for one prospective opportunity and provides a local case tracker for reviewing public organizational and contract-directory evidence. The shipped navigation has exactly two pages: **BD Feasibility** and **Privacy & Governance**.

The architecture favors explicit analyst actions, typed source records, reproducible provenance, fail-closed gaps, and human decisions. It does not compute an opportunity score, ranking, suitability determination, or bid/no-bid recommendation.

## Components

1. **Application shell** (`app.py`, `pages.py`, `roles.py`) configures the two-page Streamlit surface. Pilot mode does not grant or remove page access; it narrows presentation by hiding the guided tour and planning controls.
2. **Packet workspace** (`bd_page.py`) collects a Radar handoff, a PIID, place inputs, official workbook uploads, and analyst-entered assumptions. The handoff is context for prefilling retrieval inputs, never verified evidence.
3. **Bounded connectors** (`connectors/`) parse recognized AbilityOne workbooks and perform four independent, analyst-initiated live pulls: USAspending contract facts, USAspending subawards, Census ACS geography context, and Federal Register Procurement List notices. Each pull fails visibly rather than substituting an empty success.
4. **Packet sections** (`eligibility_gate.py`, `capture_window.py`, `incumbent_leads.py`, `staffing_whatif.py`, `pl_match.py`, `pl_activity.py`, `r2a_map.py`) turn attached evidence or labeled analyst inputs into caveat-first Markdown. They do not compute a composite score, ranking, suitability determination, or bid/no-bid recommendation.
5. **Packet assembler and export** (`opportunity_packet.py`, `packet_export.py`) preserve the rendered packet body and add a stamped header, a section ledger that records included and absent sections, and a source manifest with references, retrieval times, and assurance labels.
6. **Public-evidence case tracker** (`cases.py`, `scanner.py`, `evidence.py`, `case_store.py`) stores restart-safe cases, source snapshots, immutable observations, row reviews, route resolutions, tasks, events, and validation fingerprints in local SQLite.
7. **Synthetic validation boundary** (`synthetic.py`, `validation.py`) creates deterministic, clearly labeled demonstration fixtures and validates their privacy/schema contracts for the governance page. Synthetic fixtures never join to public evidence or become claims about real organizations or people.

## Packet data flow

```text
Radar handoff (context only) + analyst inputs
             + explicit live pulls + recognized workbook uploads
                                  |
                                  v
                 typed connector/source records
                                  |
                                  v
          caveat-first packet sections and R2a evidence map
                                  |
                                  v
                    rendered Opportunity Packet
                                  |
                                  v
              Markdown export + section ledger + source manifest
```

The packet is assembled in the Streamlit session and exported on demand. Editing an input detaches a result whose provenance no longer matches. Unknown, missing, stale, partial, or failed evidence stays visible as a gap; it is never converted to zero or positive evidence.

## Case-tracker data flow

```text
Analyst-selected official workbook
               |
               v
recognized schema -> bounded parser -> normalized public rows
               |                         |
               |                         v
               +---- failure --------> blocking task
                                         |
                                         v
                    SQLite evidence ledger and history
                                         |
                                         v
                 analyst review + route resolution + tasks
                                         |
                                         v
       Insufficient / Researching / Verified / Validated
```

Each scan belongs to one case, one source kind, and one workbook. The parser searches a bounded prefix for an exact recognized header, rejects unknown or duplicate schemas, limits XLSX expansion, and projects only the connector's supported fields. The ledger stores hashes, normalized rows, provenance metadata, observations, and audit events; it does not store workbook bytes.

The full evidence path normally requires a reviewed NIB- or SourceAmerica-affiliated organization row and a separately reviewed parsed AbilityOne Services row, plus an explicit route resolution and no open blocking tasks. Directory presence remains discovery evidence, not proof of capacity, capability, availability, relationship, commitment, or acquisition outcome.

## State vocabulary

| Vocabulary | Values | Meaning |
|---|---|---|
| Persisted case lifecycle | `Draft`, `Scanning`, `Needs Verification`, `Validated`, `Closed` | Case workflow and terminal state |
| Evidence readiness | `Insufficient`, `Researching`, `Verified`, `Validated` | Completeness, freshness, review, and blocking-task status of the public-evidence record |

The two uses of `Validated` are related but distinct. Evidence readiness is nonnumeric, while case lifecycle records the repository workflow.

## Trust and storage boundaries

- Public workbook rows never enter the synthetic demonstration data.
- Live sources are called only after the analyst presses the corresponding control; the app does not scrape PLIMS, call undocumented endpoints, or fetch arbitrary URLs.
- Packet-only is the fail-safe default. The case ledger is constructed only when `TENS_HQ_ENABLE_CASE_LEDGER=1`; the shared hosted demo leaves it disabled.
- The case ledger is local, single-user pilot infrastructure. It is not an authentication, authorization, encryption, backup, records-management, or multi-user boundary.
- Role and team aliases stored on cases are descriptive metadata, not access control.
- The existing `TENS_HQ_*` environment-variable names are retained as the umbrella-family prefix.

## Production transition

A production implementation should preserve the typed connector contracts, fail-closed evidence semantics, pure packet renderers, immutable provenance, section ledger, source manifest, and readiness truth table. Before real shared use, it also needs approved identity and authorization, encryption, retention and correction rules, backup and recovery, integrity and migration checks, source-terms review, monitoring, accessibility review, and formal security/privacy/compliance approval.
