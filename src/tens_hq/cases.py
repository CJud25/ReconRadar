"""Case domain objects and workflow invariants.

Cases are deliberately about a public, prospective operating location.  They
do not carry a person identifier or a person-level owner.  Ownership is a
controlled team/role alias so that the tracker can be shared without becoming
an employee directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
import re
from typing import Any, Mapping

from .locations import Location, normalize_location


class CaseValidationError(ValueError):
    """Raised when a case field violates the public-data contract."""


class CaseState(str, Enum):
    """Persisted case states.

    A case may be rescanned from ``Needs Verification`` or ``Validated``.
    ``Closed`` is intentionally terminal; reopening requires a new case so
    that the historical decision trail remains intact.
    """

    DRAFT = "Draft"
    SCANNING = "Scanning"
    NEEDS_VERIFICATION = "Needs Verification"
    VALIDATED = "Validated"
    CLOSED = "Closed"


# A stable alias set is preferable to person IDs (or arbitrary usernames).
# Synonyms are normalized to the canonical values below.
TEAM_ALIASES = frozenset(
    {
        "bd",
        "business_development",
        "capture",
        "compliance",
        "operations",
        "research",
        "admin",
    }
)
ROLE_ALIASES = frozenset(
    {
        "owner",
        "analyst",
        "operator",
        "reviewer",
        "approver",
        "read_only",
        "capture_manager",
        "compliance_reviewer",
    }
)

_TEAM_SYNONYMS = {
    "business-development": "business_development",
    "business development": "business_development",
    "bizdev": "bd",
    "ops": "operations",
    "operation": "operations",
    "qa": "compliance",
}
_ROLE_SYNONYMS = {
    "read-only": "read_only",
    "read only": "read_only",
    "capture manager": "capture_manager",
    "compliance reviewer": "compliance_reviewer",
}


def _alias(value: Any, *, kind: str) -> str:
    if not isinstance(value, str):
        raise CaseValidationError(f"{kind} alias is required")
    value = "_".join(value.strip().lower().split())
    value = re.sub(r"[^a-z0-9_-]", "", value)
    synonyms = _TEAM_SYNONYMS if kind == "team" else _ROLE_SYNONYMS
    value = synonyms.get(value, value)
    values = TEAM_ALIASES if kind == "team" else ROLE_ALIASES
    if value not in values:
        raise CaseValidationError(f"unknown controlled {kind} alias: {value!r}")
    return value


def normalize_team_alias(value: Any) -> str:
    """Normalize a controlled team alias; arbitrary person IDs are rejected."""

    return _alias(value, kind="team")


def normalize_role_alias(value: Any) -> str:
    """Normalize a controlled role alias; arbitrary person IDs are rejected."""

    return _alias(value, kind="role")


def coerce_case_state(value: CaseState | str) -> CaseState:
    """Convert persisted/user state text into :class:`CaseState`."""

    if isinstance(value, CaseState):
        return value
    try:
        return CaseState(value)
    except (TypeError, ValueError) as exc:
        raise CaseValidationError(f"unknown case state: {value!r}") from exc


# Explicit state graph.  Scanning is entered only by a scan start; finalization
# chooses Needs Verification versus Validated.  A failed run restores the
# ``prior_state`` recorded on the scan row and therefore does not use this
# graph's success edge.
#
# Closure is reachable *only* from ``Validated``.  A ``Draft`` or ``Needs
# Verification`` case cannot jump straight to the terminal ``Closed`` state,
# because doing so would let a case be closed while skipping validation and
# leave a historical trail that looks decided when its evidence gates were
# still open.  To close a case that should not be pursued, validate it first
# (or leave it un-closed); reopening a closed case still requires a new case.
ALLOWED_TRANSITIONS: Mapping[CaseState, frozenset[CaseState]] = {
    CaseState.DRAFT: frozenset({CaseState.SCANNING}),
    CaseState.SCANNING: frozenset(
        {CaseState.DRAFT, CaseState.NEEDS_VERIFICATION, CaseState.VALIDATED}
    ),
    CaseState.NEEDS_VERIFICATION: frozenset({CaseState.SCANNING}),
    CaseState.VALIDATED: frozenset({CaseState.SCANNING, CaseState.CLOSED}),
    CaseState.CLOSED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class Case:
    """A durable feasibility case with an optimistic-lock version."""

    case_id: str
    title: str
    location: Location
    team_alias: str
    role_alias: str
    state: CaseState = CaseState.DRAFT
    version: int = 1
    created_at: str | None = None
    updated_at: str | None = None
    closed_at: str | None = None
    last_error: str | None = None
    contract_type: str | None = None
    service_type: str | None = None
    target_headcount: int | None = None
    target_start_date: str | None = None
    job_family_requirements: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise CaseValidationError("case_id is required")
        if not isinstance(self.title, str) or not self.title.strip():
            raise CaseValidationError("title is required")
        object.__setattr__(self, "title", " ".join(self.title.split()))
        if not isinstance(self.location, Location):
            raise CaseValidationError("location must be a Location")
        object.__setattr__(self, "team_alias", normalize_team_alias(self.team_alias))
        object.__setattr__(self, "role_alias", normalize_role_alias(self.role_alias))
        object.__setattr__(self, "state", coerce_case_state(self.state))
        if not isinstance(self.version, int) or self.version < 1:
            raise CaseValidationError("version must be a positive integer")
        if self.target_headcount is not None and (not isinstance(self.target_headcount, int) or isinstance(self.target_headcount, bool) or self.target_headcount <= 0):
            raise CaseValidationError("target_headcount must be a positive integer")
        if self.target_start_date is not None:
            if not isinstance(self.target_start_date, str) or not self.target_start_date.strip():
                raise CaseValidationError("target_start_date must be an ISO date")
            try:
                date.fromisoformat(self.target_start_date.strip())
            except ValueError as exc:
                raise CaseValidationError("target_start_date must be an ISO date") from exc
            object.__setattr__(self, "target_start_date", self.target_start_date.strip())
        object.__setattr__(self, "job_family_requirements", tuple(str(value).strip() for value in self.job_family_requirements if str(value).strip()))

    @property
    def status(self) -> CaseState:
        """Alias for UIs that call the state field ``status``."""

        return self.state

    @property
    def case_state(self) -> CaseState:
        """Explicit alias for callers that want to avoid ``state`` ambiguity."""

        return self.state

    @property
    def city(self) -> str:
        return self.location.city

    @property
    def state_code(self) -> str:
        return self.location.state

    @property
    def postal_code(self) -> str | None:
        return self.location.postal_code

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly public representation."""

        return {
            "case_id": self.case_id,
            "title": self.title,
            **self.location.as_dict(),
            "team_alias": self.team_alias,
            "role_alias": self.role_alias,
            "state": self.state.value,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "closed_at": self.closed_at,
            "last_error": self.last_error,
            "contract_type": self.contract_type,
            "service_type": self.service_type,
            "target_headcount": self.target_headcount,
            "target_start_date": self.target_start_date,
            "job_family_requirements": list(self.job_family_requirements),
        }


@dataclass(frozen=True, slots=True)
class CaseCreate:
    """Input value object accepted by :meth:`CaseRepository.create_case`."""

    title: str
    city: str
    state: str
    postal_code: str | None = None
    team_alias: str = "bd"
    role_alias: str = "owner"
    case_id: str | None = None
    contract_type: str | None = None
    service_type: str | None = None
    target_headcount: int | None = None
    target_start_date: str | None = None
    job_family_requirements: tuple[str, ...] = ()

    def to_location(self) -> Location:
        return normalize_location(self.city, self.state, self.postal_code)


@dataclass(frozen=True, slots=True)
class CaseUpdate:
    """Optional public case fields for optimistic updates."""

    title: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    team_alias: str | None = None
    role_alias: str | None = None


def ensure_transition(current: CaseState | str, target: CaseState | str) -> tuple[CaseState, CaseState]:
    """Validate the state graph and return normalized states.

    The repository calls this before every user-requested transition.  Scan
    start/finalization use the same helper, while failure restoration is a
    controlled exception documented on the scan API.
    """

    source = coerce_case_state(current)
    destination = coerce_case_state(target)
    if destination not in ALLOWED_TRANSITIONS[source]:
        raise CaseValidationError(f"invalid case transition: {source.value} -> {destination.value}")
    return source, destination


__all__ = [
    "ALLOWED_TRANSITIONS",
    "Case",
    "CaseCreate",
    "CaseState",
    "CaseStatus",
    "CaseUpdate",
    "CaseValidationError",
    "ROLE_ALIASES",
    "TEAM_ALIASES",
    "coerce_case_state",
    "ensure_transition",
    "normalize_role_alias",
    "normalize_team_alias",
]

# A compatibility name used by callers that prefer status terminology.
CaseStatus = CaseState
