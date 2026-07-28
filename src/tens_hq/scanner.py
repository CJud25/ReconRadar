"""Orchestration for one-shot AbilityOne workbook scans.

``run_scan`` is intentionally a small application service: validate the
source boundary, open exactly one connector, persist normalized records, and
reconcile disappearance only after a successful parse.  Repository calls are
kept behind the concrete case-store contract, so a parser failure cannot
mutate prior evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Callable, Mapping, Sequence

from .connectors import (
    CaseRepositoryProtocol,
    ConnectorError,
    ConnectorResult,
    NormalizedRecord,
    SourceKind,
    SourceMetadata,
    coerce_source_kind,
    connector_for,
    expected_headers,
    normalize_zip,
    service_location_matches,
)
from .connectors.base import utc_now


class ScanRunStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"


@dataclass(frozen=True)
class ScanResult:
    case_id: str
    run_id: str | None
    source_kind: SourceKind
    status: ScanRunStatus
    retrieved_at: datetime | None
    source_label: str | None = None
    record_count: int = 0
    duplicate_rows: int = 0
    unparsed_rows: int = 0
    rejected_rows: int = 0
    excluded_row_count: int = 0
    added_count: int = 0
    changed_count: int = 0
    unchanged_count: int = 0
    disappeared_count: int = 0
    error_code: str | None = None
    message: str | None = None
    idempotency_key: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {ScanRunStatus.SUCCEEDED, ScanRunStatus.PARTIAL, ScanRunStatus.IDEMPOTENT_REPLAY}

    @property
    def partial(self) -> bool:
        return self.status is ScanRunStatus.PARTIAL

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["source_kind"] = self.source_kind.value
        result["status"] = self.status.value
        result["retrieved_at"] = self.retrieved_at.isoformat() if self.retrieved_at else None
        return result


class ScanFailure(ConnectorError):
    """Safe scanner failure with the same public error contract as connectors."""


class MemoryIdempotencyStore:
    """Small process-local idempotency store for the demo and offline tests."""

    def __init__(self) -> None:
        self._values: dict[str, ScanResult] = {}

    def get(self, key: str) -> ScanResult | None:
        return self._values.get(key)

    def put(self, key: str, value: ScanResult) -> None:
        self._values[key] = value


def _safe_case_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 160 or any(ord(ch) < 32 for ch in text):
        raise ScanFailure("INVALID_INPUT")
    return text


def _safe_idempotency_key(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or len(text) > 256 or any(ord(ch) < 32 for ch in text):
        raise ScanFailure("IDEMPOTENCY")
    return text


_ACTOR_ROLES = {
    "analyst": "Analyst",
    "reviewer": "Reviewer",
    "operator": "Operator",
    "approver": "Approver",
    "compliance reviewer": "Compliance Reviewer",
}


def _safe_actor_role(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text not in _ACTOR_ROLES:
        raise ScanFailure("INVALID_INPUT")
    return _ACTOR_ROLES[text]


def _retrieved_at(value: Any, clock: Callable[[], datetime]) -> datetime | None:
    # The retrieval date is an analyst-attested source fact, not the system
    # import time.  Preserve an unknown value as NULL in the ledger.
    if value is None:
        return None
    elif isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            raise ScanFailure("INVALID_INPUT") from None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    normalized = result.astimezone(timezone.utc)
    now = clock()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if normalized > now.astimezone(timezone.utc) + timedelta(minutes=5):
        raise ScanFailure("INVALID_INPUT")
    return normalized


def _cached_run_id(value: Mapping[str, Any]) -> str | None:
    for key in ("run_id", "id", "scan_id"):
        if value.get(key):
            return str(value[key])
    return None


class WorkbookScanner:
    """Run strict one-workbook scans against an injected repository."""

    def __init__(
        self,
        repository: CaseRepositoryProtocol,
        *,
        clock: Callable[[], datetime] = utc_now,
        idempotency: Any | None = None,
        connector_factory: Callable[..., Any] = connector_for,
    ) -> None:
        self.repository = repository
        self.clock = clock
        self.idempotency = idempotency or MemoryIdempotencyStore()
        self.connector_factory = connector_factory
        self._pending_records: dict[str, tuple[NormalizedRecord, ...]] = {}

    def run_scan(
        self,
        case_id: str,
        source_kind: SourceKind | str,
        workbook_bytes: bytes | bytearray | memoryview,
        filename: str | None = None,
        retrieved_at: datetime | str | None = None,
        idempotency_key: str | None = None,
        actor_role: str = "Analyst",
        expected_version: int | None = None,
    ) -> ScanResult:
        """Scan one approved workbook and reconcile its current row set.

        The input is accepted only as bytes-like data.  Strings, paths, URLs,
        file handles, and arbitrary iterables are rejected; this guarantees a
        run cannot silently fetch or read an unapproved source.
        """

        safe_case = _safe_case_id(case_id)
        try:
            kind = coerce_source_kind(source_kind)
        except ValueError:
            raise ScanFailure("UNSUPPORTED_SOURCE_KIND") from None
        if not isinstance(workbook_bytes, (bytes, bytearray, memoryview)):
            raise ScanFailure("INVALID_INPUT")
        # The digest is provenance metadata, not source content.  It is
        # calculated before parsing and never retained alongside the bytes.
        workbook_sha256 = sha256(bytes(workbook_bytes)).hexdigest()
        parser_version = "abilityone-xlsx-v1"
        schema_fingerprint = sha256(
            (parser_version + "|" + kind.value + "|" + "|".join(expected_headers(kind))).encode("utf-8")
        ).hexdigest()
        key = _safe_idempotency_key(idempotency_key)
        when = _retrieved_at(retrieved_at, self.clock)
        source_label = None
        if filename is not None:
            # SourceMetadata applies bounded basename sanitization.
            source_label = SourceMetadata(kind, source_label=filename).source_label
        safe_actor_role = _safe_actor_role(actor_role)
        metadata = SourceMetadata(
            kind,
            source_label=source_label,
            source_version=parser_version,
            asserted_by=safe_actor_role,
        )
        snapshot = {
            "source_kind": kind.value,
            "source_uri": "https://plims.abilityone.gov/reports/",
            "assurance": metadata.provenance_assurance,
            "source_label": source_label,
            "source_version": metadata.source_version,
            "retrieved_at": when.isoformat() if when else None,
            "actor_role": safe_actor_role,
            "workbook_sha256": workbook_sha256,
            "byte_size": len(workbook_bytes),
            "schema_fingerprint": schema_fingerprint,
            "payload_retained": False,
        }

        cache_key = f"{safe_case}:{key}" if key else None
        if cache_key:
            try:
                cached = self.idempotency.get(cache_key)
            except Exception:
                raise ScanFailure("IDEMPOTENCY") from None
            if cached is not None:
                if isinstance(cached, ScanResult):
                    cached_hash = str(cached.metadata.get("workbook_sha256") or "")
                    if cached_hash and cached_hash != workbook_sha256:
                        return ScanResult(
                            case_id=safe_case,
                            run_id=cached.run_id,
                            source_kind=kind,
                            status=ScanRunStatus.FAILED,
                            retrieved_at=when,
                            error_code="IDEMPOTENCY",
                            message=ConnectorError._MESSAGES["IDEMPOTENCY"],
                            idempotency_key=key,
                            metadata=snapshot,
                        )
                    return ScanResult(
                        **{
                            **asdict(cached),
                            "status": ScanRunStatus.IDEMPOTENT_REPLAY,
                        }
                    )
                # A repository may return a serialized result from a durable
                # key store; reject malformed cache values safely.
                if isinstance(cached, Mapping):
                    try:
                        cached_hash = str(dict(cached.get("metadata", {})).get("workbook_sha256") or cached.get("workbook_sha256") or "")
                        if cached_hash and cached_hash != workbook_sha256:
                            return ScanResult(
                                case_id=safe_case,
                                run_id=_cached_run_id(cached),
                                source_kind=kind,
                                status=ScanRunStatus.FAILED,
                                retrieved_at=when,
                                error_code="IDEMPOTENCY",
                                message=ConnectorError._MESSAGES["IDEMPOTENCY"],
                                idempotency_key=key,
                                metadata=snapshot,
                            )
                        return ScanResult(
                            case_id=str(cached.get("case_id", safe_case)),
                            run_id=_cached_run_id(cached),
                            source_kind=coerce_source_kind(cached.get("source_kind", kind)),
                            status=ScanRunStatus.IDEMPOTENT_REPLAY,
                            retrieved_at=_retrieved_at(cached.get("retrieved_at"), self.clock),
                            source_label=cached.get("source_label"),
                            record_count=int(cached.get("record_count", 0)),
                            metadata=dict(cached.get("metadata", {})),
                            idempotency_key=key,
                        )
                    except (TypeError, ValueError):
                        raise ScanFailure("IDEMPOTENCY") from None
                raise ScanFailure("IDEMPOTENCY")

        run_id: str | None = None
        try:
            run = self._start_scan(safe_case, kind, key, snapshot, workbook_sha256, expected_version)
            run_id = run.scan_id
            existing_status = run.status.casefold()
            if existing_status in {"succeeded", "partial"}:
                # The durable repository recognized an idempotent terminal
                # request.  Do not parse or write a second snapshot.
                persisted_retrieved = _retrieved_at(run.retrieved_at, self.clock)
                persisted_source_label = run.source_label
                persisted_key = run.idempotency_key or key
                persisted_hash = run.workbook_sha256 or workbook_sha256
                persisted_uri = run.source_uri or snapshot.get("source_uri")
                persisted_schema = run.schema_fingerprint or schema_fingerprint
                return ScanResult(
                    case_id=safe_case,
                    run_id=run_id,
                    source_kind=kind,
                    status=ScanRunStatus.IDEMPOTENT_REPLAY,
                    retrieved_at=persisted_retrieved,
                    source_label=persisted_source_label,
                    record_count=int(run.row_count or 0),
                    idempotency_key=persisted_key,
                    excluded_row_count=int(run.excluded_row_count or 0),
                    metadata={
                        "source_kind": kind.value,
                        "source_uri": persisted_uri,
                        "source_label": persisted_source_label,
                        "source_version": run.source_version,
                        "assurance": run.assurance,
                        "retrieved_at": persisted_retrieved.isoformat() if persisted_retrieved else None,
                        "actor_role": run.actor_role,
                        "workbook_sha256": persisted_hash,
                        "byte_size": run.byte_size,
                        "schema_fingerprint": persisted_schema,
                        "payload_retained": False,
                        "source_row_count": run.source_row_count if run.source_row_count is not None else run.row_count,
                        "excluded_row_count": int(run.excluded_row_count or 0),
                        "scan_status": existing_status,
                    },
                )
            # Parse before any record persistence.  A failed parse gets a
            # failed run event but leaves the prior source snapshot untouched.
            connector = self.connector_factory(kind)
            result: ConnectorResult = connector.parse(workbook_bytes, metadata=metadata)
            # Do not retain caller-owned bytes beyond parsing.
            workbook_bytes = b""
            # The case store keeps this handoff in memory and performs
            # persistence/reconciliation atomically in _finalize.
            scoped_records, excluded_records = self._scope_records(safe_case, kind, result.records)
            excluded_row_count = len(excluded_records)
            self._persist_records(run_id, scoped_records)
            counts = self._reconcile(run_id, kind, scoped_records)
            # A clean parse that omits a previously current row is not a
            # clean reconciliation: it requires the same blocking review as
            # other partial/anomalous imports.
            status = ScanRunStatus.PARTIAL if result.partial or counts.get("disappeared_count", 0) else ScanRunStatus.SUCCEEDED
            details = {
                "source_kind": kind.value,
                "record_count": len(scoped_records),
                "source_row_count": result.scanned_rows,
                "excluded_row_count": excluded_row_count,
                "duplicate_rows": result.duplicate_rows,
                "unparsed_rows": result.unparsed_rows,
                "rejected_rows": int(getattr(result, "rejected_count", 0) or 0),
                "error_code": None,
                "message": None,
                "schema_fingerprint": schema_fingerprint,
                "source_snapshot": snapshot,
                "excluded_records": excluded_records,
                **counts,
            }
            self._finalize(run_id, status.value, details)
            output = ScanResult(
                case_id=safe_case,
                run_id=run_id,
                source_kind=kind,
                status=status,
                retrieved_at=when,
                source_label=source_label,
                record_count=len(scoped_records),
                duplicate_rows=result.duplicate_rows,
                unparsed_rows=result.unparsed_rows,
                rejected_rows=int(getattr(result, "rejected_count", 0) or 0),
                excluded_row_count=excluded_row_count,
                idempotency_key=key,
                # Excluded payloads are written to the durable quarantine
                # table, not returned in the public result.  A national
                # workbook may contain thousands of out-of-scope rows.
                metadata={**snapshot, "source_row_count": result.scanned_rows, "excluded_row_count": excluded_row_count, **counts},
                **counts,
            )
            if cache_key and status is ScanRunStatus.SUCCEEDED:
                try:
                    self.idempotency.put(cache_key, output)
                except Exception:
                    # Idempotency persistence is a convenience boundary; a
                    # successful source commit must not be relabeled failed
                    # because a cache backend is temporarily unavailable.
                    pass
            return output
        except ConnectorError as exc:
            if run_id:
                self._finalize(
                    run_id,
                    ScanRunStatus.FAILED.value,
                    {
                        "source_kind": kind.value,
                        "record_count": 0,
                        "error_code": exc.code,
                        "message": exc.public_message,
                    },
                )
            output = ScanResult(
                case_id=safe_case,
                run_id=run_id,
                source_kind=kind,
                status=ScanRunStatus.FAILED,
                retrieved_at=when,
                source_label=source_label,
                error_code=exc.code,
                message=exc.public_message,
                idempotency_key=key,
                metadata=snapshot,
            )
            return output
        except Exception:
            # Repository and connector implementation details are not safe to
            # expose.  Preserve a fixed event and result for the operator.
            if run_id:
                self._finalize(
                    run_id,
                    ScanRunStatus.FAILED.value,
                    {
                        "source_kind": kind.value,
                        "record_count": 0,
                        "error_code": "REPOSITORY",
                        "message": ConnectorError._MESSAGES["REPOSITORY"],
                    },
                )
            return ScanResult(
                case_id=safe_case,
                run_id=run_id,
                source_kind=kind,
                status=ScanRunStatus.FAILED,
                retrieved_at=when,
                source_label=source_label,
                error_code="REPOSITORY",
                message=ConnectorError._MESSAGES["REPOSITORY"],
                idempotency_key=key,
                metadata=snapshot,
            )

    @staticmethod
    def _native_rows(records: Sequence[NormalizedRecord]) -> tuple[dict[str, Any], ...]:
        """Map normalized rows to the case_store public payload contract.

        There are intentionally no source IDs.  The canonical row hash acts as
        the stable key; a changed row therefore creates a new historical
        resource and an identical row is idempotently observed again.
        """

        return tuple(
            {
                **dict(record.values),
                "row_hash": record.row_hash,
                "stable_key": record.row_hash,
                "parse_status": record.parse_status,
                "parse_note": record.parse_note,
            }
            for record in records
        )

    def _scope_records(
        self,
        case_id: str,
        kind: SourceKind,
        records: Sequence[NormalizedRecord],
    ) -> tuple[tuple[NormalizedRecord, ...], tuple[dict[str, Any], ...]]:
        """Keep only exact public rows relevant to the case location.

        The official exports are national directories.  Persisting every row
        against one city case would turn directory presence into misleading
        local evidence, so scope is exact city/state and optional ZIP matching
        with no proximity or substring inference.  Repositories without the
        case-location API retain the protocol's full normalized set.
        """

        get_case = getattr(self.repository, "get_case", None)
        if get_case is None:
            return tuple(records), ()
        try:
            case = get_case(case_id)
        except Exception:
            raise ScanFailure("REPOSITORY") from None
        if case is None:
            raise ScanFailure("REPOSITORY")
        city = str(getattr(case, "city", "")).strip()
        state = str(getattr(case, "state_code", "")).strip()
        wanted_zip = normalize_zip(getattr(case, "postal_code", None)) if getattr(case, "postal_code", None) else None
        kept: list[NormalizedRecord] = []
        excluded: list[dict[str, Any]] = []
        for record in records:
            if kind is SourceKind.ABILITYONE_SERVICES:
                # Services exports are city/state scoped; ZIP is not a
                # required discriminator because many official rows omit it.
                matches = service_location_matches(record, city=city, state=state, zip_code=None)
                if not matches and record.parse_status != "PARSED":
                    # A state-identifiable but city-unparsed service row is a
                    # broad candidate, not local evidence.  Retain it in the
                    # case so a reviewer can resolve the ambiguity; the
                    # readiness gate only accepts PARSED city/state rows.
                    matches = str(record.values.get("parsed_state") or "").upper() == state.upper()
            else:
                values = record.values
                actual_city = str(values.get("city") or "").strip().casefold()
                actual_state = str(values.get("state") or "").strip().upper()
                actual_zip = normalize_zip(values.get("zip_code"))
                matches = actual_city == city.casefold() and actual_state == state.upper()
                if matches and wanted_zip:
                    matches = bool(actual_zip) and (actual_zip == wanted_zip or actual_zip[:5] == wanted_zip[:5])
            if matches:
                kept.append(record)
            else:
                excluded.append(
                    {
                        "row_hash": record.row_hash,
                        "source_row": record.source_row,
                        "parse_status": record.parse_status,
                        "parse_note": record.parse_note,
                        "reason": "SOURCE_ROW_UNPARSED" if record.parse_status != "PARSED" else "SOURCE_LOCATION_MISMATCH",
                        "payload": dict(record.values),
                    }
                )
        return tuple(kept), tuple(excluded)

    def _start_scan(
        self,
        case_id: str,
        kind: SourceKind,
        key: str | None,
        snapshot: Mapping[str, Any],
        workbook_sha256: str,
        expected_version: int | None,
    ) -> Any:
        # The case store reserves a run by workbook metadata and performs
        # persistence/reconciliation atomically in finalize_scan.
        workbook_name = str(snapshot.get("source_label") or "uploaded_workbook.xlsx")
        try:
            return self.repository.start_scan(
                case_id,
                kind.value,
                workbook_name,
                workbook_sha256=workbook_sha256,
                source_uri=snapshot.get("source_uri"),
                idempotency_key=key,
                snapshot=dict(snapshot),
                expected_version=expected_version,
            )
        except Exception as exc:
            if getattr(exc, "code", None) == "IDEMPOTENCY":
                raise ScanFailure("IDEMPOTENCY") from None
            raise

    def _persist_records(self, run_id: str, records: Sequence[NormalizedRecord]) -> None:
        # Keep the parser handoff short-lived in memory for the atomic
        # finalize_scan transaction.  A crash leaves only the durable running
        # marker for startup recovery.
        self._pending_records[run_id] = tuple(records)

    def _reconcile(self, run_id: str, kind: SourceKind, records: Sequence[NormalizedRecord]) -> dict[str, int]:
        # The repository reconciles inside finalize_scan.  Expose non-mutating
        # counters here so the scanner result remains useful without
        # duplicating that transaction.
        try:
            scan = self.repository.get_scan(run_id)
            if scan is None:
                raise ScanFailure("REPOSITORY")
            prior = self.repository.list_resources(scan.case_id, source_kind=kind.value, current_only=True)
            prior_hashes = {str(item.row_hash) for item in prior}
            observed = {str(record.row_hash) for record in records}
            return {
                "added_count": len(observed - prior_hashes),
                "changed_count": 0,
                "unchanged_count": len(observed & prior_hashes),
                "disappeared_count": len(prior_hashes - observed),
            }
        except ScanFailure:
            raise
        except Exception:
            raise ScanFailure("REPOSITORY") from None

    def _finalize(self, run_id: str, status: str, details: Mapping[str, Any]) -> Any:
        pending = self._pending_records.pop(run_id, ())
        rows = self._native_rows(pending)
        if status == ScanRunStatus.FAILED.value:
            return self.repository.fail_scan(run_id, details.get("message") or "scan failed")

        return self.repository.finalize_scan(
            run_id,
            rows,
            success=True,
            status=status.casefold(),
            schema_fingerprint=details.get("schema_fingerprint"),
            source_row_count=int(details.get("source_row_count", details.get("record_count", len(rows)))),
            excluded_row_count=int(details.get("excluded_row_count", 0)),
            unparsed_rows=int(details.get("unparsed_rows", 0)),
            rejected_rows=int(details.get("rejected_rows", 0)),
            excluded_records=tuple(details.get("excluded_records") or ()),
        )


def run_scan(
    repository: CaseRepositoryProtocol,
    case_id: str,
    source_kind: SourceKind | str,
    workbook_bytes: bytes | bytearray | memoryview,
    filename: str | None = None,
    *,
    retrieved_at: datetime | str | None = None,
    idempotency_key: str | None = None,
    actor_role: str = "Analyst",
    clock: Callable[[], datetime] = utc_now,
    idempotency: Any | None = None,
    expected_version: int | None = None,
) -> ScanResult:
    return WorkbookScanner(repository, clock=clock, idempotency=idempotency).run_scan(
        case_id,
        source_kind,
        workbook_bytes,
        filename,
        retrieved_at,
        idempotency_key,
        actor_role,
        expected_version,
    )

__all__ = [
    "MemoryIdempotencyStore",
    "ScanFailure",
    "ScanResult",
    "ScanRunStatus",
    "WorkbookScanner",
    "run_scan",
]
