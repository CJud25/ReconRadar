# ADR-003: Status-only eligibility boundary

## Status

Accepted

## Date

2026-07-17

## Context

The Opportunity Packet presents reported contract set-aside status and related evidence for analyst review. ReconRadar must not turn that status into an independent eligibility determination or become an informal medical or disability-document repository.

## Decision

Treat eligibility as status-only evidence. The packet may present a cited or analyst-entered status, including an explicit unknown state, but the human remains responsible for the determination. No medical/disability content, eligibility document, file path, or accommodation information belongs in this boundary.

## Alternatives considered

- **Store diagnosis or eligibility-document examples:** rejected because it normalizes a harmful future data model and adds no packet value.
- **Remove eligibility status entirely:** rejected because the packet must present the contract's reported set-aside evidence while keeping the decision with the analyst.

## Consequences

A future approved system must source the minimum necessary status from an authoritative process. ReconRadar will not independently determine eligibility.
