-- Durable public feasibility case/evidence tracker schema.
--
-- Migrations are additive and are intentionally free of DROP/DELETE/REPLACE
-- statements.  CaseStore runs this file only after enabling foreign keys.

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    postal_code TEXT,
    team_alias TEXT NOT NULL,
    role_alias TEXT NOT NULL,
    state_name TEXT NOT NULL DEFAULT 'Draft',
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    last_error TEXT,
    contract_type TEXT,
    service_type TEXT,
    target_headcount INTEGER,
    target_start_date TEXT,
    job_family_requirements_json TEXT NOT NULL DEFAULT '[]',
    CHECK (length(trim(city)) > 0),
    CHECK (length(state) = 2),
    CHECK (postal_code IS NULL OR length(postal_code) = 5)
);

CREATE TABLE IF NOT EXISTS scan_runs (
    scan_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE RESTRICT,
    source_kind TEXT NOT NULL,
    workbook_name TEXT NOT NULL,
    workbook_sha256 TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'partial', 'failed')),
    prior_state TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error_message TEXT,
    row_count INTEGER,
    snapshot_id TEXT,
    idempotency_key TEXT,
    source_label TEXT,
    source_version TEXT,
    assurance TEXT,
    retrieved_at TEXT,
    actor_role TEXT,
    source_uri TEXT,
    byte_size INTEGER,
    schema_fingerprint TEXT,
    payload_retained INTEGER NOT NULL DEFAULT 0 CHECK (payload_retained IN (0, 1)),
    source_row_count INTEGER,
    excluded_row_count INTEGER NOT NULL DEFAULT 0 CHECK (excluded_row_count >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS one_running_scan_per_case
    ON scan_runs(case_id) WHERE status = 'running';

CREATE INDEX IF NOT EXISTS scan_runs_case_idx ON scan_runs(case_id, started_at DESC);
CREATE INDEX IF NOT EXISTS scan_runs_request_idx
    ON scan_runs(case_id, request_fingerprint, status);
CREATE INDEX IF NOT EXISTS scan_runs_idempotency_idx
    ON scan_runs(case_id, idempotency_key, started_at DESC);

CREATE TABLE IF NOT EXISTS source_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    scan_id TEXT NOT NULL REFERENCES scan_runs(scan_id) ON DELETE RESTRICT,
    case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE RESTRICT,
    source_kind TEXT NOT NULL,
    workbook_name TEXT NOT NULL,
    workbook_sha256 TEXT NOT NULL,
    source_uri TEXT,
    observed_at TEXT NOT NULL,
    row_count INTEGER NOT NULL CHECK (row_count >= 0),
    schema_fingerprint TEXT,
    source_label TEXT,
    source_version TEXT,
    assurance TEXT,
    retrieved_at TEXT,
    actor_role TEXT,
    byte_size INTEGER,
    payload_retained INTEGER NOT NULL DEFAULT 0 CHECK (payload_retained IN (0, 1)),
    source_row_count INTEGER,
    excluded_row_count INTEGER NOT NULL DEFAULT 0 CHECK (excluded_row_count >= 0)
);

CREATE INDEX IF NOT EXISTS source_snapshots_case_idx
    ON source_snapshots(case_id, source_kind, observed_at DESC);

CREATE TABLE IF NOT EXISTS source_records (
    resource_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE RESTRICT,
    source_kind TEXT NOT NULL,
    stable_key TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    display_name TEXT,
    public_url TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    review_status TEXT NOT NULL DEFAULT 'unreviewed'
        CHECK (review_status IN ('unreviewed', 'verified', 'rejected')),
    review_note TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (case_id, source_kind, stable_key, row_hash)
);

CREATE INDEX IF NOT EXISTS source_records_current_idx
    ON source_records(case_id, source_kind, is_current);

-- Rows that were parsed safely but excluded from a location case are retained
-- as bounded quarantine metadata.  They never become current evidence, but a
-- reviewer can explain why a national source row was not imported locally.
CREATE TABLE IF NOT EXISTS source_exclusions (
    exclusion_id TEXT PRIMARY KEY,
    scan_id TEXT NOT NULL REFERENCES scan_runs(scan_id) ON DELETE RESTRICT,
    case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE RESTRICT,
    source_kind TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    source_row INTEGER,
    parse_status TEXT NOT NULL,
    parse_note TEXT,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (scan_id, row_hash, reason)
);

CREATE INDEX IF NOT EXISTS source_exclusions_case_idx
    ON source_exclusions(case_id, source_kind, created_at DESC);

CREATE TABLE IF NOT EXISTS evidence_observations (
    observation_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id) ON DELETE RESTRICT,
    resource_id TEXT NOT NULL REFERENCES source_records(resource_id) ON DELETE RESTRICT,
    row_hash TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    UNIQUE (snapshot_id, resource_id)
);

CREATE INDEX IF NOT EXISTS evidence_observations_resource_idx
    ON evidence_observations(resource_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS route_hypotheses (
    hypothesis_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE RESTRICT,
    route_kind TEXT NOT NULL,
    target TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    source_label TEXT,
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    status TEXT NOT NULL DEFAULT 'hypothesis'
        CHECK (status IN ('hypothesis', 'resolved', 'rejected')),
    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS route_resolutions (
    resolution_id TEXT PRIMARY KEY,
    hypothesis_id TEXT NOT NULL REFERENCES route_hypotheses(hypothesis_id) ON DELETE RESTRICT,
    case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE RESTRICT,
    decision TEXT NOT NULL CHECK (decision IN ('resolved', 'rejected')),
    rationale TEXT NOT NULL DEFAULT '',
    resolved_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS route_hypotheses_case_idx ON route_hypotheses(case_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS readiness_items (
    item_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE RESTRICT,
    item_key TEXT NOT NULL,
    label TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('verified', 'needs_verification', 'missing', 'not_applicable')),
    is_blocking INTEGER NOT NULL DEFAULT 1 CHECK (is_blocking IN (0, 1)),
    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    note TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (case_id, item_key)
);

CREATE INDEX IF NOT EXISTS readiness_items_case_idx ON readiness_items(case_id, is_blocking, state);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE RESTRICT,
    task_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('blocking', 'advisory')),
    title TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE (case_id, fingerprint)
);

CREATE INDEX IF NOT EXISTS tasks_case_open_idx ON tasks(case_id, status, severity);

CREATE TABLE IF NOT EXISTS fingerprints (
    fingerprint TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS case_events (
    event_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    scan_id TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS case_events_case_idx ON case_events(case_id, created_at DESC);
