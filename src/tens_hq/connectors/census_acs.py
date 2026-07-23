"""Census ACS geography connector (the smallest live public-API connector).

This is the A1 walking-skeleton connector: given a county + state, resolve the
county FIPS and pull one ACS figure -- the disability characteristics from ACS
Subject Table S1810 -- for that county.  It is a *context* source only (N4):
county-level population statistics, never a candidate-supply or capacity claim.

Design (see :mod:`tens_hq.connectors.api`):

* ``retrieve_*`` functions are the only network steps (stdlib ``urllib`` GET).
* ``parse_*`` functions are pure and byte-in, coded to the documented Census
  API JSON shape: a JSON array whose first row is the header and whose
  remaining rows are values.

Provenance captured on the returned record: the retrieval timestamp, the source
URL, and the ACS survey-year vintage.  A rate-limit or upstream failure is a
loud :class:`ConnectorError`, never a silently-empty record.

NOTE: the connector is coded to the Census API's documented response shape and
verified against hand-authored fixtures.  The live endpoint must be verified on
first real run (see the repository handoff/caveats).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Callable
from urllib.parse import quote

from .api import RetrievedPayload, http_get
from .base import ConnectorError, utc_now

# The public ACS API base.  ACS 5-year detailed tables live under ``acs/acs5``;
# subject tables (S-prefixed, e.g. S1810) live under ``acs/acs5/subject``.
ACS_API_BASE = "https://api.census.gov/data"

# The Census data API requires a (free) API key on every request (it returns
# an HTML "Missing Key" page otherwise -- observed live 2026-07-22 on the
# real-PIID dry run). The key is the analyst's own, supplied via this
# environment variable; it rides ONLY the wire request. Every cited /
# rendered source URL stays keyless so the key can never leak into a packet,
# an export, or a screenshot.
CENSUS_API_KEY_ENV = "TENS_HQ_CENSUS_API_KEY"

# The ACS vintage used by the demo.  ACS 5-year is the smallest reliable county
# grain.  The vintage is recorded on every record so a figure is never shown
# without the survey year it came from.
DEFAULT_ACS_YEAR = 2022
ACS_SURVEY_LABEL = "ACS 5-Year Estimates, Subject Table S1810 (Disability Characteristics)"

# S1810 disability-characteristics columns (documented Census variable IDs):
#   C01_001E -- total civilian noninstitutionalized population (the universe)
#   C02_001E -- number with a disability
#   C03_001E -- percent with a disability (ACS-published)
_S1810_TOTAL = "S1810_C01_001E"
_S1810_WITH_DISABILITY = "S1810_C02_001E"
_S1810_PERCENT = "S1810_C03_001E"

# Two-letter USPS code -> two-digit state FIPS (FIPS 5-2 / INCITS 38 standard).
# A fixed, non-fuzzy lookup, in the same spirit as the state-name table the
# workbook parser uses.
STATE_FIPS: dict[str, str] = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56", "PR": "72",
}


@dataclass(frozen=True)
class CountyFips:
    """A resolved county geography (state + county FIPS) with its matched name."""

    state_code: str
    state_fips: str
    county_fips: str
    matched_name: str
    county_query: str


@dataclass(frozen=True)
class GeographyRecord:
    """One county's ACS disability context figure, with full provenance.

    Every field is a public, county-level aggregate.  There is no person-level
    data and no score of any kind.
    """

    county_name: str
    state_code: str
    state_fips: str
    county_fips: str
    total_population: int
    with_disability: int
    disability_percent: float
    acs_survey: str
    acs_vintage_year: int
    source_url: str
    retrieved_at: str

    def to_public_payload(self) -> dict[str, Any]:
        """A public, org/aggregate-only payload (passes the evidence wall)."""

        return {
            "county_name": self.county_name,
            "state_code": self.state_code,
            "state_fips": self.state_fips,
            "county_fips": self.county_fips,
            "total_population": self.total_population,
            "with_disability": self.with_disability,
            "disability_percent": self.disability_percent,
            "acs_survey": self.acs_survey,
            "acs_vintage_year": self.acs_vintage_year,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
        }


def _census_api_key() -> str | None:
    key = os.environ.get(CENSUS_API_KEY_ENV, "").strip()
    return key or None


def _keyed(cited_url: str) -> str:
    """The wire-request URL: the cited URL plus the analyst's key, if set."""

    key = _census_api_key()
    if not key:
        return cited_url
    separator = "&" if "?" in cited_url else "?"
    return f"{cited_url}{separator}key={quote(key, safe='')}"


def _looks_like_missing_key_page(body: bytes) -> bool:
    """Recognize the Census API's HTML 'Missing Key' page (a 200 response)."""

    sample = body[:2048].decode("utf-8", errors="replace").lower()
    return "missing key" in sample or "key_signup" in sample


def _rows(payload: RetrievedPayload | bytes) -> list[list[Any]]:
    """Decode the documented ACS array-of-arrays response, failing closed."""

    body = payload.body if isinstance(payload, RetrievedPayload) else bytes(payload)
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeError):
        if _looks_like_missing_key_page(body):
            raise ConnectorError("CENSUS_KEY_REQUIRED") from None
        raise ConnectorError("UPSTREAM_SCHEMA") from None
    if not isinstance(data, list) or len(data) < 1 or not all(isinstance(row, list) for row in data):
        raise ConnectorError("UPSTREAM_SCHEMA")
    return data


def _header_index(header: list[Any], required: tuple[str, ...]) -> dict[str, int]:
    index = {str(name): position for position, name in enumerate(header)}
    if any(column not in index for column in required):
        raise ConnectorError("UPSTREAM_SCHEMA")
    return index


def _normalize_county(value: str) -> str:
    text = " ".join(str(value).strip().casefold().split())
    for suffix in (" county", " parish", " borough", " census area", " municipality"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    return text


def _to_int(value: Any) -> int:
    # ACS uses large negative sentinels (e.g. -666666666) for suppressed/absent
    # estimates.  Treat those and any non-integer as an unusable response rather
    # than a real figure.
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ConnectorError("UPSTREAM_SCHEMA") from None
    if number < 0:
        raise ConnectorError("UPSTREAM_SCHEMA")
    return number


def _to_float(value: Any) -> float:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        raise ConnectorError("UPSTREAM_SCHEMA") from None
    if number < 0:
        raise ConnectorError("UPSTREAM_SCHEMA")
    return number


def parse_county_fips(payload: RetrievedPayload | bytes, *, county: str, state: str) -> CountyFips:
    """Resolve a county name to its FIPS from the documented county index.

    The index response is ``[["NAME","state","county"], ["Denver County,
    Colorado","08","031"], ...]``.  Matching is exact on the normalized county
    name (case/whitespace folded, a trailing "County"/"Parish"/... dropped) --
    never a substring or fuzzy match.
    """

    rows = _rows(payload)
    index = _header_index(rows[0], ("NAME", "state", "county"))
    wanted = _normalize_county(county)
    for row in rows[1:]:
        name = str(row[index["NAME"]])
        county_part = name.split(",", 1)[0]
        if _normalize_county(county_part) == wanted:
            return CountyFips(
                state_code=str(state).strip().upper(),
                state_fips=str(row[index["state"]]),
                county_fips=str(row[index["county"]]),
                matched_name=name,
                county_query=str(county).strip(),
            )
    raise ConnectorError("GEOGRAPHY_NOT_FOUND")


def parse_acs_disability(
    payload: RetrievedPayload,
    *,
    county: str,
    state: str,
    state_fips: str,
    county_fips: str,
    year: int,
) -> GeographyRecord:
    """Turn an S1810 response into a :class:`GeographyRecord` with provenance.

    The value row carries the three documented S1810 columns.  Provenance
    (source URL + retrieval time) is taken from the :class:`RetrievedPayload`
    produced by the network ``retrieve`` step, and the survey vintage from
    ``year`` -- so a figure can never render without its citation.
    """

    rows = _rows(payload)
    index = _header_index(rows[0], ("NAME", _S1810_TOTAL, _S1810_WITH_DISABILITY, _S1810_PERCENT))
    if len(rows) < 2:
        raise ConnectorError("GEOGRAPHY_NOT_FOUND")
    values = rows[1]
    name = str(values[index["NAME"]]) or county
    return GeographyRecord(
        county_name=name,
        state_code=str(state).strip().upper(),
        state_fips=str(state_fips),
        county_fips=str(county_fips),
        total_population=_to_int(values[index[_S1810_TOTAL]]),
        with_disability=_to_int(values[index[_S1810_WITH_DISABILITY]]),
        disability_percent=_to_float(values[index[_S1810_PERCENT]]),
        acs_survey=ACS_SURVEY_LABEL,
        acs_vintage_year=int(year),
        source_url=payload.source_uri,
        retrieved_at=payload.retrieved_at.isoformat(),
    )


def county_index_url(state_fips: str, *, year: int = DEFAULT_ACS_YEAR) -> str:
    return f"{ACS_API_BASE}/{year}/acs/acs5?get=NAME&for=county:*&in=state:{state_fips}"


def acs_disability_url(state_fips: str, county_fips: str, *, year: int = DEFAULT_ACS_YEAR) -> str:
    variables = ",".join(("NAME", _S1810_TOTAL, _S1810_WITH_DISABILITY, _S1810_PERCENT))
    return (
        f"{ACS_API_BASE}/{year}/acs/acs5/subject"
        f"?get={variables}&for=county:{county_fips}&in=state:{state_fips}"
    )


def retrieve_county_index(
    state_fips: str,
    *,
    year: int = DEFAULT_ACS_YEAR,
    clock: Callable[[], datetime] = utc_now,
    opener: Any | None = None,
) -> RetrievedPayload:
    """Network step: fetch the county-name index for a state.

    The request carries the analyst's API key when one is configured; the
    returned payload's ``source_uri`` (which feeds every citation) is always
    the keyless URL.
    """

    cited_url = county_index_url(state_fips, year=year)
    payload = http_get(_keyed(cited_url), clock=clock, opener=opener)
    return replace(payload, source_uri=cited_url)


def retrieve_acs_disability(
    state_fips: str,
    county_fips: str,
    *,
    year: int = DEFAULT_ACS_YEAR,
    clock: Callable[[], datetime] = utc_now,
    opener: Any | None = None,
) -> RetrievedPayload:
    """Network step: fetch the S1810 disability figure for one county.

    Same key handling as :func:`retrieve_county_index`: keyed request,
    keyless cited ``source_uri``.
    """

    cited_url = acs_disability_url(state_fips, county_fips, year=year)
    payload = http_get(_keyed(cited_url), clock=clock, opener=opener)
    return replace(payload, source_uri=cited_url)


def pull_geography_context(
    county: str,
    state: str,
    *,
    year: int = DEFAULT_ACS_YEAR,
    clock: Callable[[], datetime] = utc_now,
    opener: Any | None = None,
) -> GeographyRecord:
    """Resolve a county + state to its ACS disability context figure.

    Orchestration only: state FIPS is a local lookup, then two network
    ``retrieve`` steps feed two pure ``parse`` steps.  Any upstream failure
    propagates as a loud :class:`ConnectorError`.
    """

    state_code = str(state).strip().upper()
    state_fips = STATE_FIPS.get(state_code)
    if not state_fips:
        raise ConnectorError("GEOGRAPHY_NOT_FOUND")
    index_payload = retrieve_county_index(state_fips, year=year, clock=clock, opener=opener)
    resolved = parse_county_fips(index_payload, county=county, state=state_code)
    disability_payload = retrieve_acs_disability(
        resolved.state_fips, resolved.county_fips, year=year, clock=clock, opener=opener
    )
    return parse_acs_disability(
        disability_payload,
        county=resolved.matched_name or county,
        state=state_code,
        state_fips=resolved.state_fips,
        county_fips=resolved.county_fips,
        year=year,
    )


__all__ = [
    "ACS_API_BASE",
    "ACS_SURVEY_LABEL",
    "CENSUS_API_KEY_ENV",
    "CountyFips",
    "DEFAULT_ACS_YEAR",
    "GeographyRecord",
    "STATE_FIPS",
    "acs_disability_url",
    "county_index_url",
    "parse_acs_disability",
    "parse_county_fips",
    "pull_geography_context",
    "retrieve_acs_disability",
    "retrieve_county_index",
]
