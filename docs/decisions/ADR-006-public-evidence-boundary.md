# ADR-006: Public evidence is a separate scanner boundary

## Status

Accepted for the v0.2 public-evidence pilot

## Context

ADR-001 kept the concept demo synthetic-only and rejected public directories because a real organization next to fictional outcomes could imply a relationship that was never verified. The BD question now needs a governed discovery workflow, but a directory record is not proof of capacity, availability, capability, or commitment.

## Decision

Add a separate public-evidence boundary. It may ingest only strict, allowlisted fields from the current official AbilityOne NIB, SourceAmerica, and Services workbook exports. The scanner stores public organizational/contract evidence and provenance, never applicant, employee, medical, disability, eligibility, contact-person, home-address, CUI/FCI, or proprietary planning data. Public rows never join to synthetic outcomes and never become partners automatically.

The v0.2 connector is an analyst-selected workbook import from the official report page. It does not scrape PLIMS, call undocumented endpoints, accept arbitrary URLs, or fetch at runtime. Exact source schemas, parser versions, hashes, analyst-supplied retrieval timestamps, import timestamps, and analyst-attested provenance are retained as metadata; workbook bytes are not retained. Rows excluded by case-location scope are retained only in a bounded quarantine table and never become current evidence.

### Implementation mechanism: a person-PII denylist, not a field allowlist

The phrase "only strict, allowlisted fields" above describes the intent. The shipped enforcement (`ensure_public_payload` in `evidence.py`) is a **person-PII denylist**, not a strict field allowlist: it rejects a known set of person-level keys (`_PERSON_PII_KEYS`) at every nesting depth and default-allows any other public-organization field. Rejected keys include direct person/employee/applicant/candidate/contact IDs, source-native identifiers, SSNs, medical/disability/eligibility narratives and documents, a named individual's personal contact (`contact_name`/`contact_email`/`contact_phone`/`personal_email`/`home_address`), the **bare, unprefixed contact channels** (`phone`/`mobile`/`telephone`/`email`/`address`/`street_address`), and attachments. An organization's public contact line is allowed only through explicit `org_`-prefixed keys (`org_phone`/`org_email`/`org_address`, plus `org_url`/`org_website`/`org_public_url`) or, for a web address only, bare `url`/`website`/`public_url` — a public web address is not personal PII.

The trust boundary this draws: a connector must never attach a named individual's personal contact to a generic key. Because the wall default-allows unknown keys, a bare `email`/`phone`/`address` value would silently pass, so those channels are denied and a public organization's contact must be attached through the `org_`-prefixed keys. A future move to a true strict allowlist (enumerate every accepted field) would tighten this further and is a candidate for a production hardening ADR.

## Consequences

- The bundled synthetic validation boundary remains isolated from public evidence. ADR-016 records that the legacy synthetic feasibility calculator (`feasibility.py`) and its Opportunity Recon capture board were deleted; neither is part of the current app.
- Public scan results are typed discovery evidence. The current implementation stores generic row review, derives separate geographic and service readiness gates, and records acquisition-route resolution. Capability and relationship remain advisory and are not independent gating states.
- Unknown, stale, partial, and failed evidence cannot become positive or zero evidence.
- A future production multi-user implementation still requires identity, authorization, encryption, records management, source terms review, and formal HR/privacy/security/compliance approval.

## Alternatives considered

- **Live PLIMS scraping:** rejected because the public page exposes an undocumented dynamic endpoint and its contract/rate limits are not a stable integration boundary.
- **Mix public directories into `DemoData`:** rejected because it would imply fictional outcomes or relationships.
- **General web search:** rejected because source authority, reproducibility, licensing, and prompt-injection controls would be unclear.
