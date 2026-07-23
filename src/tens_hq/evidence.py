"""Public evidence records and deterministic assessment helpers.

This module contains no connector code.  A connector/scanner turns a public
workbook into these value objects; :mod:`tens_hq.case_store` persists them with
history.  Snapshots retain metadata only (name/hash/count/schema), while
individual public source records and observations retain the evidence fields
needed to explain a readiness result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Any, Iterable, Mapping


class EvidenceValidationError(ValueError):
    """Raised when evidence contains unsupported or malformed data."""


class TaskSeverity(str, Enum):
    """Whether an unresolved task blocks validation."""

    BLOCKING = "blocking"
    ADVISORY = "advisory"


class TaskStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ReadinessState(str, Enum):
    """Truth-table states for one readiness requirement."""

    VERIFIED = "verified"
    NEEDS_VERIFICATION = "needs_verification"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


class RouteStatus(str, Enum):
    HYPOTHESIS = "hypothesis"
    RESOLVED = "resolved"
    REJECTED = "rejected"


# The two-app wall is drawn at the *right* key.  Person-level identifiers and
# sensitive narrative/document fields would turn this public organization
# tracker into a person/employee system, so they are always rejected at any
# nesting depth.  A named individual's *personal* contact details are person
# PII too (``contact_name``/``contact_email``/``contact_phone``/
# ``personal_email``/``home_address``).  Attachments can carry any of the above.
_PERSON_PII_KEYS = {
    # Direct person identifiers.
    "person_id",
    "user_id",
    "employee_id",
    "applicant_id",
    "candidate_id",
    "contact_id",
    # Organization/source native identifiers are not evidence and are not an
    # identity boundary in this pilot; keep rejecting them rather than persist
    # an external key as if it were a fact.
    "organization_id",
    "external_id",
    "source_id",
    # Sensitive person data (medical / disability / eligibility).
    "ssn",
    "social_security_number",
    "medical_record",
    "medical_record_number",
    "diagnosis",
    "disability_narrative",
    "accommodation",
    "eligibility_document",
    "doctor_note",
    "iep",
    "504",
    "disability",
    "medical",
    "psychological",
    # A named individual's personal contact details (NOT an org's public line).
    "personal_email",
    "contact_name",
    "contact_email",
    "contact_phone",
    "home_address",
    # Bare, unprefixed contact channels are rejected too.  The wall is a
    # person-PII denylist over a default-allow surface, so a generic ``email``/
    # ``phone``/``address`` key that a connector fills with a named individual's
    # personal contact would otherwise pass silently.  An organization's public
    # contact line is attached instead through the explicit ``org_``-prefixed
    # keys below (``org_phone``/``org_email``/``org_address`` …); only the web
    # address keys (``url``/``website``/``public_url``) stay allowed bare,
    # because an org web address is not personal PII.
    "phone",
    "mobile",
    "telephone",
    "email",
    "address",
    "street_address",
    # Attached documents can carry any of the above.
    "document",
    "attachment",
    "file_path",
}

# A *public organization's* contact fields are explicitly allowed, but only
# through keys that cannot be mistaken for a named individual's personal
# contact.  A resource-directory row (Independent Living Center, CARF provider,
# American Job Center) carries its public phone/email/mailing address on
# ``org_``-prefixed keys, and its public web address on bare ``url``/``website``/
# ``public_url`` (a web address is not personal PII).  The bare contact channels
# (``phone``/``email``/``address`` …) are deliberately NOT here: they are person
# PII (see ``_PERSON_PII_KEYS``) because a connector could fill them with an
# individual's personal contact.  Any key that is not person PII is allowed;
# this set documents the intended-public keys and lets the wall's two halves be
# asserted disjoint.
_PUBLIC_ORG_CONTACT_KEYS = {
    "url",
    "website",
    "public_url",
    "org_url",
    "org_website",
    "org_public_url",
    "org_phone",
    "org_email",
    "org_address",
}

# The two halves of the wall must never overlap: a key cannot be both rejected
# person PII and an allowed public-org contact field.
assert _PERSON_PII_KEYS.isdisjoint(_PUBLIC_ORG_CONTACT_KEYS)

# Backwards-compatible alias for the rejection set.
_PRIVATE_KEYS = _PERSON_PII_KEYS


def _public_key(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceValidationError("evidence field names must be non-empty strings")
    return value.strip()


def ensure_public_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy a JSON-like public payload and reject person/sensitive keys.

    The wall is a person-PII denylist (``_PERSON_PII_KEYS``) over a
    default-allow surface: known person-level keys are rejected and any other
    public organization field passes.  A public organization's contact line is
    attached through explicit ``org_*`` keys (``org_phone``/``org_email``/
    ``org_address`` …) or, for a web address, bare ``url``/``website``/
    ``public_url`` (``_PUBLIC_ORG_CONTACT_KEYS``); the bare contact channels
    (``phone``/``email``/``address`` …) are rejected because a connector must
    not attach a named individual's personal contact to a generic key.  The
    check is recursive so a forbidden field cannot be hidden in a nested
    connector response.  Values are copied through JSON round-tripping; this
    prevents mutable caller-owned objects from changing an audit record after it
    is written.
    """

    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise EvidenceValidationError("public payload must be a mapping")

    def walk(value: Any) -> Any:
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for raw_key, raw_value in value.items():
                key = _public_key(raw_key)
                if key.lower().replace("-", "_").replace(" ", "_") in _PERSON_PII_KEYS:
                    raise EvidenceValidationError(f"private field is not allowed: {key}")
                result[key] = walk(raw_value)
            return result
        if isinstance(value, (list, tuple)):
            return [walk(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise EvidenceValidationError(f"unsupported payload value: {type(value).__name__}")

    result = walk(payload)
    # Validate serializability and normalize any mapping subclasses.
    try:
        return json.loads(json.dumps(result, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise EvidenceValidationError("public payload must be JSON serializable") from exc


def canonical_json(value: Any) -> str:
    """Serialize a JSON-compatible value deterministically."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(value: Any) -> str:
    """Return a stable SHA-256 fingerprint for a JSON-compatible value."""

    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def row_fingerprint(row: Mapping[str, Any]) -> str:
    """Hash a public row after validation."""

    return fingerprint(ensure_public_payload(row))


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """Metadata about one workbook observation; no workbook contents."""

    snapshot_id: str
    scan_id: str
    case_id: str
    source_kind: str
    workbook_name: str
    workbook_sha256: str
    observed_at: str
    row_count: int
    schema_fingerprint: str | None = None
    source_uri: str | None = None
    source_label: str | None = None
    source_version: str | None = None
    assurance: str | None = None
    retrieved_at: str | None = None
    actor_role: str | None = None
    byte_size: int | None = None
    payload_retained: bool = False
    source_row_count: int | None = None
    excluded_row_count: int = 0

    def __post_init__(self) -> None:
        if not self.snapshot_id or not self.scan_id or not self.case_id:
            raise EvidenceValidationError("snapshot, scan, and case IDs are required")
        if not self.source_kind.strip() or not self.workbook_name.strip():
            raise EvidenceValidationError("source_kind and workbook_name are required")
        if not isinstance(self.row_count, int) or self.row_count < 0:
            raise EvidenceValidationError("row_count must be non-negative")
        if self.byte_size is not None and (not isinstance(self.byte_size, int) or self.byte_size < 0):
            raise EvidenceValidationError("byte_size must be non-negative")
        if self.source_row_count is not None and (not isinstance(self.source_row_count, int) or self.source_row_count < 0):
            raise EvidenceValidationError("source_row_count must be non-negative")
        if not isinstance(self.excluded_row_count, int) or self.excluded_row_count < 0:
            raise EvidenceValidationError("excluded_row_count must be non-negative")
        if self.payload_retained:
            raise EvidenceValidationError("raw workbook payloads are never retained")

    @property
    def workbook_hash(self) -> str:
        """Alias for ``workbook_sha256``."""

        return self.workbook_sha256


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """A current or historical public resource discovered in a snapshot."""

    resource_id: str
    case_id: str
    source_kind: str
    stable_key: str
    row_hash: str
    display_name: str | None = None
    public_url: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    current: bool = True
    review_status: str = "unreviewed"
    review_note: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None

    def __post_init__(self) -> None:
        if not self.resource_id or not self.case_id or not self.source_kind:
            raise EvidenceValidationError("resource, case, source kind are required")
        if not self.stable_key:
            raise EvidenceValidationError("stable_key is required")
        if not self.row_hash:
            raise EvidenceValidationError("row_hash is required")
        if self.review_status not in {"unreviewed", "verified", "rejected"}:
            raise EvidenceValidationError("unknown review status")
        object.__setattr__(self, "payload", ensure_public_payload(self.payload))

    @property
    def is_current(self) -> bool:
        return self.current

    @property
    def name(self) -> str | None:
        return self.display_name


@dataclass(frozen=True, slots=True)
class EvidenceObservation:
    """Immutable observation of one resource in one source snapshot."""

    observation_id: str
    snapshot_id: str
    resource_id: str
    row_hash: str
    observed_at: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    is_current: bool = True

    def __post_init__(self) -> None:
        if not self.observation_id or not self.snapshot_id or not self.resource_id:
            raise EvidenceValidationError("observation IDs are required")
        object.__setattr__(self, "payload", ensure_public_payload(self.payload))

    @property
    def current(self) -> bool:
        return self.is_current


@dataclass(frozen=True, slots=True)
class RouteHypothesis:
    """A public route/relationship suggestion awaiting human resolution."""

    hypothesis_id: str
    case_id: str
    route_kind: str
    target: str
    rationale: str = ""
    confidence: float | None = None
    status: RouteStatus = RouteStatus.HYPOTHESIS
    evidence_ids: tuple[str, ...] = ()
    source_label: str | None = None

    def __post_init__(self) -> None:
        if not self.hypothesis_id or not self.case_id or not self.route_kind or not self.target:
            raise EvidenceValidationError("route hypothesis identifiers and target are required")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise EvidenceValidationError("route confidence must be between 0 and 1")
        object.__setattr__(self, "status", RouteStatus(self.status))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))


@dataclass(frozen=True, slots=True)
class RouteResolution:
    """Human resolution of a route hypothesis."""

    resolution_id: str
    hypothesis_id: str
    case_id: str
    decision: str
    rationale: str = ""
    resolved_at: str | None = None
    source_label: str | None = None

    def __post_init__(self) -> None:
        if self.decision not in {"resolved", "rejected"}:
            raise EvidenceValidationError("route decision must be resolved or rejected")


@dataclass(frozen=True, slots=True)
class ReadinessItem:
    """One truth-table input to a case readiness assessment."""

    key: str
    label: str
    state: ReadinessState | str
    blocking: bool = True
    evidence_ids: tuple[str, ...] = ()
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.label:
            raise EvidenceValidationError("readiness key and label are required")
        object.__setattr__(self, "state", ReadinessState(self.state))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))

    @property
    def required(self) -> bool:
        return self.blocking


@dataclass(frozen=True, slots=True)
class ReadinessAssessment:
    """Deterministic aggregate of readiness items."""

    ready: bool
    coverage: float
    blocking: tuple[ReadinessItem, ...]
    advisory: tuple[ReadinessItem, ...]
    items: tuple[ReadinessItem, ...]

    @property
    def state(self) -> str:
        return "validated" if self.ready else "needs_verification"

    @property
    def blocking_keys(self) -> tuple[str, ...]:
        return tuple(item.key for item in self.blocking)

    @property
    def advisory_keys(self) -> tuple[str, ...]:
        return tuple(item.key for item in self.advisory)


@dataclass(frozen=True, slots=True)
class Task:
    """An idempotent blocking or advisory follow-up task."""

    task_id: str
    case_id: str
    task_type: str
    severity: TaskSeverity | str
    title: str
    fingerprint: str
    status: TaskStatus | str = TaskStatus.OPEN
    details: Mapping[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    resolved_at: str | None = None

    def __post_init__(self) -> None:
        if not self.task_id or not self.case_id or not self.task_type or not self.title:
            raise EvidenceValidationError("task identifiers and title are required")
        object.__setattr__(self, "severity", TaskSeverity(self.severity))
        object.__setattr__(self, "status", TaskStatus(self.status))
        object.__setattr__(self, "details", ensure_public_payload(self.details))


def make_readiness_item(
    key: str,
    label: str,
    *,
    verified: bool | None,
    blocking: bool = True,
    evidence_ids: Iterable[str] = (),
    note: str | None = None,
) -> ReadinessItem:
    """Build an item from a compact three-valued truth-table input.

    ``True`` is verified, ``False`` is missing, and ``None`` means that a
    human must verify the claim.  This makes connector/UI adapters explicit
    about unknown versus negative evidence.
    """

    state = (
        ReadinessState.VERIFIED
        if verified is True
        else ReadinessState.MISSING
        if verified is False
        else ReadinessState.NEEDS_VERIFICATION
    )
    return ReadinessItem(key, label, state, blocking, tuple(evidence_ids), note)


def assess_readiness(items: Iterable[ReadinessItem]) -> ReadinessAssessment:
    """Apply the readiness truth table.

    Verified and not-applicable items count as covered.  A missing or unknown
    item blocks only when its ``blocking`` flag is true; advisory gaps are
    reported but do not make a case unready.  Empty input is *not* considered
    validated, preventing an accidental no-evidence approval.
    """

    normalized = tuple(item if isinstance(item, ReadinessItem) else ReadinessItem(**item) for item in items)  # type: ignore[arg-type]
    blocking = tuple(
        item
        for item in normalized
        if item.blocking and item.state in {ReadinessState.MISSING, ReadinessState.NEEDS_VERIFICATION}
    )
    advisory = tuple(
        item
        for item in normalized
        if not item.blocking and item.state in {ReadinessState.MISSING, ReadinessState.NEEDS_VERIFICATION}
    )
    covered = sum(item.state in {ReadinessState.VERIFIED, ReadinessState.NOT_APPLICABLE} for item in normalized)
    coverage = covered / len(normalized) if normalized else 0.0
    return ReadinessAssessment(bool(normalized) and not blocking, coverage, blocking, advisory, normalized)


def readiness_truth_table(
    *,
    required_verified: bool,
    required_unknown: bool,
    advisory_unknown: bool,
) -> bool:
    """Return whether compact flags imply validation.

    The helper is useful for tests and adapters: validation requires every
    required field to be present and known.  Advisory unknowns do not block.
    ``required_verified`` is retained as an explicit argument to make callers'
    intent visible; it must be true and no required field may be unknown.
    """

    return bool(required_verified and not required_unknown)


# Common names used by UI code and earlier prototypes.
compute_readiness = assess_readiness
compute_readiness_matrix = assess_readiness


__all__ = [
    "EvidenceObservation",
    "EvidenceValidationError",
    "ReadinessAssessment",
    "ReadinessItem",
    "ReadinessState",
    "RouteHypothesis",
    "RouteResolution",
    "RouteStatus",
    "SourceRecord",
    "SourceSnapshot",
    "Task",
    "TaskSeverity",
    "TaskStatus",
    "assess_readiness",
    "canonical_json",
    "compute_readiness",
    "compute_readiness_matrix",
    "ensure_public_payload",
    "fingerprint",
    "make_readiness_item",
    "readiness_truth_table",
    "row_fingerprint",
]
