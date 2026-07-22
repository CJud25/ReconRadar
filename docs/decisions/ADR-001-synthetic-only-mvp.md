# ADR-001: Synthetic-only MVP

## Status

Accepted for the bundled synthetic-example boundary; partially superseded by ADR-006 for the isolated public-evidence pilot

## Date

2026-07-17

## Context

ReconRadar must be demonstrated and its governance checks exercised without requiring unapproved applicant, employee, HR, timekeeping, partner, or compliance data.

## Decision

The bundled demonstration boundary generates its fixtures from a deterministic seed. Every synthetic table has `synthetic_flag`, person-like labels say Synthetic, IDs use `SYN-` prefixes, contacts use `example.invalid`, and validation fails if these contracts are violated.

ADR-006 introduces one narrow exception: an isolated public-evidence scanner may ingest allowlisted public organizational/contract directory fields. That exception does not permit real people, applicants, employees, internal outcomes, partner assertions, or public-to-synthetic outcome joins.

## Alternatives considered

- **De-identified internal data:** rejected because re-identification and authorization risks remain, and internal data are unnecessary to test product usefulness.
- **Public partner directories in the synthetic model:** rejected because mixing real organizations with fictional outcomes would imply unsupported relationships. ADR-006 later permits a separate evidence boundary without those joins.

## Consequences

The bundled examples can test offline workflow clarity and boundary validation. They cannot establish predictive accuracy, official compliance status, actual partner availability, or real-world impact. The public scanner supports cited evidence review only; it does not change those limits.
