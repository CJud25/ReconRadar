# Changelog

## [Unreleased]

### Changed

- The Opportunity Packet tab is now the landing surface on the BD page (first paint, no manual tab click), and the guided tour's packet beats were re-cut to describe the already-open packet instead of instructing the operator to open a tab it couldn't reach.
- The Privacy & Governance page's "Decision boundaries" and "Data inventory" framing were corrected to describe only shipped capabilities (ADR-024); the page no longer references deleted concepts (site views, source scores, organization scenarios, small-sample shrinkage, the start-stage gate).
- Cited source URLs (packet body and export manifest) render as clean autolinks instead of backslash-escaped Markdown, so a pasted citation resolves correctly.
- Packet-path connector failures log via `logging.getLogger` and no longer mislabel an internal bug as a public-source outage.

### Added

- The bundled synthetic PIID resolves into honestly-labeled, offline SYNTHETIC-example Contract Facts (never `API_RETRIEVED`, never a live award URL), so the offline guided demo reaches a populated flagship moment with no red error (ADR-025).
- A bundled synthetic NIB/NPA workbook sample and an in-app affordance to scan it offline.

## [1.0.0] - 2026-07-22

### Added

- Initial public release of ReconRadar: the cited, score-free Opportunity Packet and public-evidence case tracker for AbilityOne NPA business development.
- **Retrieve/parse API boundary** (ADR-011): every public connector (Census ACS, USAspending, Federal Register) separates a network `retrieve` step from a pure `parse` step, with `Assurance.API_RETRIEVED` provenance and bounded, fail-loud `ConnectorError` mapping.
- **Eligibility Gate** (ADR-013): presents set-aside evidence for the N6 slice as a cited state, never a pursuit verdict.
- **Contract Facts** (ADR-014): live USAspending award-detail facts resolved to an exact single award, with obligated and ceiling values kept as distinct labeled lines.
- **Capture Window** (ADR-015): an honest band anchored to the solicitation, never a manufactured contract-end-date estimate.
- **Incumbent & teaming leads** (ADR-017): a cited packet of leads, never a computed share.
- **Packet export assembler** (ADR-018): a composed, cited export document — Section ledger plus Source manifest — never a re-derivation of the packet's facts.
- **Radar handoff intake** (ADR-019): an uploaded claim, gated onto the packet tab, never auto-trusted.
- **Owner-attested domain constants** (ADR-020): the ODLH/PLDLH-EDLH ratio definitions and related constants, attested by the pilot NPA's compliance coordinator, replacing provisional guesses.
- **Staffing what-if** (ADR-021): an agency-wide ODLH planning indicator computed from analyst-entered hypothetical input, never a determination.
- **R2a determination-support map** (ADR-022): routes citations to the four suitability criteria; it never assesses or scores them.
- **Federal Register PL notices** (ADR-023): a cited national notice-list pull from the Federal Register API, never a claim about the specific contract in the packet.
- **Legacy synthetic feasibility removed** (ADR-016): the "Opportunity Recon" capture board and its `ready_to_pursue_score` formula were deleted before this release, keeping the shipped product to its one, score-free identity.
