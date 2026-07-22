"""SQLite-backed case, scan, and public-evidence repository.

The repository is intentionally boring infrastructure: one SQLite file,
additive migration, explicit transactions, and immutable observations.  A
scanner can call :meth:`start_scan`, write a single workbook result with
:meth:`finalize_scan`, and then use the read methods to render a UI.  A failed
scan never mutates the prior source records.

Only public case data is accepted.  Locations have no county/FIPS fields,
ownership is represented by controlled aliases, and payload validation rejects
person identifiers and sensitive narratives before a transaction begins.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from hashlib import sha256
import uuid
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from .cases import (
    ALLOWED_TRANSITIONS,
    Case,
    CaseCreate,
    CaseState,
    CaseUpdate,
    CaseValidationError,
    coerce_case_state,
    ensure_transition,
    normalize_role_alias,
    normalize_team_alias,
)
from .evidence import (
    EvidenceObservation,
    EvidenceValidationError,
    ReadinessAssessment,
    ReadinessItem,
    ReadinessState,
    RouteHypothesis,
    RouteResolution,
    RouteStatus,
    SourceRecord,
    SourceSnapshot,
    Task,
    TaskSeverity,
    TaskStatus,
    assess_readiness,
    canonical_json,
    ensure_public_payload,
    fingerprint,
    row_fingerprint,
)
from .locations import Location, LocationValidationError, normalize_location


class CaseStoreError(RuntimeError):
    """Base class for durable case-store errors."""


class CaseNotFoundError(CaseStoreError, KeyError):
    """Raised when a requested case/resource/scan does not exist."""


class ScanInProgressError(CaseStoreError):
    """Raised when a case already has a running scan."""


class ScanStateError(CaseStoreError):
    """Raised when a scan is finalized in an invalid state."""


class IdempotencyConflict(ScanStateError):
    """Raised when a retry key is reused for a different source payload."""

    code = "IDEMPOTENCY"


class OptimisticLockError(CaseStoreError):
    """Raised when a caller writes an object using a stale version."""


class IntegrityError(CaseStoreError):
    """Raised for a repository integrity violation."""


class ScanStatus(str):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ScanRun:
    """Public scan-run view.

    A run always covers one case, one source kind, and one workbook.  The
    workbook is represented by name/hash metadata only.
    """

    scan_id: str
    case_id: str
    source_kind: str
    workbook_name: str
    workbook_sha256: str
    status: str
    prior_state: CaseState
    started_at: str
    finished_at: str | None = None
    error_message: str | None = None
    row_count: int | None = None
    snapshot_id: str | None = None
    idempotency_key: str | None = None
    source_label: str | None = None
    source_version: str | None = None
    assurance: str | None = None
    retrieved_at: str | None = None
    actor_role: str | None = None
    source_uri: str | None = None
    byte_size: int | None = None
    schema_fingerprint: str | None = None
    payload_retained: bool = False
    source_row_count: int | None = None
    excluded_row_count: int = 0

    @property
    def workbook_hash(self) -> str:
        return self.workbook_sha256

    @property
    def succeeded(self) -> bool:
        return self.status == ScanStatus.SUCCEEDED

    @property
    def failed(self) -> bool:
        return self.status == ScanStatus.FAILED

    @property
    def partial(self) -> bool:
        return self.status == ScanStatus.PARTIAL


@dataclass(frozen=True, slots=True)
class CaseEvent:
    """Append-only audit event view."""

    event_id: str
    case_id: str
    event_type: str
    scan_id: str | None
    detail: Mapping[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class _IncomingRow:
    stable_key: str
    row_hash: str
    payload: dict[str, Any]
    display_name: str | None
    public_url: str | None


_MISSING = object()


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    """Per-source retrieval-freshness budget with an effective date.

    ``max_age`` is measured against the analyst-attested *source retrieval
    time* (``retrieved_at``), never the system import time.  ``effective_date``
    records when this budget took effect so a stored readiness assessment can
    be reproduced and audited, and so the threshold is never a silent, global
    hard-coded constant.
    """

    max_age_days: int
    effective_date: str

    def __post_init__(self) -> None:
        if not isinstance(self.max_age_days, int) or isinstance(self.max_age_days, bool) or self.max_age_days <= 0:
            raise CaseValidationError("freshness max_age_days must be a positive integer")
        try:
            date.fromisoformat(self.effective_date)
        except (TypeError, ValueError) as exc:
            raise CaseValidationError("freshness effective_date must be an ISO date") from exc

    @property
    def max_age(self) -> timedelta:
        return timedelta(days=self.max_age_days)


# Per-source-kind retrieval-freshness budgets.  Official AbilityOne exports are
# refreshed on publication cycles that differ by source, so a single global
# 30-day window is wrong; each source declares its own budget with an effective
# date.  An unknown source kind falls back to the default, and a missing
# retrieval time is never treated as fresh.
_DEFAULT_FRESHNESS_POLICY = FreshnessPolicy(max_age_days=30, effective_date="2026-07-18")
SOURCE_FRESHNESS_POLICY: Mapping[str, FreshnessPolicy] = {
    "NIB_NPA": FreshnessPolicy(max_age_days=180, effective_date="2026-07-18"),
    "SOURCEAMERICA_NPA": FreshnessPolicy(max_age_days=180, effective_date="2026-07-18"),
    "ABILITYONE_SERVICES": FreshnessPolicy(max_age_days=90, effective_date="2026-07-18"),
}


def freshness_policy_for(source_kind: str | None) -> FreshnessPolicy:
    """Return the freshness budget for ``source_kind`` (default if unknown)."""

    if source_kind is None:
        return _DEFAULT_FRESHNESS_POLICY
    return SOURCE_FRESHNESS_POLICY.get(str(source_kind), _DEFAULT_FRESHNESS_POLICY)


class CaseRepository:
    """Durable repository for public feasibility cases and evidence.

    Parameters
    ----------
    db_path:
        SQLite path.  ``":memory:"`` is supported for tests; file-backed
        stores use WAL and survive process restart.
    clock:
        Optional zero-argument callable returning an aware ``datetime``.  It
        exists to make deterministic focused tests straightforward.
    """

    def __init__(self, db_path: str | Path = "reconops.sqlite3", *, clock: Callable[[], datetime] | None = None):
        self.db_path = str(db_path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._conn = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._configure_connection()
        self._migrate()

    def _configure_connection(self) -> None:
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 30000")
        # SQLite returns ``memory`` for :memory: databases, which is expected;
        # file-backed stores get durable WAL semantics.
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")

    def _migrate(self) -> None:
        migration = Path(__file__).with_name("migrations") / "001_cases.sql"
        sql = migration.read_text(encoding="utf-8")
        # Fail closed for ledgers that this build cannot safely interpret.
        # In particular, an older CHECK constraint may reject the terminal
        # ``partial`` state even if additive columns are present; overwriting
        # its schema marker would make the incompatibility harder to detect.
        meta_exists = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
        ).fetchone() is not None
        existing_meta = (
            self._conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            if meta_exists
            else None
        )
        if existing_meta is not None:
            try:
                version = int(existing_meta[0])
            except (TypeError, ValueError) as exc:
                raise CaseStoreError("unsupported case ledger schema version") from exc
            if version > 2:
                raise CaseStoreError("case ledger is newer than this application")
            if version < 2:
                raise CaseStoreError("case ledger requires the v2 migration before it can be opened")
        existing_scan_sql = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='scan_runs'"
        ).fetchone()
        if existing_scan_sql is not None and "'partial'" not in str(existing_scan_sql[0]).lower():
            raise CaseStoreError("case ledger requires an explicit migration before partial scans are enabled")
        if existing_scan_sql is not None:
            existing_scan_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(scan_runs)").fetchall()}
            if "idempotency_key" not in existing_scan_columns:
                raise CaseStoreError("case ledger is missing v2 scan provenance columns")
        # executescript is idempotent because the migration itself uses only
        # CREATE IF NOT EXISTS.  There is no reset/drop path.
        self._conn.executescript(sql)
        # Failed requests remain retryable under the same idempotency key, so
        # the key is intentionally indexed rather than unique.  Older pilot
        # ledgers briefly created a unique index; replace it safely.
        self._conn.execute("DROP INDEX IF EXISTS scan_runs_idempotency_idx")
        self._conn.execute("CREATE INDEX IF NOT EXISTS scan_runs_idempotency_idx ON scan_runs(case_id, idempotency_key, started_at DESC)")
        # Keep the pilot additive for databases created by an earlier build.
        # New installations get the complete schema above; existing local
        # ledgers receive nullable provenance columns without a data reset.
        additive = {
            "cases": {
                "contract_type": "TEXT",
                "service_type": "TEXT",
                "target_headcount": "INTEGER",
                "target_start_date": "TEXT",
                "job_family_requirements_json": "TEXT NOT NULL DEFAULT '[]'",
            },
            "scan_runs": {
                "idempotency_key": "TEXT",
                "source_label": "TEXT",
                "source_version": "TEXT",
                "assurance": "TEXT",
                "retrieved_at": "TEXT",
                "actor_role": "TEXT",
                "source_uri": "TEXT",
                "byte_size": "INTEGER",
                "schema_fingerprint": "TEXT",
                "payload_retained": "INTEGER NOT NULL DEFAULT 0",
                "source_row_count": "INTEGER",
                "excluded_row_count": "INTEGER NOT NULL DEFAULT 0",
            },
            "source_snapshots": {
                "source_label": "TEXT",
                "source_version": "TEXT",
                "assurance": "TEXT",
                "retrieved_at": "TEXT",
                "actor_role": "TEXT",
                "byte_size": "INTEGER",
                "payload_retained": "INTEGER NOT NULL DEFAULT 0",
                "source_row_count": "INTEGER",
                "excluded_row_count": "INTEGER NOT NULL DEFAULT 0",
            },
            "route_hypotheses": {"source_label": "TEXT"},
            "route_resolutions": {"source_label": "TEXT"},
        }
        for table, columns in additive.items():
            present = {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for column, definition in columns.items():
                if column not in present:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        now = self._now()
        self._conn.execute(
            "INSERT INTO schema_meta(key, value, updated_at) VALUES ('schema_version', '2', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (now,),
        )
        self._conn.execute(
            "INSERT INTO schema_meta(key, value, updated_at) VALUES ('migration_001_cases', 'applied', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (now,),
        )

    def close(self) -> None:
        """Close the SQLite connection; committed data remains durable."""

        if self._conn is not None:
            self._conn.close()
            self._conn = None  # type: ignore[assignment]

    def __enter__(self) -> "CaseRepository":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - best-effort interpreter cleanup
        try:
            self.close()
        except Exception:
            pass

    def _now(self) -> str:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")

    @contextmanager
    def _transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        if self._conn is None:
            raise CaseStoreError("repository is closed")
        try:
            self._conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    @staticmethod
    def _json(value: Any) -> str:
        return canonical_json(value)

    @staticmethod
    def _decode_json(value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except (TypeError, ValueError) as exc:
            raise IntegrityError("invalid JSON persisted in case store") from exc

    @staticmethod
    def _case_from_row(row: sqlite3.Row) -> Case:
        return Case(
            case_id=row["case_id"],
            title=row["title"],
            location=Location(row["city"], row["state"], row["postal_code"]),
            team_alias=row["team_alias"],
            role_alias=row["role_alias"],
            state=CaseState(row["state_name"]),
            version=int(row["version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            closed_at=row["closed_at"],
            last_error=row["last_error"],
            contract_type=row["contract_type"] if "contract_type" in row.keys() else None,
            service_type=row["service_type"] if "service_type" in row.keys() else None,
            target_headcount=row["target_headcount"] if "target_headcount" in row.keys() else None,
            target_start_date=row["target_start_date"] if "target_start_date" in row.keys() else None,
            job_family_requirements=tuple(json.loads(row["job_family_requirements_json"] or "[]")) if "job_family_requirements_json" in row.keys() else (),
        )

    @staticmethod
    def _scan_from_row(row: sqlite3.Row) -> ScanRun:
        return ScanRun(
            scan_id=row["scan_id"],
            case_id=row["case_id"],
            source_kind=row["source_kind"],
            workbook_name=row["workbook_name"],
            workbook_sha256=row["workbook_sha256"],
            status=row["status"],
            prior_state=CaseState(row["prior_state"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error_message=row["error_message"],
            row_count=row["row_count"],
            snapshot_id=row["snapshot_id"],
            idempotency_key=row["idempotency_key"] if "idempotency_key" in row.keys() else None,
            source_label=row["source_label"] if "source_label" in row.keys() else None,
            source_version=row["source_version"] if "source_version" in row.keys() else None,
            assurance=row["assurance"] if "assurance" in row.keys() else None,
            retrieved_at=row["retrieved_at"] if "retrieved_at" in row.keys() else None,
            actor_role=row["actor_role"] if "actor_role" in row.keys() else None,
            source_uri=row["source_uri"] if "source_uri" in row.keys() else None,
            byte_size=row["byte_size"] if "byte_size" in row.keys() else None,
            schema_fingerprint=row["schema_fingerprint"] if "schema_fingerprint" in row.keys() else None,
            payload_retained=bool(row["payload_retained"]) if "payload_retained" in row.keys() else False,
            source_row_count=row["source_row_count"] if "source_row_count" in row.keys() else row["row_count"],
            excluded_row_count=int(row["excluded_row_count"] or 0) if "excluded_row_count" in row.keys() else 0,
        )

    @staticmethod
    def _snapshot_from_row(row: sqlite3.Row) -> SourceSnapshot:
        return SourceSnapshot(
            snapshot_id=row["snapshot_id"],
            scan_id=row["scan_id"],
            case_id=row["case_id"],
            source_kind=row["source_kind"],
            workbook_name=row["workbook_name"],
            workbook_sha256=row["workbook_sha256"],
            source_uri=row["source_uri"],
            observed_at=row["observed_at"],
            row_count=int(row["row_count"]),
            schema_fingerprint=row["schema_fingerprint"],
            source_label=row["source_label"] if "source_label" in row.keys() else None,
            source_version=row["source_version"] if "source_version" in row.keys() else None,
            assurance=row["assurance"] if "assurance" in row.keys() else None,
            retrieved_at=row["retrieved_at"] if "retrieved_at" in row.keys() else None,
            actor_role=row["actor_role"] if "actor_role" in row.keys() else None,
            byte_size=row["byte_size"] if "byte_size" in row.keys() else None,
            payload_retained=bool(row["payload_retained"]) if "payload_retained" in row.keys() else False,
            source_row_count=row["source_row_count"] if "source_row_count" in row.keys() else int(row["row_count"]),
            excluded_row_count=int(row["excluded_row_count"] or 0) if "excluded_row_count" in row.keys() else 0,
        )

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> SourceRecord:
        return SourceRecord(
            resource_id=row["resource_id"],
            case_id=row["case_id"],
            source_kind=row["source_kind"],
            stable_key=row["stable_key"],
            row_hash=row["row_hash"],
            display_name=row["display_name"],
            public_url=row["public_url"],
            payload=json.loads(row["payload_json"] or "{}"),
            current=bool(row["is_current"]),
            review_status=row["review_status"],
            review_note=row["review_note"],
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
        )

    @staticmethod
    def _observation_from_row(row: sqlite3.Row) -> EvidenceObservation:
        return EvidenceObservation(
            observation_id=row["observation_id"],
            snapshot_id=row["snapshot_id"],
            resource_id=row["resource_id"],
            row_hash=row["row_hash"],
            observed_at=row["observed_at"],
            payload=json.loads(row["payload_json"] or "{}"),
            is_current=bool(row["is_current"]),
        )

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> Task:
        return Task(
            task_id=row["task_id"],
            case_id=row["case_id"],
            task_type=row["task_type"],
            severity=row["severity"],
            title=row["title"],
            fingerprint=row["fingerprint"],
            status=row["status"],
            details=json.loads(row["details_json"] or "{}"),
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )

    def _require_case(self, conn: sqlite3.Connection, case_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        if row is None:
            raise CaseNotFoundError(case_id)
        return row

    def _check_version(self, conn: sqlite3.Connection, case_id: str, expected_version: int | None) -> sqlite3.Row:
        row = self._require_case(conn, case_id)
        if expected_version is not None and int(row["version"]) != expected_version:
            raise OptimisticLockError(
                f"stale case {case_id}: expected version {expected_version}, found {row['version']}"
            )
        return row

    def _bump_case(
        self,
        conn: sqlite3.Connection,
        case_id: str,
        *,
        state: CaseState | str | None = None,
        last_error: str | None | object = _MISSING,
        closed_at: str | None | object = _MISSING,
    ) -> Case:
        row = self._require_case(conn, case_id)
        now = self._now()
        target = coerce_case_state(state) if state is not None else CaseState(row["state_name"])
        error = row["last_error"] if last_error is _MISSING else last_error
        closed = row["closed_at"] if closed_at is _MISSING else closed_at
        conn.execute(
            "UPDATE cases SET state_name=?, version=version+1, updated_at=?, last_error=?, closed_at=? WHERE case_id=?",
            (target.value, now, error, closed, case_id),
        )
        return self._case_from_row(self._require_case(conn, case_id))

    def _invalidate_case(self, conn: sqlite3.Connection, case_id: str, event_type: str, detail: Mapping[str, Any] | None = None) -> None:
        """Bump the case version and remove a stale validation state."""

        row = self._require_case(conn, case_id)
        state = CaseState.NEEDS_VERIFICATION if CaseState(row["state_name"]) == CaseState.VALIDATED else CaseState(row["state_name"])
        self._bump_case(conn, case_id, state=state, last_error=None)
        self._event(conn, case_id, event_type, detail)

    def _event(
        self,
        conn: sqlite3.Connection,
        case_id: str,
        event_type: str,
        detail: Mapping[str, Any] | None = None,
        scan_id: str | None = None,
    ) -> None:
        conn.execute(
            "INSERT INTO case_events(event_id, case_id, event_type, scan_id, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (self._new_id("evt"), case_id, event_type, scan_id, self._json(ensure_public_payload(detail)), self._now()),
        )

    # ------------------------------------------------------------------ cases
    def create_case(
        self,
        title: str | CaseCreate | Mapping[str, Any] | None = None,
        city: str | None = None,
        state: str | None = None,
        postal_code: str | None = None,
        *,
        location: Location | None = None,
        zip_code: str | None = None,
        team_alias: str = "bd",
        role_alias: str = "owner",
        team: str | None = None,
        role: str | None = None,
        case_id: str | None = None,
        contract_type: str | None = None,
        service_type: str | None = None,
        target_headcount: int | None = None,
        target_start_date: str | None = None,
        job_family_requirements: Iterable[str] = (),
    ) -> Case:
        """Create a Draft case and return it.

        ``title`` may be a :class:`CaseCreate` or mapping for adapter
        convenience.  No owner/person ID parameter is accepted; team and role
        are validated controlled aliases.
        """

        if isinstance(title, CaseCreate):
            payload = title
            title, city, state, postal_code = payload.title, payload.city, payload.state, payload.postal_code
            team_alias, role_alias, case_id = payload.team_alias, payload.role_alias, payload.case_id
            contract_type, service_type, target_headcount, target_start_date, job_family_requirements = payload.contract_type, payload.service_type, payload.target_headcount, payload.target_start_date, payload.job_family_requirements
        elif isinstance(title, Mapping):
            payload = dict(title)
            title = payload.get("title")
            city = payload.get("city", city)
            state = payload.get("state", state)
            postal_code = payload.get("postal_code", payload.get("zip_code", postal_code))
            location = payload.get("location", location)
            team_alias = payload.get("team_alias", payload.get("team", team_alias))
            role_alias = payload.get("role_alias", payload.get("role", role_alias))
            case_id = payload.get("case_id", case_id)
            contract_type = payload.get("contract_type", contract_type)
            service_type = payload.get("service_type", service_type)
            target_headcount = payload.get("target_headcount", target_headcount)
            target_start_date = payload.get("target_start_date", target_start_date)
            job_family_requirements = payload.get("job_family_requirements", job_family_requirements)
        if team is not None:
            team_alias = team
        if role is not None:
            role_alias = role
        if not isinstance(title, str) or not title.strip():
            raise CaseValidationError("title is required")
        if location is None:
            if city is None or state is None:
                raise LocationValidationError("city and state are required")
            location = normalize_location(city, state, postal_code, zip_code=zip_code)
        elif not isinstance(location, Location):
            raise LocationValidationError("location must be a Location")
        team_alias = normalize_team_alias(team_alias)
        role_alias = normalize_role_alias(role_alias)
        if target_headcount is not None and (isinstance(target_headcount, bool) or not isinstance(target_headcount, int) or target_headcount <= 0):
            raise CaseValidationError("target_headcount must be a positive integer")
        if target_start_date is not None:
            if not isinstance(target_start_date, str) or not target_start_date.strip():
                raise CaseValidationError("target_start_date must be an ISO date")
            try:
                start_date = date.fromisoformat(target_start_date.strip())
            except ValueError as exc:
                raise CaseValidationError("target_start_date must be an ISO date") from exc
            clock_value = self._clock()
            if clock_value.tzinfo is None:
                clock_value = clock_value.replace(tzinfo=timezone.utc)
            if start_date <= clock_value.astimezone(timezone.utc).date():
                raise CaseValidationError("target_start_date must be in the future")
            target_start_date = target_start_date.strip()
        job_families = tuple(str(value).strip() for value in (job_family_requirements or ()) if str(value).strip())
        case_id = case_id or self._new_id("case")
        now = self._now()
        with self._transaction() as conn:
            try:
                conn.execute(
                    "INSERT INTO cases(case_id,title,city,state,postal_code,team_alias,role_alias,state_name,version,created_at,updated_at,contract_type,service_type,target_headcount,target_start_date,job_family_requirements_json) "
                    "VALUES(?,?,?,?,?,?,?,'Draft',1,?,?,?,?,?,?,?)",
                    (case_id, " ".join(title.split()), location.city, location.state, location.postal_code, team_alias, role_alias, now, now, contract_type, service_type, target_headcount, target_start_date, self._json(list(job_families))),
                )
            except sqlite3.IntegrityError as exc:
                raise IntegrityError(f"case already exists: {case_id}") from exc
            self._event(conn, case_id, "case_created", {"team_alias": team_alias, "role_alias": role_alias})
            return self._case_from_row(self._require_case(conn, case_id))

    def get_case(self, case_id: str) -> Case | None:
        """Return the persisted case, or ``None`` when it does not exist.

        This is a pure read: it never mutates case state.  A ``Validated`` case
        whose evidence has since gone stale (for example because its import
        aged past the source freshness budget with no intervening write) is
        reconciled by the explicit :meth:`reconcile_case_validation` /
        :meth:`reconcile_validations` command, not by a getter.
        """

        with self._transaction(immediate=False) as conn:
            row = conn.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
            if row is None:
                return None
            return self._case_from_row(row)

    def require_case(self, case_id: str) -> Case:
        """Return a case or raise :class:`CaseNotFoundError`."""

        case = self.get_case(case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        return case

    def _validation_holds(self, conn: sqlite3.Connection, case_id: str) -> bool:
        """Return whether a case still satisfies every validation gate *now*.

        Pure read: it evaluates the freshness-aware readiness assessment and any
        open blocking tasks against the *current* clock, without mutating
        anything.  The persisting reconcile command and the read-only display
        derivation share this predicate so a case is judged the same way whether
        we are about to write the demotion or merely render it.
        """

        assessment = self._assessment_conn(conn, case_id)
        has_blocking = conn.execute(
            "SELECT 1 FROM tasks WHERE case_id=? AND severity='blocking' AND status='open' LIMIT 1", (case_id,)
        ).fetchone() is not None
        return assessment.ready and not has_blocking

    def _reconcile_validation(self, conn: sqlite3.Connection, case_id: str) -> Case:
        row = self._require_case(conn, case_id)
        case = self._case_from_row(row)
        if case.state != CaseState.VALIDATED:
            return case
        if not self._validation_holds(conn, case_id):
            case = self._bump_case(conn, case_id, state=CaseState.NEEDS_VERIFICATION, last_error=None)
            self._event(conn, case_id, "validation_invalidated", {"reason": "readiness_or_freshness_changed"})
        return case

    def reconcile_case_validation(self, case_id: str) -> Case:
        """Demote a persisted ``Validated`` case whose evidence no longer holds.

        Read methods are side-effect free, so this is the explicit command that
        performs freshness/readiness reconciliation.  Call it from a scheduled
        or startup process, or before acting on a case.  A case that is still
        ready (or not currently ``Validated``) is returned unchanged.
        """

        with self._transaction() as conn:
            return self._reconcile_validation(conn, case_id)

    def reconcile_validations(self) -> list[Case]:
        """Reconcile every persisted ``Validated`` case; return those demoted."""

        with self._transaction(immediate=False) as conn:
            case_ids = [
                r["case_id"]
                for r in conn.execute(
                    "SELECT case_id FROM cases WHERE state_name=?", (CaseState.VALIDATED.value,)
                ).fetchall()
            ]
        demoted: list[Case] = []
        for case_id in case_ids:
            case = self.reconcile_case_validation(case_id)
            if case.state != CaseState.VALIDATED:
                demoted.append(case)
        return demoted

    def displayed_state(self, case: Case | str) -> CaseState:
        """Return the state a case should be *shown* as right now -- a pure read.

        A case persisted as ``Validated`` whose attested evidence has since aged
        past its source-freshness budget (or that has picked up an open blocking
        task) no longer holds its validation, even though the persisted row still
        reads ``Validated`` until the next :meth:`reconcile_case_validation`
        command writes the demotion.  The startup reconcile only persists
        demotions known when the process booted, so a case that ages during
        uptime keeps a stale ``Validated`` row until something writes.

        This derives the live display state from the same freshness view
        :meth:`compute_readiness` uses, so read-only surfaces (the Cases table,
        the case selector) never show a stale case as current ``Validated``.  It
        never mutates: persisting the demotion is still the reconcile command's
        job.
        """

        with self._transaction(immediate=False) as conn:
            if isinstance(case, Case):
                case_id = case.case_id
                persisted = case.state
            else:
                case_id = case
                persisted = CaseState(self._require_case(conn, case_id)["state_name"])
            if persisted == CaseState.VALIDATED and not self._validation_holds(conn, case_id):
                return CaseState.NEEDS_VERIFICATION
            return persisted

    def list_cases(self, *, state: CaseState | str | None = None) -> list[Case]:
        """List cases ordered by most recently updated."""

        with self._transaction(immediate=False) as conn:
            if state is None:
                rows = conn.execute("SELECT * FROM cases ORDER BY updated_at DESC, case_id").fetchall()
            else:
                value = coerce_case_state(state).value
                rows = conn.execute("SELECT * FROM cases WHERE state_name=? ORDER BY updated_at DESC, case_id", (value,)).fetchall()
            return [self._case_from_row(row) for row in rows]

    def update_case(
        self,
        case_id: str,
        expected_version: int | CaseUpdate | None = None,
        *,
        title: str | None = None,
        city: str | None = None,
        state: str | None = None,
        postal_code: str | None = None,
        zip_code: str | None = None,
        location: Location | None = None,
        team_alias: str | None = None,
        role_alias: str | None = None,
        update: CaseUpdate | None = None,
    ) -> Case:
        """Optimistically update public case fields and increment ``version``."""

        if isinstance(expected_version, CaseUpdate):
            update = expected_version
            expected_version = None
        if update is not None:
            title = update.title if update.title is not None else title
            city = update.city if update.city is not None else city
            state = update.state if update.state is not None else state
            postal_code = update.postal_code if update.postal_code is not None else postal_code
            team_alias = update.team_alias if update.team_alias is not None else team_alias
            role_alias = update.role_alias if update.role_alias is not None else role_alias
        with self._transaction() as conn:
            row = self._check_version(conn, case_id, expected_version if isinstance(expected_version, int) else None)
            current_state = CaseState(row["state_name"])
            if current_state in {CaseState.SCANNING, CaseState.CLOSED}:
                raise CaseValidationError(f"cannot update a {current_state.value} case")
            next_title = row["title"] if title is None else title
            if not isinstance(next_title, str) or not next_title.strip():
                raise CaseValidationError("title is required")
            if location is None and any(value is not None for value in (city, state, postal_code, zip_code)):
                next_location = normalize_location(
                    city if city is not None else row["city"],
                    state if state is not None else row["state"],
                    postal_code if postal_code is not None else row["postal_code"],
                    zip_code=zip_code,
                )
            elif location is not None:
                next_location = location
            else:
                next_location = Location(row["city"], row["state"], row["postal_code"])
            next_team = normalize_team_alias(team_alias) if team_alias is not None else row["team_alias"]
            next_role = normalize_role_alias(role_alias) if role_alias is not None else row["role_alias"]
            now = self._now()
            next_state = CaseState.NEEDS_VERIFICATION if current_state == CaseState.VALIDATED else current_state
            changed = conn.execute(
                "UPDATE cases SET title=?,city=?,state=?,postal_code=?,team_alias=?,role_alias=?,state_name=?,version=version+1,updated_at=? "
                "WHERE case_id=? AND version=?",
                (" ".join(next_title.split()), next_location.city, next_location.state, next_location.postal_code, next_team, next_role, next_state.value, now, case_id, row["version"]),
            ).rowcount
            if not changed:
                raise OptimisticLockError(f"stale case {case_id}")
            self._event(conn, case_id, "case_updated")
            return self._case_from_row(self._require_case(conn, case_id))

    def transition_case(
        self,
        case_id: str,
        target: CaseState | str,
        expected_version: int | None = None,
    ) -> Case:
        """Transition a case through the explicit state graph."""

        with self._transaction() as conn:
            row = self._check_version(conn, case_id, expected_version)
            current, destination = ensure_transition(row["state_name"], target)
            if destination == CaseState.SCANNING:
                running = conn.execute("SELECT 1 FROM scan_runs WHERE case_id=? AND status='running'", (case_id,)).fetchone()
                if running:
                    raise ScanInProgressError(case_id)
            closed_at = self._now() if destination == CaseState.CLOSED else None
            result = self._bump_case(conn, case_id, state=destination, closed_at=closed_at)
            self._event(conn, case_id, "case_state_changed", {"from": current.value, "to": destination.value})
            return result

    # ------------------------------------------------------------------- scans
    def start_scan(
        self,
        case_id: str,
        source_kind: str,
        workbook_name: str,
        *,
        workbook_sha256: str | None = None,
        workbook_hash: str | None = None,
        source_uri: str | None = None,
        idempotency_key: str | None = None,
        snapshot: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> ScanRun:
        """Atomically reserve one case/source/workbook scan.

        Starting the same already-succeeded request is idempotent and returns
        the original run.  A failed request can be retried, producing a new
        run.  Concurrent running scans for one case are rejected by both the
        transaction check and SQLite's partial index for one running scan.
        """

        if not isinstance(source_kind, str) or not source_kind.strip():
            raise ScanStateError("source_kind is required")
        if not isinstance(workbook_name, str) or not workbook_name.strip():
            raise ScanStateError("workbook_name is required")
        if workbook_sha256 is not None and workbook_hash is not None and workbook_sha256 != workbook_hash:
            raise ScanStateError("workbook hash aliases disagree")
        wb_hash = workbook_sha256 or workbook_hash or fingerprint({"workbook_name": workbook_name})
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not idempotency_key.strip():
                raise ScanStateError("idempotency key is required when supplied")
            idempotency_key = idempotency_key.strip()
        # Filename is display metadata, never request identity.  This keeps a
        # browser rename from bypassing an idempotent retry.
        request_fp = fingerprint({
            "case_id": case_id,
            "source_kind": source_kind.strip(),
            "workbook_sha256": wb_hash,
            "idempotency_key": idempotency_key,
        })
        with self._transaction() as conn:
            row = self._check_version(conn, case_id, expected_version)
            latest_request = None
            if idempotency_key:
                latest_request = conn.execute(
                    "SELECT * FROM scan_runs WHERE case_id=? AND idempotency_key=? ORDER BY started_at DESC, rowid DESC LIMIT 1",
                    (case_id, idempotency_key),
                ).fetchone()
            if latest_request is None:
                latest_request = conn.execute(
                    "SELECT * FROM scan_runs WHERE case_id=? AND request_fingerprint=? ORDER BY started_at DESC, rowid DESC LIMIT 1",
                    (case_id, request_fp),
                ).fetchone()
            if idempotency_key and latest_request is not None and latest_request["status"] in {ScanStatus.SUCCEEDED, ScanStatus.PARTIAL}:
                if latest_request["source_kind"] != source_kind.strip() or latest_request["workbook_sha256"] != wb_hash:
                    raise IdempotencyConflict("idempotency key is already bound to a different workbook")
            latest_source = conn.execute(
                "SELECT * FROM scan_runs WHERE case_id=? AND source_kind=? ORDER BY started_at DESC, rowid DESC LIMIT 1",
                (case_id, source_kind.strip()),
            ).fetchone()
            # A successful idempotency key is a durable receipt, not a
            # "latest source" pointer.  Later scans must not let an old key
            # replay as a third import and roll the current set backward.  A
            # partial receipt becomes replayable once its explicit partial
            # blocker has been resolved; while open, the same key is a retry
            # opportunity for a corrected import.
            if (
                latest_request
                and latest_request["status"] in {ScanStatus.SUCCEEDED, ScanStatus.PARTIAL}
                and (
                    idempotency_key is not None
                    or (latest_source is not None and latest_source["scan_id"] == latest_request["scan_id"])
                )
                and (
                    latest_request["status"] == ScanStatus.SUCCEEDED
                    or conn.execute(
                        "SELECT 1 FROM tasks WHERE case_id=? AND task_type='SCAN_PARTIAL' AND status='open' AND details_json LIKE ? LIMIT 1",
                        (case_id, f'%"scan_id":"{latest_request["scan_id"]}"%'),
                    ).fetchone() is None
                )
            ):
                return self._scan_from_row(latest_request)
            running = conn.execute("SELECT * FROM scan_runs WHERE case_id=? AND status='running'", (case_id,)).fetchone()
            if running:
                raise ScanInProgressError(f"case {case_id} already has running scan {running['scan_id']}")
            current = CaseState(row["state_name"])
            if current == CaseState.CLOSED:
                raise ScanStateError("closed cases cannot be rescanned")
            scan_id = self._new_id("scan")
            now = self._now()
            source = dict(snapshot or {})
            try:
                conn.execute(
                    "INSERT INTO scan_runs(scan_id,case_id,source_kind,workbook_name,workbook_sha256,request_fingerprint,status,prior_state,started_at,idempotency_key,source_label,source_version,assurance,retrieved_at,actor_role,source_uri,byte_size,schema_fingerprint,payload_retained,source_row_count,excluded_row_count) "
                    "VALUES(?,?,?,?,?,?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0)",
                    (
                        scan_id, case_id, source_kind.strip(), workbook_name.strip(), wb_hash, request_fp,
                        current.value, now, idempotency_key, source.get("source_label"), source.get("source_version"),
                        source.get("assurance"), source.get("retrieved_at"), source.get("actor_role"), source.get("source_uri"),
                        int(source.get("byte_size", 0) or 0), source.get("schema_fingerprint"),
                        int(source.get("source_row_count", 0) or 0),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ScanInProgressError(f"case {case_id} already has a running scan") from exc
            self._bump_case(conn, case_id, state=CaseState.SCANNING, last_error=None)
            self._event(conn, case_id, "scan_started", {"source_kind": source_kind.strip(), "workbook_name": workbook_name.strip(), "source_uri": source_uri, "idempotency_key_present": bool(idempotency_key)}, scan_id)
            return self._scan_from_row(conn.execute("SELECT * FROM scan_runs WHERE scan_id=?", (scan_id,)).fetchone())

    @staticmethod
    def _incoming_row(row: Mapping[str, Any] | SourceRecord) -> _IncomingRow:
        if isinstance(row, SourceRecord):
            payload = ensure_public_payload(row.payload)
            return _IncomingRow(row.stable_key, row_hash=row_hash if (row_hash := row.row_hash) else row_fingerprint(payload), payload=payload, display_name=row.display_name, public_url=row.public_url)
        if not isinstance(row, Mapping):
            raise EvidenceValidationError("scan rows must be mappings or SourceRecord values")
        raw = dict(row)
        explicit_stable = None
        # Source-native IDs are intentionally not an identity boundary in the
        # pilot.  Only the canonical allowlisted row hash determines identity;
        # changed rows therefore remain historical rather than being fuzzy
        # merged through an external identifier.
        for key in ("stable_key", "source_key", "record_key", "external_key"):
            if raw.get(key) not in (None, ""):
                explicit_stable = str(raw[key]).strip()
                break
        explicit_hash = raw.pop("row_hash", None)
        raw.pop("stable_key", None)
        raw.pop("source_key", None)
        raw.pop("record_key", None)
        raw.pop("external_key", None)
        payload = ensure_public_payload(raw)
        computed_hash = row_fingerprint(payload)
        row_hash = str(explicit_hash) if explicit_hash else computed_hash
        stable = explicit_stable or computed_hash
        name = payload.get("display_name", payload.get("name", payload.get("organization_name")))
        public_url = payload.get("public_url", payload.get("url", payload.get("website")))
        return _IncomingRow(stable, row_hash, payload, str(name) if name is not None else None, str(public_url) if public_url is not None else None)

    def _task_upsert(
        self,
        conn: sqlite3.Connection,
        *,
        case_id: str,
        task_type: str,
        severity: TaskSeverity | str,
        title: str,
        details: Mapping[str, Any] | None = None,
        task_fingerprint: str | None = None,
    ) -> Task:
        details_json = ensure_public_payload(details)
        sev = TaskSeverity(severity).value
        fp = task_fingerprint or fingerprint({"task_type": task_type, "severity": sev, "details": details_json})
        now = self._now()
        conn.execute(
            "INSERT OR IGNORE INTO tasks(task_id,case_id,task_type,severity,title,fingerprint,status,details_json,created_at) VALUES(?,?,?,?,?,?,'open',?,?)",
            (self._new_id("task"), case_id, task_type, sev, title, fp, self._json(details_json), now),
        )
        row = conn.execute("SELECT * FROM tasks WHERE case_id=? AND fingerprint=?", (case_id, fp)).fetchone()
        if row is None:
            raise IntegrityError("task upsert failed")
        if row["status"] in {TaskStatus.RESOLVED.value, TaskStatus.DISMISSED.value}:
            conn.execute("UPDATE tasks SET status='open', resolved_at=NULL WHERE task_id=?", (row["task_id"],))
            row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (row["task_id"],)).fetchone()
        return self._task_from_row(row)

    def _resolve_task(self, conn: sqlite3.Connection, case_id: str, task_fingerprint: str) -> None:
        conn.execute(
            "UPDATE tasks SET status='resolved', resolved_at=? WHERE case_id=? AND fingerprint=? AND status='open'",
            (self._now(), case_id, task_fingerprint),
        )

    def _finalize_failure(
        self,
        scan_id: str,
        error_message: str,
        *,
        expected_version: int | None = None,
    ) -> ScanRun:
        with self._transaction() as conn:
            scan_row = conn.execute("SELECT * FROM scan_runs WHERE scan_id=?", (scan_id,)).fetchone()
            if scan_row is None:
                raise CaseNotFoundError(scan_id)
            if scan_row["status"] in {ScanStatus.SUCCEEDED, ScanStatus.PARTIAL}:
                return self._scan_from_row(scan_row)
            if scan_row["status"] == ScanStatus.FAILED:
                return self._scan_from_row(scan_row)
            case_row = self._check_version(conn, scan_row["case_id"], expected_version)
            if CaseState(case_row["state_name"]) != CaseState.SCANNING:
                raise ScanStateError("running scan's case is not Scanning")
            now = self._now()
            conn.execute(
                "UPDATE scan_runs SET status='failed', finished_at=?, error_message=? WHERE scan_id=? AND status='running'",
                (now, str(error_message), scan_id),
            )
            # A failed newer run must never restore a prior Validated state.
            # Historical evidence exists if either a prior snapshot or record
            # is present; that history requires a fresh analyst check.
            has_history = conn.execute(
                "SELECT 1 FROM source_snapshots WHERE case_id=? LIMIT 1",
                (scan_row["case_id"],),
            ).fetchone() is not None
            target = CaseState.NEEDS_VERIFICATION if has_history else CaseState.DRAFT
            self._bump_case(conn, scan_row["case_id"], state=target, last_error=str(error_message))
            self._event(conn, scan_row["case_id"], "scan_failed", {"error": str(error_message)}, scan_id)
            self._task_upsert(
                conn,
                case_id=scan_row["case_id"],
                task_type="SCAN_FAILED",
                severity=TaskSeverity.BLOCKING,
                title="Latest source scan failed; review and retry",
                details={"scan_id": scan_id, "source_kind": scan_row["source_kind"]},
                task_fingerprint=fingerprint({"task_type": "SCAN_FAILED", "scan_id": scan_id}),
            )
            return self._scan_from_row(conn.execute("SELECT * FROM scan_runs WHERE scan_id=?", (scan_id,)).fetchone())

    def finalize_scan(
        self,
        scan_id: str,
        rows: Iterable[Mapping[str, Any] | SourceRecord] | None = None,
        *,
        success: bool = True,
        status: str | None = None,
        error_message: str | None = None,
        error: str | None = None,
        source_uri: str | None = None,
        schema_fingerprint: str | None = None,
        source_row_count: int | None = None,
        excluded_row_count: int = 0,
        unparsed_rows: int = 0,
        rejected_rows: int = 0,
        excluded_records: Iterable[Mapping[str, Any]] = (),
        expected_version: int | None = None,
    ) -> ScanRun:
        """Commit one workbook result and derive case validation state.

        ``rows`` are only public source records.  A failed finalization updates
        run metadata and moves the case to a reviewable state while leaving
        prior source snapshots/records/observations untouched.
        """

        if not success or (status is not None and status.casefold() == ScanStatus.FAILED):
            return self._finalize_failure(scan_id, error_message or error or "scan failed", expected_version=expected_version)
        run_status = (status or ScanStatus.SUCCEEDED).casefold()
        if run_status not in {ScanStatus.SUCCEEDED, ScanStatus.PARTIAL}:
            raise ScanStateError("unknown terminal scan status")
        if excluded_row_count < 0 or unparsed_rows < 0 or rejected_rows < 0:
            raise ScanStateError("scan counts must be non-negative")
        try:
            incoming = [self._incoming_row(row) for row in (rows or ())]
            safe_exclusions = [ensure_public_payload(dict(item)) for item in excluded_records]
            if len(safe_exclusions) != int(excluded_row_count):
                raise EvidenceValidationError("excluded source row metadata does not match the exclusion count")
            stable_seen: set[str] = set()
            for row in incoming:
                if row.stable_key in stable_seen:
                    raise EvidenceValidationError(f"duplicate stable_key in workbook: {row.stable_key}")
                stable_seen.add(row.stable_key)
        except Exception as exc:
            self._finalize_failure(scan_id, str(exc), expected_version=expected_version)
            raise
        with self._transaction() as conn:
            scan_row = conn.execute("SELECT * FROM scan_runs WHERE scan_id=?", (scan_id,)).fetchone()
            if scan_row is None:
                raise CaseNotFoundError(scan_id)
            if scan_row["status"] in {ScanStatus.SUCCEEDED, ScanStatus.PARTIAL}:
                return self._scan_from_row(scan_row)
            if scan_row["status"] == ScanStatus.FAILED:
                raise ScanStateError("cannot finalize a failed scan")
            case_row = self._check_version(conn, scan_row["case_id"], expected_version)
            if CaseState(case_row["state_name"]) != CaseState.SCANNING:
                raise ScanStateError("running scan's case is not Scanning")
            case_id = scan_row["case_id"]
            source_kind = scan_row["source_kind"]
            now = self._now()
            snapshot_id = self._new_id("snapshot")
            # Snapshot stores metadata, not workbook bytes or row content.
            snapshot_row_count = int(source_row_count if source_row_count is not None else len(incoming))
            conn.execute(
                "INSERT INTO source_snapshots(snapshot_id,scan_id,case_id,source_kind,workbook_name,workbook_sha256,source_uri,observed_at,row_count,schema_fingerprint,source_label,source_version,assurance,retrieved_at,actor_role,byte_size,payload_retained,source_row_count,excluded_row_count) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
                (
                    snapshot_id, scan_id, case_id, source_kind, scan_row["workbook_name"], scan_row["workbook_sha256"],
                    source_uri or scan_row["source_uri"], now, len(incoming), schema_fingerprint or scan_row["schema_fingerprint"],
                    scan_row["source_label"], scan_row["source_version"], scan_row["assurance"], scan_row["retrieved_at"],
                    scan_row["actor_role"], scan_row["byte_size"], snapshot_row_count, int(excluded_row_count),
                ),
            )
            for exclusion in safe_exclusions:
                row_hash = str(exclusion.get("row_hash") or "").strip()
                reason = str(exclusion.get("reason") or "").strip()
                if len(row_hash) != 64 or not reason:
                    raise EvidenceValidationError("excluded source rows require a hash and reason")
                conn.execute(
                    "INSERT OR IGNORE INTO source_exclusions(exclusion_id,scan_id,case_id,source_kind,row_hash,source_row,parse_status,parse_note,reason,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        self._new_id("exclusion"), scan_id, case_id, source_kind, row_hash,
                        exclusion.get("source_row"), str(exclusion.get("parse_status") or "UNKNOWN"),
                        exclusion.get("parse_note"), reason,
                        self._json(ensure_public_payload(exclusion.get("payload") or {})), now,
                    ),
                )
            prior_rows = conn.execute(
                "SELECT * FROM source_records WHERE case_id=? AND source_kind=? AND is_current=1",
                (case_id, source_kind),
            ).fetchall()
            prior_by_stable = {row["stable_key"]: row for row in prior_rows}
            # A terminal snapshot defines the current set.  Partial status
            # blocks validation, but absent prior rows are still historical so
            # the UI never presents carried-forward records as current proof.
            if run_status == ScanStatus.SUCCEEDED:
                conn.execute("UPDATE source_records SET is_current=0 WHERE case_id=? AND source_kind=? AND is_current=1", (case_id, source_kind))
                conn.execute(
                    "UPDATE evidence_observations SET is_current=0 WHERE resource_id IN (SELECT resource_id FROM source_records WHERE case_id=? AND source_kind=?)",
                    (case_id, source_kind),
                )
            for item in incoming:
                existing = conn.execute(
                    "SELECT * FROM source_records WHERE case_id=? AND source_kind=? AND stable_key=? AND row_hash=?",
                    (case_id, source_kind, item.stable_key, item.row_hash),
                ).fetchone()
                if existing:
                    resource_id = existing["resource_id"]
                    conn.execute(
                        "UPDATE source_records SET is_current=1,last_seen_at=?,display_name=?,public_url=?,payload_json=? WHERE resource_id=?",
                        (now, item.display_name, item.public_url, self._json(item.payload), resource_id),
                    )
                else:
                    resource_id = "res_" + fingerprint({"case_id": case_id, "source_kind": source_kind, "stable_key": item.stable_key, "row_hash": item.row_hash})
                    conn.execute(
                        "INSERT INTO source_records(resource_id,case_id,source_kind,stable_key,row_hash,display_name,public_url,payload_json,is_current,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,1,?,?)",
                        (resource_id, case_id, source_kind, item.stable_key, item.row_hash, item.display_name, item.public_url, self._json(item.payload), now, now),
                    )
                # New row hash means a new resource.  The previous stable key
                # resource remains historical and is never fuzzy-merged.
                old = prior_by_stable.get(item.stable_key)
                if old and old["row_hash"] != item.row_hash:
                    conn.execute("UPDATE source_records SET is_current=0 WHERE resource_id=?", (old["resource_id"],))
                    changed_fp = fingerprint({"case_id": case_id, "source_kind": source_kind, "stable_key": item.stable_key, "old_hash": old["row_hash"], "new_hash": item.row_hash})
                    self._task_upsert(conn, case_id=case_id, task_type="SOURCE_RECORD_CHANGED", severity=TaskSeverity.ADVISORY, title="Source record changed", details={"source_kind": source_kind, "stable_key": item.stable_key}, task_fingerprint=changed_fp)
                # Immutable observations preserve every version, while only
                # the latest observation for this resource is current.
                conn.execute("UPDATE evidence_observations SET is_current=0 WHERE resource_id=?", (resource_id,))
                observation_id = "obs_" + fingerprint({"snapshot_id": snapshot_id, "resource_id": resource_id})
                conn.execute(
                    "INSERT OR IGNORE INTO evidence_observations(observation_id,snapshot_id,resource_id,row_hash,observed_at,payload_json,is_current) VALUES(?,?,?,?,?,?,1)",
                    (observation_id, snapshot_id, resource_id, item.row_hash, now, self._json(item.payload)),
                )
                missing_fp = fingerprint({"task_type": "SOURCE_RECORD_DISAPPEARED", "source_kind": source_kind, "stable_key": item.stable_key})
                self._resolve_task(conn, case_id, missing_fp)
            # Records missing from any terminal snapshot become historical and
            # get a blocking reconciliation task; partial status prevents
            # validation but does not carry stale rows forward as current.
            if run_status in {ScanStatus.SUCCEEDED, ScanStatus.PARTIAL}:
                for stable_key, old in prior_by_stable.items():
                    if stable_key in stable_seen:
                        continue
                    conn.execute("UPDATE source_records SET is_current=0 WHERE resource_id=?", (old["resource_id"],))
                    conn.execute("UPDATE evidence_observations SET is_current=0 WHERE resource_id=?", (old["resource_id"],))
                    task_fp = fingerprint({"task_type": "SOURCE_RECORD_DISAPPEARED", "source_kind": source_kind, "stable_key": stable_key})
                    self._task_upsert(conn, case_id=case_id, task_type="SOURCE_RECORD_DISAPPEARED", severity=TaskSeverity.BLOCKING, title="Source record disappeared; reconcile source", details={"source_kind": source_kind, "stable_key": stable_key, "prior_resource_id": old["resource_id"]}, task_fingerprint=task_fp)
            if not incoming and run_status == ScanStatus.SUCCEEDED:
                empty_fp = fingerprint({"task_type": "SOURCE_EMPTY", "source_kind": source_kind})
                self._task_upsert(conn, case_id=case_id, task_type="SOURCE_EMPTY", severity=TaskSeverity.BLOCKING, title="Source returned no records; verify source coverage", details={"source_kind": source_kind}, task_fingerprint=empty_fp)
            # A later successful import is the explicit acknowledgement that
            # a prior failed run has been superseded.  Resolve only failures
            # for this source kind; failures for another source remain open.
            failed_tasks = conn.execute(
                "SELECT task_id, details_json FROM tasks WHERE case_id=? AND task_type='SCAN_FAILED' AND status='open'",
                (case_id,),
            ).fetchall()
            for task in failed_tasks:
                detail = self._decode_json(task["details_json"], {})
                if detail.get("source_kind") == source_kind:
                    conn.execute("UPDATE tasks SET status='resolved', resolved_at=? WHERE task_id=?", (now, task["task_id"]))
            conn.execute(
                "UPDATE scan_runs SET status=?,finished_at=?,row_count=?,snapshot_id=?,schema_fingerprint=?,source_row_count=?,excluded_row_count=? WHERE scan_id=? AND status='running'",
                (run_status, now, len(incoming), snapshot_id, schema_fingerprint or scan_row["schema_fingerprint"], snapshot_row_count, int(excluded_row_count), scan_id),
            )
            if run_status == ScanStatus.PARTIAL:
                self._task_upsert(
                    conn,
                    case_id=case_id,
                    task_type="SCAN_PARTIAL",
                    severity=TaskSeverity.BLOCKING,
                    title="Partial import requires anomaly review",
                    details={"scan_id": scan_id, "source_kind": source_kind, "unparsed_rows": int(unparsed_rows), "rejected_rows": int(rejected_rows), "excluded_row_count": int(excluded_row_count)},
                    task_fingerprint=fingerprint({"task_type": "SCAN_PARTIAL", "scan_id": scan_id}),
                )
            if excluded_row_count:
                mismatch_severity = TaskSeverity.BLOCKING if not incoming else TaskSeverity.ADVISORY
                self._task_upsert(
                    conn,
                    case_id=case_id,
                    task_type="SOURCE_LOCATION_MISMATCH",
                    severity=mismatch_severity,
                    title="Source rows were excluded because they do not match the case location",
                    details={"scan_id": scan_id, "source_kind": source_kind, "excluded_row_count": int(excluded_row_count), "retained_row_count": len(incoming)},
                    task_fingerprint=fingerprint({"task_type": "SOURCE_LOCATION_MISMATCH", "scan_id": scan_id}),
                )
            assessment = self._assessment_conn(conn, case_id)
            open_blocking = conn.execute("SELECT 1 FROM tasks WHERE case_id=? AND severity='blocking' AND status='open' LIMIT 1", (case_id,)).fetchone() is not None
            # A scan produces evidence; it does not itself constitute an
            # analyst validation decision.  Even a clean import therefore
            # returns the case to Needs Verification.  validate_case is the
            # only API allowed to enter Validated.
            target = CaseState.NEEDS_VERIFICATION
            self._bump_case(conn, case_id, state=target, last_error=None)
            self._event(
                conn,
                case_id,
                    "scan_partial" if run_status == ScanStatus.PARTIAL else "scan_succeeded",
                {
                    "source_kind": source_kind,
                    "row_count": len(incoming),
                    "readiness_state": target.value,
                    "open_blocking_tasks": open_blocking,
                    "blocking_items": list(assessment.blocking_keys),
                },
                scan_id,
            )
            return self._scan_from_row(conn.execute("SELECT * FROM scan_runs WHERE scan_id=?", (scan_id,)).fetchone())

    def list_exclusions(self, case_id: str, *, scan_id: str | None = None) -> list[dict[str, Any]]:
        """Return bounded quarantine metadata for rows excluded from a case."""

        with self._transaction(immediate=False) as conn:
            self._require_case(conn, case_id)
            if scan_id:
                rows = conn.execute(
                    "SELECT * FROM source_exclusions WHERE case_id=? AND scan_id=? ORDER BY created_at, exclusion_id",
                    (case_id, scan_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM source_exclusions WHERE case_id=? ORDER BY created_at DESC, exclusion_id",
                    (case_id,),
                ).fetchall()
            return [
                {
                    "exclusion_id": row["exclusion_id"],
                    "scan_id": row["scan_id"],
                    "case_id": row["case_id"],
                    "source_kind": row["source_kind"],
                    "row_hash": row["row_hash"],
                    "source_row": row["source_row"],
                    "parse_status": row["parse_status"],
                    "parse_note": row["parse_note"],
                    "reason": row["reason"],
                    "payload": self._decode_json(row["payload_json"], {}),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

    # Obvious aliases for scanner/UI adapters.
    complete_scan = finalize_scan
    finish_scan = finalize_scan

    def record_scan_result(
        self,
        scan_id: str,
        rows: Iterable[Mapping[str, Any] | SourceRecord] | None = None,
        **kwargs: Any,
    ) -> ScanRun:
        """Alias for :meth:`finalize_scan` used by scanner orchestration."""

        return self.finalize_scan(scan_id, rows, **kwargs)

    def scan(
        self,
        case_id: str,
        source_kind: str,
        workbook_name: str,
        rows: Iterable[Mapping[str, Any] | SourceRecord],
        **kwargs: Any,
    ) -> ScanRun:
        """Run a complete start/finalize cycle for synchronous adapters."""

        run = self.start_scan(case_id, source_kind, workbook_name, **{key: value for key, value in kwargs.items() if key in {"workbook_sha256", "workbook_hash", "source_uri", "expected_version"}})
        return self.finalize_scan(run.scan_id, rows, source_uri=kwargs.get("source_uri"), schema_fingerprint=kwargs.get("schema_fingerprint"))

    def fail_scan(self, scan_id: str, error_message: str, *, expected_version: int | None = None) -> ScanRun:
        """Mark a run failed and move the case back to a reviewable state."""

        return self._finalize_failure(scan_id, error_message, expected_version=expected_version)

    def recover_interrupted_scans(self, error_message: str = "scan interrupted before finalization") -> list[ScanRun]:
        """Recover running scans after a process restart without changing evidence."""

        with self._transaction() as conn:
            running = conn.execute("SELECT scan_id FROM scan_runs WHERE status='running' ORDER BY started_at").fetchall()
            result: list[ScanRun] = []
            for item in running:
                scan = conn.execute("SELECT * FROM scan_runs WHERE scan_id=?", (item["scan_id"],)).fetchone()
                case = self._require_case(conn, scan["case_id"])
                try:
                    started = datetime.fromisoformat(scan["started_at"].replace("Z", "+00:00"))
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    now_value = self._clock()
                    if now_value.tzinfo is None:
                        now_value = now_value.replace(tzinfo=timezone.utc)
                    if now_value.astimezone(timezone.utc) - started.astimezone(timezone.utc) < timedelta(minutes=15):
                        continue
                except (TypeError, ValueError):
                    # Malformed timestamps are safer to recover than to leave
                    # a permanently blocking Running row.
                    pass
                now = self._now()
                conn.execute("UPDATE scan_runs SET status='failed',finished_at=?,error_message=? WHERE scan_id=?", (now, error_message, scan["scan_id"]))
                history = conn.execute("SELECT 1 FROM source_snapshots WHERE case_id=? LIMIT 1", (scan["case_id"],)).fetchone() is not None
                target = CaseState.NEEDS_VERIFICATION if history else CaseState.DRAFT
                self._bump_case(conn, scan["case_id"], state=target, last_error=error_message)
                self._event(conn, scan["case_id"], "scan_recovered_as_failed", {"error": error_message}, scan["scan_id"])
                self._task_upsert(
                    conn,
                    case_id=scan["case_id"],
                    task_type="SCAN_FAILED",
                    severity=TaskSeverity.BLOCKING,
                    title="Latest source scan failed; review and retry",
                    details={"scan_id": scan["scan_id"], "source_kind": scan["source_kind"]},
                    task_fingerprint=fingerprint({"task_type": "SCAN_FAILED", "scan_id": scan["scan_id"]}),
                )
                result.append(self._scan_from_row(conn.execute("SELECT * FROM scan_runs WHERE scan_id=?", (scan["scan_id"],)).fetchone()))
            return result

    def get_scan(self, scan_id: str) -> ScanRun | None:
        """Return a scan run or ``None``."""

        with self._transaction(immediate=False) as conn:
            row = conn.execute("SELECT * FROM scan_runs WHERE scan_id=?", (scan_id,)).fetchone()
            return self._scan_from_row(row) if row else None

    def list_scans(self, case_id: str, *, status: str | None = None) -> list[ScanRun]:
        """List runs for a case, newest first."""

        with self._transaction(immediate=False) as conn:
            if status is None:
                rows = conn.execute("SELECT * FROM scan_runs WHERE case_id=? ORDER BY started_at DESC", (case_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM scan_runs WHERE case_id=? AND status=? ORDER BY started_at DESC", (case_id, status)).fetchall()
            return [self._scan_from_row(row) for row in rows]

    # -------------------------------------------------------------- resources
    def list_snapshots(self, case_id: str, *, source_kind: str | None = None) -> list[SourceSnapshot]:
        """List source metadata snapshots; workbook contents are never returned."""

        with self._transaction(immediate=False) as conn:
            if source_kind is None:
                rows = conn.execute("SELECT * FROM source_snapshots WHERE case_id=? ORDER BY observed_at DESC", (case_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM source_snapshots WHERE case_id=? AND source_kind=? ORDER BY observed_at DESC", (case_id, source_kind)).fetchall()
            return [self._snapshot_from_row(row) for row in rows]

    def list_resources(
        self,
        case_id: str,
        *,
        source_kind: str | None = None,
        current_only: bool = False,
    ) -> list[SourceRecord]:
        """List public source records, optionally limited to current rows."""

        with self._transaction(immediate=False) as conn:
            clauses = ["case_id=?"]
            params: list[Any] = [case_id]
            if source_kind is not None:
                clauses.append("source_kind=?")
                params.append(source_kind)
            if current_only:
                clauses.append("is_current=1")
            rows = conn.execute(f"SELECT * FROM source_records WHERE {' AND '.join(clauses)} ORDER BY source_kind,stable_key,row_hash", params).fetchall()
            return [self._record_from_row(row) for row in rows]

    def get_resource(self, resource_id: str) -> SourceRecord | None:
        """Return one public source record."""

        with self._transaction(immediate=False) as conn:
            row = conn.execute("SELECT * FROM source_records WHERE resource_id=?", (resource_id,)).fetchone()
            return self._record_from_row(row) if row else None

    def list_observations(
        self,
        resource_id: str | None = None,
        *,
        case_id: str | None = None,
        current_only: bool = False,
    ) -> list[EvidenceObservation]:
        """List immutable observation history for one resource or case."""

        with self._transaction(immediate=False) as conn:
            clauses: list[str] = []
            params: list[Any] = []
            if resource_id is not None:
                clauses.append("o.resource_id=?")
                params.append(resource_id)
            if case_id is not None:
                clauses.append("s.case_id=?")
                params.append(case_id)
            if current_only:
                clauses.append("o.is_current=1")
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(f"SELECT o.* FROM evidence_observations o JOIN source_snapshots s ON s.snapshot_id=o.snapshot_id{where} ORDER BY o.observed_at DESC,o.observation_id", params).fetchall()
            return [self._observation_from_row(row) for row in rows]

    def update_resource_review(
        self,
        resource_id: str,
        review_status: str,
        *,
        review_note: str | None = None,
    ) -> SourceRecord:
        """Record a human review state without editing evidence payload."""

        if review_status not in {"unreviewed", "verified", "rejected"}:
            raise EvidenceValidationError("review_status must be unreviewed, verified, or rejected")
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM source_records WHERE resource_id=?", (resource_id,)).fetchone()
            if row is None:
                raise CaseNotFoundError(resource_id)
            now = self._now()
            conn.execute("UPDATE source_records SET review_status=?,review_note=?,last_seen_at=? WHERE resource_id=?", (review_status, review_note, now, resource_id))
            self._invalidate_case(conn, row["case_id"], "resource_review_updated", {"resource_id": resource_id, "review_status": review_status})
            return self._record_from_row(conn.execute("SELECT * FROM source_records WHERE resource_id=?", (resource_id,)).fetchone())

    # --------------------------------------------------------- readiness/tasks
    def _assessment_conn(self, conn: sqlite3.Connection, case_id: str) -> ReadinessAssessment:
        case_row = self._require_case(conn, case_id)
        scan_rows = conn.execute(
            "SELECT * FROM scan_runs WHERE case_id=? ORDER BY started_at DESC, rowid DESC", (case_id,)
        ).fetchall()
        latest_by_kind: dict[str, sqlite3.Row] = {}
        for scan in scan_rows:
            latest_by_kind.setdefault(scan["source_kind"], scan)

        def usable(scan: sqlite3.Row | None) -> bool:
            if scan is None or scan["status"] == ScanStatus.RUNNING or scan["status"] == ScanStatus.FAILED:
                return False
            if scan["status"] == ScanStatus.PARTIAL:
                return conn.execute(
                    "SELECT 1 FROM tasks WHERE case_id=? AND task_type='SCAN_PARTIAL' AND status='open' AND details_json LIKE ? LIMIT 1",
                    (case_id, f'%"scan_id":"{scan["scan_id"]}"%'),
                ).fetchone() is None
            return True

        def source_fresh(scan: sqlite3.Row | None) -> bool:
            # Freshness is measured from the analyst-attested *source retrieval
            # time*, never the system import time, and against a per-source
            # budget rather than a single global window.  A missing retrieval
            # time is never fresh: an old workbook uploaded today must not look
            # current just because its import just finished.
            if scan is None:
                return False
            retrieved = scan["retrieved_at"] if "retrieved_at" in scan.keys() else None
            if not retrieved:
                return False
            try:
                retrieved_at = datetime.fromisoformat(str(retrieved).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                return False
            if retrieved_at.tzinfo is None:
                retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
            now_value = self._clock()
            if now_value.tzinfo is None:
                now_value = now_value.replace(tzinfo=timezone.utc)
            age = now_value.astimezone(timezone.utc) - retrieved_at.astimezone(timezone.utc)
            policy = freshness_policy_for(scan["source_kind"])
            return timedelta(0) <= age <= policy.max_age

        def fresh_terminal(scan: sqlite3.Row | None) -> bool:
            return usable(scan) and source_fresh(scan)

        latest = scan_rows[0] if scan_rows else None
        latest_usable = usable(latest)
        fresh_import = bool(latest_usable and source_fresh(latest))
        latest_retrieved_at = latest["retrieved_at"] if (latest_usable and "retrieved_at" in latest.keys()) else None
        latest_policy = freshness_policy_for(latest["source_kind"]) if latest is not None else _DEFAULT_FRESHNESS_POLICY

        # A review assertion is only current when its own source kind has a
        # fresh terminal run; a new unrelated source import cannot refresh it.
        latest_ids = {kind: row["scan_id"] for kind, row in latest_by_kind.items() if fresh_terminal(row)}
        current_rows = conn.execute(
            "SELECT sr.source_kind, sr.payload_json, ss.scan_id FROM source_records sr "
            "JOIN evidence_observations eo ON eo.resource_id=sr.resource_id AND eo.is_current=1 "
            "JOIN source_snapshots ss ON ss.snapshot_id=eo.snapshot_id "
            "WHERE sr.case_id=? AND sr.is_current=1 AND sr.review_status='verified'",
            (case_id,),
        ).fetchall()
        geographic_verified = False
        service_verified = False
        wanted_city = str(case_row["city"]).casefold()
        wanted_state = str(case_row["state"]).upper()
        for current in current_rows:
            # Bind review assertions to the latest usable terminal source for
            # that source kind; stale rows cannot validate a fresh case.
            latest_for_kind = latest_ids.get(current["source_kind"])
            if not latest_for_kind or current["scan_id"] != latest_for_kind:
                continue
            payload = self._decode_json(current["payload_json"], {})
            observed_city = str(payload.get("parsed_city") or payload.get("city") or "").casefold()
            observed_state = str(payload.get("parsed_state") or payload.get("state") or "").upper()
            if observed_city == wanted_city and observed_state == wanted_state:
                if current["source_kind"] in {"NIB_NPA", "SOURCEAMERICA_NPA"}:
                    geographic_verified = True
                elif (
                    current["source_kind"] == "ABILITYONE_SERVICES"
                    and str(payload.get("location_parse_status")) == "PARSED"
                    and bool(payload.get("service_type"))
                ):
                    service_verified = True

        resolved_route = conn.execute(
            "SELECT 1 FROM route_resolutions rr JOIN route_hypotheses rh ON rh.hypothesis_id=rr.hypothesis_id "
            "WHERE rr.case_id=? AND rr.decision='resolved' "
            "AND rh.route_kind IN ('ABILITYONE_CONFIRMED','OTHER_FEDERAL_CONFIRMED') "
            "AND TRIM(rr.rationale)<>'' AND COALESCE(TRIM(rr.source_label),'')<>'' LIMIT 1",
            (case_id,),
        ).fetchone() is not None

        # Core gates are immutable requirements.  Analyst-supplied readiness
        # rows are additive and cannot replace these checks.
        core = {
            "case_location": ReadinessItem("case_location", "Case location is structurally valid", ReadinessState.VERIFIED, True),
            "current_import": ReadinessItem(
                "current_import",
                "The latest public import is terminal and fresh for its source",
                ReadinessState.VERIFIED if fresh_import else ReadinessState.NEEDS_VERIFICATION if latest else ReadinessState.MISSING,
                True,
                note=(
                    f"Source retrieved {latest_retrieved_at}; within the {latest_policy.max_age_days}-day budget (policy effective {latest_policy.effective_date})"
                    if fresh_import
                    else (
                        f"Latest import has no attested retrieval within its {latest_policy.max_age_days}-day source budget "
                        f"(policy effective {latest_policy.effective_date}); it is failed, partial, running, older than the budget, "
                        "or its retrieval time is unknown"
                    )
                    if latest
                    else "Import an approved workbook"
                ),
            ),
            "route_resolution": ReadinessItem(
                "route_resolution", "Acquisition route is explicitly confirmed by an analyst", ReadinessState.VERIFIED if resolved_route else ReadinessState.NEEDS_VERIFICATION, True
            ),
            "geographic_relevance": ReadinessItem(
                "geographic_relevance", "A current public resource is separately verified for the case location", ReadinessState.VERIFIED if geographic_verified else ReadinessState.NEEDS_VERIFICATION, True
            ),
            "service_relevance": ReadinessItem(
                "service_relevance", "A current AbilityOne service row is separately verified for the case location", ReadinessState.VERIFIED if service_verified else ReadinessState.NEEDS_VERIFICATION, True
            ),
        }
        custom = conn.execute("SELECT * FROM readiness_items WHERE case_id=? ORDER BY item_key", (case_id,)).fetchall()
        for row in custom:
            if row["item_key"] in core:
                continue
            core[row["item_key"]] = ReadinessItem(
                key=row["item_key"], label=row["label"], state=row["state"], blocking=bool(row["is_blocking"]),
                evidence_ids=tuple(self._decode_json(row["evidence_ids_json"], [])), note=row["note"],
            )
        return assess_readiness(tuple(core.values()))

    def compute_readiness(self, case_id: str) -> ReadinessAssessment:
        """Compute the deterministic readiness matrix for a case."""

        with self._transaction(immediate=False) as conn:
            self._require_case(conn, case_id)
            assessment = self._assessment_conn(conn, case_id)
            open_tasks = conn.execute(
                "SELECT task_type, title, fingerprint, details_json FROM tasks WHERE case_id=? AND severity='blocking' AND status='open' ORDER BY fingerprint",
                (case_id,),
            ).fetchall()
            if not open_tasks:
                return assessment
            task_items = tuple(
                ReadinessItem(
                    key=f"task:{row['fingerprint']}",
                    label=row["title"],
                    state=ReadinessState.NEEDS_VERIFICATION,
                    blocking=True,
                    note=row["task_type"],
                )
                for row in open_tasks
            )
            return assess_readiness((*assessment.items, *task_items))

    readiness_assessment = compute_readiness

    def upsert_readiness_item(
        self,
        case_id: str,
        key: str | ReadinessItem,
        label: str | None = None,
        state: ReadinessState | str | None = None,
        *,
        blocking: bool = True,
        evidence_ids: Iterable[str] = (),
        note: str | None = None,
    ) -> ReadinessItem:
        """Insert/update one readiness requirement (an explicit truth-table input)."""

        if isinstance(key, ReadinessItem):
            item = key
        else:
            if label is None or state is None:
                raise EvidenceValidationError("readiness label and state are required")
            item = ReadinessItem(key, label, state, blocking, tuple(evidence_ids), note)
        with self._transaction() as conn:
            self._require_case(conn, case_id)
            conn.execute(
                "INSERT INTO readiness_items(item_id,case_id,item_key,label,state,is_blocking,evidence_ids_json,note,updated_at) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(case_id,item_key) DO UPDATE SET label=excluded.label,state=excluded.state,is_blocking=excluded.is_blocking,evidence_ids_json=excluded.evidence_ids_json,note=excluded.note,updated_at=excluded.updated_at",
                (self._new_id("ready"), case_id, item.key, item.label, item.state.value, int(item.blocking), self._json(list(item.evidence_ids)), item.note, self._now()),
            )
            self._invalidate_case(conn, case_id, "readiness_item_updated", {"key": item.key, "state": item.state.value})
            row = conn.execute("SELECT * FROM readiness_items WHERE case_id=? AND item_key=?", (case_id, item.key)).fetchone()
            return ReadinessItem(row["item_key"], row["label"], row["state"], bool(row["is_blocking"]), tuple(self._decode_json(row["evidence_ids_json"], [])), row["note"])

    set_readiness_item = upsert_readiness_item

    def list_tasks(
        self,
        case_id: str,
        *,
        status: TaskStatus | str | None = None,
        severity: TaskSeverity | str | None = None,
        open_only: bool = False,
    ) -> list[Task]:
        """List blocking/advisory tasks for a case."""

        with self._transaction(immediate=False) as conn:
            clauses = ["case_id=?"]
            params: list[Any] = [case_id]
            if status is not None:
                clauses.append("status=?")
                params.append(TaskStatus(status).value)
            if severity is not None:
                clauses.append("severity=?")
                params.append(TaskSeverity(severity).value)
            if open_only:
                clauses.append("status='open'")
            rows = conn.execute(f"SELECT * FROM tasks WHERE {' AND '.join(clauses)} ORDER BY severity DESC,created_at", params).fetchall()
            return [self._task_from_row(row) for row in rows]

    def create_task(
        self,
        case_id: str,
        task_type: str,
        severity: TaskSeverity | str,
        title: str,
        *,
        details: Mapping[str, Any] | None = None,
        task_fingerprint: str | None = None,
        fingerprint_value: str | None = None,
    ) -> Task:
        """Create an idempotent task keyed by a deterministic fingerprint."""

        fp = task_fingerprint or fingerprint_value
        with self._transaction() as conn:
            self._require_case(conn, case_id)
            task = self._task_upsert(conn, case_id=case_id, task_type=task_type, severity=severity, title=title, details=details, task_fingerprint=fp)
            self._invalidate_case(conn, case_id, "task_created", {"task_type": task_type, "task_id": task.task_id})
            return task

    def resolve_task(self, task_id: str, *, reason: str | None = None) -> Task:
        """Resolve an open task with an auditable operator reason."""

        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise CaseNotFoundError(task_id)
            if row["task_type"] == "SCAN_FAILED":
                raise CaseStoreError("system scan failures resolve only after a later successful or acknowledged partial scan")
            if row["status"] == TaskStatus.OPEN.value:
                if not isinstance(reason, str) or not reason.strip():
                    raise EvidenceValidationError("a task resolution reason is required")
                details = self._decode_json(row["details_json"], {})
                details["resolution_reason"] = " ".join(reason.split())
                conn.execute("UPDATE tasks SET details_json=? WHERE task_id=?", (self._json(details), task_id))
                conn.execute("UPDATE tasks SET status='resolved',resolved_at=? WHERE task_id=?", (self._now(), task_id))
                self._invalidate_case(conn, row["case_id"], "task_resolved", {"task_type": row["task_type"], "task_id": task_id, "reason": details["resolution_reason"]})
            return self._task_from_row(conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone())

    def validate_case(self, case_id: str, *, expected_version: int | None = None) -> Case:
        """Set Validated when no blocking evidence/task gaps remain."""

        with self._transaction() as conn:
            row = self._check_version(conn, case_id, expected_version)
            if CaseState(row["state_name"]) == CaseState.CLOSED:
                raise CaseValidationError("closed case cannot be validated")
            assessment = self._assessment_conn(conn, case_id)
            has_blocking = conn.execute("SELECT 1 FROM tasks WHERE case_id=? AND severity='blocking' AND status='open' LIMIT 1", (case_id,)).fetchone() is not None
            # Validation is deliberately explicit: an empty matrix is not a
            # pass, and every blocking item/task must be resolved first.
            target = CaseState.NEEDS_VERIFICATION if not assessment.items or assessment.blocking or has_blocking else CaseState.VALIDATED
            result = self._bump_case(conn, case_id, state=target, last_error=None)
            if target == CaseState.VALIDATED:
                current_hashes = [row["row_hash"] for row in conn.execute("SELECT row_hash FROM source_records WHERE case_id=? AND is_current=1 ORDER BY row_hash", (case_id,)).fetchall()]
                task_fingerprints = [row["fingerprint"] for row in conn.execute("SELECT fingerprint FROM tasks WHERE case_id=? AND severity='blocking' AND status='open' ORDER BY fingerprint", (case_id,)).fetchall()]
                latest_runs = [
                    {"scan_id": item["scan_id"], "source_kind": item["source_kind"], "status": item["status"], "finished_at": item["finished_at"]}
                    for item in conn.execute("SELECT scan_id,source_kind,status,finished_at FROM scan_runs WHERE case_id=? ORDER BY started_at DESC", (case_id,)).fetchall()
                ]
                reviews = [
                    {"resource_id": item["resource_id"], "row_hash": item["row_hash"], "review_status": item["review_status"], "review_note": item["review_note"]}
                    for item in conn.execute("SELECT resource_id,row_hash,review_status,review_note FROM source_records WHERE case_id=? AND is_current=1 ORDER BY resource_id", (case_id,)).fetchall()
                ]
                routes = [
                    {"hypothesis_id": item["hypothesis_id"], "route_kind": item["route_kind"], "status": item["status"]}
                    for item in conn.execute("SELECT hypothesis_id,route_kind,status FROM route_hypotheses WHERE case_id=? ORDER BY hypothesis_id", (case_id,)).fetchall()
                ]
                validation_value = fingerprint({"case_id": case_id, "case_version": result.version, "current_row_hashes": current_hashes, "open_blocking_tasks": task_fingerprints, "readiness": [item.key for item in assessment.items], "latest_runs": latest_runs, "reviews": reviews, "routes": routes})
                conn.execute(
                    "INSERT OR IGNORE INTO fingerprints(fingerprint,entity_type,entity_id,created_at) VALUES(?,?,?,?)",
                    (validation_value, "case_validation", f"{case_id}:{result.version}", self._now()),
                )
                self._event(conn, case_id, "case_validated", {"blocking_tasks": has_blocking, "blocking_items": list(assessment.blocking_keys), "validation_fingerprint": validation_value})
            else:
                self._event(conn, case_id, "case_needs_verification", {"blocking_tasks": has_blocking, "blocking_items": list(assessment.blocking_keys)})
            return result

    def close_case(self, case_id: str, *, reason: str, expected_version: int | None = None) -> Case:
        """Close a validated case with an explicit, auditable reason.

        Closure is terminal and only reachable from ``Validated`` (enforced by
        the transition graph).  The transition graph alone is not enough: a case
        can be *persisted* ``Validated`` yet no longer hold that validation
        because its attested evidence aged past its freshness budget during
        uptime with no intervening write.  So this command first reconciles the
        specific case (``reconcile_case_validation``) before the transition
        check -- close is already a write, so reconciling here is a command
        action, not write-on-read.  A stale case is demoted to
        ``Needs Verification`` (persisted) and the transition graph then refuses
        to close it; only a case that still holds its validation closes.  The
        historical trail therefore never shows a case closed while its evidence
        gates were open.  The close reason and the validation fingerprint in
        force at close time are recorded on the ``case_closed`` event for audit.
        """

        if not isinstance(reason, str) or not reason.strip():
            raise CaseValidationError("a close reason is required")
        close_reason = " ".join(reason.split())
        # Reconcile this specific case (its own command transaction, so the
        # demotion persists) before the close transaction reads the state for
        # the transition check.  A stale-but-persisted-Validated case becomes
        # Needs Verification here, which ensure_transition then refuses to close.
        self.reconcile_case_validation(case_id)
        with self._transaction() as conn:
            row = self._check_version(conn, case_id, expected_version)
            current, destination = ensure_transition(row["state_name"], CaseState.CLOSED)
            validation_row = conn.execute(
                "SELECT fingerprint FROM fingerprints WHERE entity_type='case_validation' AND entity_id=?",
                (f"{case_id}:{row['version']}",),
            ).fetchone()
            result = self._bump_case(conn, case_id, state=destination, closed_at=self._now())
            self._event(
                conn,
                case_id,
                "case_closed",
                {
                    "from": current.value,
                    "reason": close_reason,
                    "validation_fingerprint": validation_row["fingerprint"] if validation_row else None,
                },
            )
            return result

    # -------------------------------------------------------------- routes/log
    def add_route_hypothesis(
        self,
        case_id: str,
        route_kind: str | RouteHypothesis,
        target: str | None = None,
        *,
        rationale: str = "",
        confidence: float | None = None,
        evidence_ids: Iterable[str] = (),
        source_label: str | None = None,
        hypothesis_id: str | None = None,
    ) -> RouteHypothesis:
        """Persist a public route hypothesis awaiting human resolution."""

        if isinstance(route_kind, RouteHypothesis):
            item = route_kind
            case_id = item.case_id
        else:
            if target is None:
                raise EvidenceValidationError("route target is required")
            item = RouteHypothesis(hypothesis_id or self._new_id("route"), case_id, route_kind, target, rationale, confidence, RouteStatus.HYPOTHESIS, tuple(evidence_ids), source_label.strip() if source_label else None)
        now = self._now()
        with self._transaction() as conn:
            self._require_case(conn, case_id)
            conn.execute(
                "INSERT INTO route_hypotheses(hypothesis_id,case_id,route_kind,target,rationale,confidence,status,evidence_ids_json,source_label,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (item.hypothesis_id, case_id, item.route_kind, item.target, item.rationale, item.confidence, item.status.value, self._json(list(item.evidence_ids)), item.source_label, now, now),
            )
            self._invalidate_case(conn, case_id, "route_hypothesis_added", {"hypothesis_id": item.hypothesis_id})
            return item

    def list_route_hypotheses(self, case_id: str) -> list[RouteHypothesis]:
        """List route hypotheses for a case."""

        with self._transaction(immediate=False) as conn:
            rows = conn.execute("SELECT * FROM route_hypotheses WHERE case_id=? ORDER BY created_at", (case_id,)).fetchall()
            return [RouteHypothesis(row["hypothesis_id"], row["case_id"], row["route_kind"], row["target"], row["rationale"], row["confidence"], row["status"], tuple(self._decode_json(row["evidence_ids_json"], [])), row["source_label"] if "source_label" in row.keys() else None) for row in rows]

    def resolve_route(
        self,
        hypothesis_id: str,
        decision: str,
        *,
        rationale: str = "",
        source_label: str | None = None,
        resolution_id: str | None = None,
    ) -> RouteResolution:
        """Resolve or reject a route hypothesis with an append-only resolution."""

        if decision not in {"resolved", "rejected"}:
            raise EvidenceValidationError("route decision must be resolved or rejected")
        now = self._now()
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM route_hypotheses WHERE hypothesis_id=?", (hypothesis_id,)).fetchone()
            if row is None:
                raise CaseNotFoundError(hypothesis_id)
            if decision == "resolved":
                if row["route_kind"] not in {"ABILITYONE_CONFIRMED", "OTHER_FEDERAL_CONFIRMED"}:
                    raise EvidenceValidationError("only a confirmed controlled route may be resolved")
                if not rationale.strip():
                    raise EvidenceValidationError("a route resolution rationale is required")
                source_label = (source_label or row["source_label"] or "").strip()
                if not source_label:
                    raise EvidenceValidationError("a public route source label is required")
            rid = resolution_id or self._new_id("resolution")
            conn.execute("UPDATE route_hypotheses SET status=?,updated_at=? WHERE hypothesis_id=?", (decision, now, hypothesis_id))
            conn.execute("INSERT INTO route_resolutions(resolution_id,hypothesis_id,case_id,decision,rationale,source_label,resolved_at) VALUES(?,?,?,?,?,?,?)", (rid, hypothesis_id, row["case_id"], decision, rationale, source_label, now))
            self._invalidate_case(conn, row["case_id"], "route_resolved", {"hypothesis_id": hypothesis_id, "decision": decision})
            return RouteResolution(rid, hypothesis_id, row["case_id"], decision, rationale, now, source_label)

    def list_events(self, case_id: str) -> list[CaseEvent]:
        """Return append-only audit events newest first."""

        with self._transaction(immediate=False) as conn:
            rows = conn.execute("SELECT * FROM case_events WHERE case_id=? ORDER BY created_at DESC,event_id DESC", (case_id,)).fetchall()
            return [CaseEvent(row["event_id"], row["case_id"], row["event_type"], row["scan_id"], json.loads(row["detail_json"] or "{}"), row["created_at"]) for row in rows]

    def put_fingerprint(self, entity_type: str, entity_id: str, value: Any | None = None) -> str:
        """Persist/return an entity fingerprint, idempotently."""

        fp = fingerprint(value if value is not None else {"entity_type": entity_type, "entity_id": entity_id})
        with self._transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO fingerprints(fingerprint,entity_type,entity_id,created_at) VALUES(?,?,?,?)", (fp, entity_type, entity_id, self._now()))
            return fp

    fingerprint = put_fingerprint


# Name used in the approved design and by scanner/UI integrations.
CaseStore = CaseRepository


__all__ = [
    "CaseEvent",
    "CaseNotFoundError",
    "CaseRepository",
    "CaseStore",
    "CaseStoreError",
    "CaseEvent",
    "IntegrityError",
    "OptimisticLockError",
    "ScanInProgressError",
    "ScanRun",
    "ScanStateError",
    "ScanStatus",
]
