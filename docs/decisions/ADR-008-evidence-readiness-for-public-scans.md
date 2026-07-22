# ADR-008: Evidence readiness replaces numeric feasibility for public scans

## Status

Accepted for v0.2 public scanner cases

## Context

Numeric feasibility models depend on calibrated evidence and explicit assumptions. Synthetic outcomes, positive defaults for missing evidence, and a Boolean relationship input are unsafe for public directory records and cannot establish candidate supply or partner capacity. ADR-016 records removal of the earlier synthetic feasibility implementation.

## Decision

Public scanner cases use a nonnumeric readiness contract: `Insufficient`, `Researching`, `Verified`, and `Validated`. A score, candidate-volume estimate, capacity claim, partner commitment, proposal-ready staffing claim, or bid/no-bid action is withheld.

`Verified` requires a resolved city/state location, a current successful or acknowledged partial import that is still fresh, an explicit analyst route-resolution event with a source label and rationale, at least one current resource verified for geographic and service relevance, and no blocking route, conflict, anomaly, reconciliation, geographic, or service tasks.

Freshness is gated on the analyst-attested **source retrieval time** (`retrieved_at`), never the system import time: an old workbook uploaded today is not fresh just because its import just finished. Each source kind carries its own retrieval-freshness budget in `SOURCE_FRESHNESS_POLICY` (`case_store.py`), and every budget declares an `effective_date` so a stored readiness result can be reproduced and audited rather than depending on a silent global constant. When a source's retrieval time is unknown (no `retrieved_at` supplied) or older than its budget, the `current_import` requirement is `NEEDS_VERIFICATION`, which keeps the case out of `Verified`/`Validated`. The per-source budgets — NIB/SourceAmerica 180 days, AbilityOne Services 90 days, and a 30-day default for any other source kind — are **provisional pending owner confirmation** of the real publication cadence for each source. Capability and relationship review remain advisory and never imply capacity. `Validated` additionally requires an analyst validation event with a fingerprint of the case version, current row set, and blocking task set. A partial run may support readiness only after its blocking anomaly/reconciliation tasks are resolved. Every terminal snapshot defines the current set; omitted prior rows become historical and raise a blocking reconciliation task. National rows outside the case location are advisory when local rows were retained; they become blocking only when a scan yields no local rows.

The persisted case state named `Validated` and the rendered readiness label `Validated` are related but distinct vocabularies. The complete evidence path requires both a separately reviewed geographically relevant NIB/SourceAmerica organization row and a separately reviewed parsed AbilityOne Services row, plus the independent route-resolution and blocking-task gates. A single workbook import normally cannot satisfy the full path.

## Consequences

The page can tell a BD analyst what is known, what is missing, where to verify, and whether the evidence is current. It cannot manufacture precision from directory counts. Any future calibrated real-data model requires new evidence, formula versions, test vectors, and governance approval; the legacy synthetic calculator and capture board remain removed under ADR-016.
