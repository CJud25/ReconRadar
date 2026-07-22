# Privacy and governance statement

ReconRadar (part of TENS HQ) assembles cited public evidence for a prospective business-development opportunity and tracks the review state of public organizational and contract-directory evidence. It does not evaluate the value, disability status, employability, or suitability of any person.

## Data boundary

The retained product handles four deliberately separated kinds of input:

- **Public contract facts and notices**, retrieved only through an explicit analyst action from USAspending, Census ACS, or the Federal Register.
- **Official public-directory workbooks**, selected by the analyst and parsed through recognized, bounded schemas for AbilityOne NPA and Services data.
- **Analyst-entered opportunity context and aggregate planning assumptions**, used to assemble the current packet and its export. A staffing what-if is a labeled planning indicator, never an official ODLH compliance determination.
- **Bundled synthetic examples**, visibly marked `SYNTHETIC` and isolated from public evidence. They support offline demonstration and governance validation; they make no claim about a real person, organization, contract, relationship, or outcome.

ReconRadar excludes diagnoses, disability narratives, medical records, accommodation information, eligibility-document images, person-level applicant or employee data, personal contact details, CUI/FCI, and proprietary records from the public-evidence tracker. Public evidence never joins to synthetic people or outcomes.

## Collection and retention

The application does not scrape PLIMS, call undocumented endpoints, accept arbitrary URLs for ingestion, or make a live request without the analyst pressing its specific control. Recognized workbook connectors bound file size and expansion, locate an exact supported header, reject unknown or duplicate schemas, and project only supported fields. The evidence payload wall also rejects known person-level and personal-contact keys.

The local case ledger stores source kind, filename label, workbook hash, parser/schema metadata, analyst-supplied retrieval time, import time, normalized public rows, immutable observations, row-review state, route resolutions, tasks, case events, and validation fingerprints. It does not retain workbook bytes. Packet results live in the application session and in any Markdown export the analyst chooses to save; operators remain responsible for protecting those exports and the host on which ReconRadar runs.

## Evidence and decision boundaries

- A Radar handoff is labeled context and may prefill retrieval inputs; it is not verified evidence and never drives another assessment.
- Directory presence is discovery evidence, not proof of capacity, capability, availability, relationship, commitment, candidate supply, or acquisition outcome.
- A workbook no-match is evidence absence within that source and matching key, not proof that an item is absent from the Procurement List.
- Contract and subaward records are cited leads, not incumbent, teaming, or relationship verdicts.
- Census geography is context, not a claim about workforce supply.
- Capture-window dates are owner-attested methodology bands that still require contract-specific confirmation.
- The R2a map routes attached evidence to the four suitability criteria; the U.S. AbilityOne Commission makes the suitability determination.
- The packet never renders a composite score, ranking, official ODLH determination, or bid/no-bid recommendation.

Public-scanner readiness is deliberately nonnumeric: `Insufficient`, `Researching`, `Verified`, or `Validated`. Unknown, stale, partial, failed, conflicting, or unresolved evidence remains blocking until the applicable requirement or task is resolved. A failed scan cannot erase earlier evidence, and a later usable import—not manual dismissal alone—clears the underlying scan-failure condition.

## Pilot infrastructure limits

The SQLite ledger is local, unencrypted, and unauthenticated. It is not suitable for CUI/FCI, HR records, a shared drive, or multi-user production. Case role/team aliases are metadata and do not enforce access. The runtime has no approved backup/restore, retention, legal-hold, enterprise identity, row-level authorization, or production monitoring boundary.

Any future shared or operational deployment requires an approved purpose and data inventory, authoritative system-of-record boundaries, minimum-necessary fields, identity and least-privilege authorization, encryption, retention/correction/deletion/legal-hold rules, backup and recovery, integrity and migration checks, source-terms review, accessibility and incident procedures, and current legal/privacy, compliance, security, and IT approval.
