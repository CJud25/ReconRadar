"""Small, privacy-preserving location value objects used by BD cases.

The feasibility workflow deliberately stores only a city, a two-letter state,
and (when supplied) a five digit ZIP code.  County names, FIPS codes, and
address-level fields are intentionally not represented by this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class LocationValidationError(ValueError):
    """Raised when a case location is not in the supported public shape."""


_STATE_RE = re.compile(r"^[A-Za-z]{2}$")
_ZIP_RE = re.compile(r"^\d{5}$")


def _clean_city(value: Any) -> str:
    if not isinstance(value, str):
        raise LocationValidationError("city is required")
    city = " ".join(value.split())
    if not city:
        raise LocationValidationError("city is required")
    return city


def _clean_state(value: Any) -> str:
    if not isinstance(value, str) or not _STATE_RE.fullmatch(value.strip()):
        raise LocationValidationError("state must be a two-letter code")
    return value.strip().upper()


def _clean_zip(value: Any) -> str | None:
    if value is None or value == "":
        return None
    # Do not coerce integers: coercion would silently lose leading zeroes and
    # make malformed input look valid.
    if not isinstance(value, str) or not _ZIP_RE.fullmatch(value.strip()):
        raise LocationValidationError("postal_code must be an optional five-digit ZIP")
    return value.strip()


@dataclass(frozen=True, slots=True)
class Location:
    """A normalized public location.

    ``postal_code`` is optional.  The class has no county/FIPS/address fields
    by design; callers attempting to pass those fields get a normal Python
    ``TypeError`` rather than accidentally persisting them.
    """

    city: str
    state: str
    postal_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "city", _clean_city(self.city))
        object.__setattr__(self, "state", _clean_state(self.state))
        object.__setattr__(self, "postal_code", _clean_zip(self.postal_code))

    @property
    def zip_code(self) -> str | None:
        """Alias used by a few UI callers."""

        return self.postal_code

    @property
    def zip5(self) -> str | None:
        """Alias for the normalized five-digit ZIP value."""

        return self.postal_code

    def as_dict(self) -> dict[str, str]:
        """Return only the supported public fields."""

        result = {"city": self.city, "state": self.state}
        if self.postal_code is not None:
            result["postal_code"] = self.postal_code
        return result

    def __str__(self) -> str:
        suffix = f" {self.postal_code}" if self.postal_code else ""
        return f"{self.city}, {self.state}{suffix}"


def normalize_location(
    city: str,
    state: str,
    postal_code: str | None = None,
    *,
    zip_code: str | None = None,
) -> Location:
    """Validate and normalize a location.

    ``zip_code`` is an ergonomic alias for ``postal_code``.  Supplying both
    aliases with different values is rejected to avoid ambiguous writes.
    """

    if postal_code is not None and zip_code is not None and postal_code != zip_code:
        raise LocationValidationError("postal_code and zip_code disagree")
    return Location(city, state, postal_code if postal_code is not None else zip_code)


def validate_location(
    city: str,
    state: str,
    postal_code: str | None = None,
    *,
    zip_code: str | None = None,
) -> Location:
    """Compatibility spelling for :func:`normalize_location`."""

    return normalize_location(city, state, postal_code, zip_code=zip_code)


__all__ = ["Location", "LocationValidationError", "normalize_location", "validate_location"]
