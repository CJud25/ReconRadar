# ADR-007: SQLite evidence ledger for the local pilot

## Status

Accepted for v0.2 local pilot

## Context

The existing feasibility page stores only the last form in Streamlit session state. A legitimate scanner needs durable cases, scan history, source snapshots, analyst tasks, current-versus-historical observations, and an audit trail.

## Decision

Use a small standard-library `sqlite3` repository under `data/runtime/` (overridable by `TENS_HQ_DB_PATH`). Enable foreign keys, WAL, a busy timeout, parameterized SQL, explicit transactions, schema metadata, optimistic case versions, and one running scan per case. The model includes cases, requirements, scan runs, source snapshots/records, immutable evidence assertions, scan observations, case-resource review states, verification tasks, readiness/validation fingerprints, and case events.

Each scan is one case, one source kind, and one uploaded workbook. Parsing happens outside the write transaction. A running scan is committed first; valid results and terminal status commit atomically. A running scan older than 15 minutes is recovered as `failed`, creates or retains a blocking `SCAN_FAILED` task, and records a recovery event. Failed scans preserve prior evidence. Migrations fail closed and no destructive auto-reset is attempted for a corrupt database.

## Consequences

SQLite is appropriate for a local, single-user pilot and restart-safe tests. It is not an authorization boundary, encrypted store, tenant database, scheduler, or production multi-user system. A governed production implementation must replace it with an approved managed store and identity/audit controls while preserving the evidence contracts.
