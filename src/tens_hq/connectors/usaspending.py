"""USAspending single-award contract-facts connector.

Given a pasted PIID, resolve it to a single federal award and retrieve real,
cited contract facts (obligated, ceiling, period of performance, set-aside,
extent-competed, offers, NAICS/PSC, sub-agency, recipient, and the recipient's
public SAM-registration ``business_categories``).
The facts also include the award's reported description and place of performance.

This module also retrieves that award's reported **subawards** (a second,
independent POST call an analyst may make once the award is resolved) --
public FSRS/FFATA teaming-posture evidence for the incumbent-and-teaming-leads
packet section (A5). It is the same public source and shares the same
``retrieve``/``parse`` helpers, so it stays in this module rather than a
separate one.

Design (see :mod:`tens_hq.connectors.api`), mirroring the ACS connector:

* ``retrieve_*`` functions are the only network steps (the search is a POST, the
  detail a GET). ``parse_*`` functions are pure and byte-in, coded to the
  documented/confirmed-live USAspending JSON shapes, so they stay fully testable
  offline against hand-authored fixtures.

Two honesty facts drive the design:

* **A PIID is not unique.** The keyword search is fuzzy/substring; probing one
  PIID returned three distinct awards sharing it. The connector filters to EXACT
  ``Award ID`` matches and, when more than one remains, returns the candidates
  for the analyst to disambiguate -- it NEVER silently picks one and never
  fetches a detail in that state. Zero exact matches is a loud ``AWARD_NOT_FOUND``.
* **Obligated is not the ceiling.** ``total_obligation`` (money obligated) and
  ``base_and_all_options`` (potential value with all options) are kept as
  distinct fields; a legitimately-``null`` field (e.g. an unreported set-aside)
  stays ``None`` and is never coerced to ``0``/``""``.

NOTE: the connector is coded to the confirmed-live USAspending shapes and
verified against hand-authored fixtures. The live endpoint must be verified on
first real run (see the repository handoff/caveats), consistent with ADR-011.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from .api import RetrievedPayload, http_get, http_post
from .base import ConnectorError, utc_now

USASPENDING_API_BASE = "https://api.usaspending.gov/api/v2"
_AWARD_SEARCH_PATH = "/search/spending_by_award/"  # POST (keep trailing slash)

# Definitive contract award-type codes (procurement awards, not assistance).
_SEARCH_AWARD_TYPE_CODES = ("A", "B", "C", "D")
_SEARCH_FIELDS = (
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Contract Award Type",
    "Awarding Agency",
    "Awarding Sub Agency",
    "NAICS",
    "PSC",
    "Start Date",
    "End Date",
)
DEFAULT_AWARD_SEARCH_LIMIT = 100  # USAspending's per-page maximum; reduces truncation


@dataclass(frozen=True)
class AwardCandidate:
    """One search-result row the analyst may need to disambiguate (PIID not unique)."""

    award_id: str
    generated_internal_id: str
    recipient_name: str | None
    subagency_name: str | None
    award_amount: float | None
    start_date: str | None
    contract_award_type: str | None
    naics_code: str | None
    psc_code: str | None


@dataclass(frozen=True)
class ContractFactsRecord:
    """Parsed single-award facts, coded to confirmed-live keys, with provenance."""

    piid: str
    generated_unique_award_id: str | None
    award_type_code: str | None
    award_type_description: str | None
    category: str | None
    date_signed: str | None
    total_obligation: float | None  # OBLIGATED (money actually obligated)
    base_and_all_options: float | None  # CEILING (potential value w/ options; NOT money)
    period_start_date: str | None
    period_end_date: str | None  # current end
    period_potential_end_date: str | None  # RAW string; may carry a " 00:00:00" suffix
    toptier_agency_name: str | None
    subagency_name: str | None  # the real discriminator (subtier)
    recipient_name: str | None
    recipient_uei: str | None
    recipient_business_categories: tuple[str, ...] | None  # public SAM registration facts
    set_aside_code: str | None  # FPDS type_set_aside; may be None (= not reported)
    set_aside_description: str | None
    extent_competed_code: str | None  # a CODE (reliable); reason off this, not the text
    extent_competed_description: str | None
    number_of_offers_received: int | None
    naics_code: str | None
    naics_description: str | None
    psc_code: str | None
    psc_description: str | None
    description: str | None
    pop_city_name: str | None
    pop_county_name: str | None
    pop_state_code: str | None
    pop_country_code: str | None
    source_url: str  # the detail endpoint URL (the citation)
    retrieved_at: str  # RetrievedPayload.retrieved_at.isoformat()
    synthetic_example: bool = False  # True only for the bundled offline example (ADR-025)

    def to_public_payload(self) -> dict[str, Any]:
        """A flat, public dict of exactly the fields above (mirrors GeographyRecord)."""

        return {
            "piid": self.piid,
            "generated_unique_award_id": self.generated_unique_award_id,
            "award_type_code": self.award_type_code,
            "award_type_description": self.award_type_description,
            "category": self.category,
            "date_signed": self.date_signed,
            "total_obligation": self.total_obligation,
            "base_and_all_options": self.base_and_all_options,
            "period_start_date": self.period_start_date,
            "period_end_date": self.period_end_date,
            "period_potential_end_date": self.period_potential_end_date,
            "toptier_agency_name": self.toptier_agency_name,
            "subagency_name": self.subagency_name,
            "recipient_name": self.recipient_name,
            "recipient_uei": self.recipient_uei,
            "recipient_business_categories": self.recipient_business_categories,
            "set_aside_code": self.set_aside_code,
            "set_aside_description": self.set_aside_description,
            "extent_competed_code": self.extent_competed_code,
            "extent_competed_description": self.extent_competed_description,
            "number_of_offers_received": self.number_of_offers_received,
            "naics_code": self.naics_code,
            "naics_description": self.naics_description,
            "psc_code": self.psc_code,
            "psc_description": self.psc_description,
            "description": self.description,
            "pop_city_name": self.pop_city_name,
            "pop_county_name": self.pop_county_name,
            "pop_state_code": self.pop_state_code,
            "pop_country_code": self.pop_country_code,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "synthetic_example": self.synthetic_example,
        }


@dataclass(frozen=True)
class ContractFactsResolution:
    """Outcome of resolving a PIID. Exactly one of the two states is populated:

    * resolved  -> ``record`` is set (exactly one exact award matched, or the
      analyst supplied a ``generated_internal_id`` directly); ``candidates`` empty.
    * ambiguous -> ``record`` is None and ``candidates`` has >1 entries (the
      analyst must disambiguate). The detail endpoint is NOT fetched in this state.

    A zero-match PIID never becomes a resolution; it raises
    ``ConnectorError("AWARD_NOT_FOUND")``.
    """

    piid: str
    record: ContractFactsRecord | None = None
    candidates: tuple[AwardCandidate, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.record is not None

    @property
    def ambiguous(self) -> bool:
        return self.record is None and len(self.candidates) > 1


def award_search_url() -> str:
    return f"{USASPENDING_API_BASE}{_AWARD_SEARCH_PATH}"


def award_detail_url(generated_internal_id: str) -> str:
    from urllib.parse import quote

    return f"{USASPENDING_API_BASE}/awards/{quote(str(generated_internal_id), safe='')}/"


def award_search_body(piid: str, *, limit: int = DEFAULT_AWARD_SEARCH_LIMIT) -> dict[str, Any]:
    return {
        "filters": {
            "award_type_codes": list(_SEARCH_AWARD_TYPE_CODES),
            "keywords": [str(piid).strip()],
        },
        "fields": list(_SEARCH_FIELDS),
        "limit": int(limit),
        "page": 1,
    }


def retrieve_award_search(
    piid: str,
    *,
    limit: int = DEFAULT_AWARD_SEARCH_LIMIT,
    clock: Callable[[], datetime] = utc_now,
    opener: Any | None = None,
) -> RetrievedPayload:
    """Network step: POST the award keyword search for a PIID."""

    body = json.dumps(award_search_body(piid, limit=limit)).encode("utf-8")
    return http_post(award_search_url(), body, clock=clock, opener=opener)


def retrieve_award_detail(
    generated_internal_id: str,
    *,
    clock: Callable[[], datetime] = utc_now,
    opener: Any | None = None,
) -> RetrievedPayload:
    """Network step: GET the award detail for a resolved award id."""

    return http_get(award_detail_url(generated_internal_id), clock=clock, opener=opener)


def _body_json(payload: RetrievedPayload | bytes) -> Any:
    body = payload.body if isinstance(payload, RetrievedPayload) else bytes(payload)
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise ConnectorError("UPSTREAM_SCHEMA") from None


def _dict_block(value: Any) -> dict[str, Any]:
    """A nested block that is legitimately absent (``None``) is an empty dict; a
    wrong-TYPED block (list/str/number) is a garbled shape and fails loud."""

    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    raise ConnectorError("UPSTREAM_SCHEMA")


def _search_truncated(payload: RetrievedPayload | bytes, *, limit: int) -> bool:
    """Whether the keyword search returned an incomplete (paged) result set.

    Prefers the API's ``page_metadata.hasNext``; falls back to a full page
    (``len(results) >= limit``) when that flag is absent. Used to refuse a silent
    single-award auto-resolve when a further exact match could exist on a later
    page (the "never silently pick one" guarantee must hold under truncation).
    """

    data = _body_json(payload)
    if not isinstance(data, dict):
        return False
    meta = data.get("page_metadata")
    if isinstance(meta, dict) and meta.get("hasNext") is not None:
        return bool(meta.get("hasNext"))
    results = data.get("results")
    return isinstance(results, list) and len(results) >= int(limit)


def _nested_code(value: Any) -> str | None:
    """A NAICS/PSC search cell is a ``{"code","description"}`` dict; pull the code defensively."""

    if isinstance(value, dict):
        code = value.get("code")
        return str(code) if code not in (None, "") else None
    if value in (None, ""):
        return None
    return str(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text != "" else None


def _to_optional_float(value: Any) -> float | None:
    # A legitimately-absent money field is None; a PRESENT but non-numeric value
    # is a real upstream problem (never silently coerced to 0 -- NaN != 0).
    if value is None or value == "":
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        raise ConnectorError("UPSTREAM_SCHEMA") from None


def _optional_str_tuple(value: Any) -> tuple[str, ...] | None:
    # A legitimately-absent/null list (business_categories not reported) is
    # None -- never an empty tuple, so "not reported" and "reported as empty"
    # stay distinguishable. A PRESENT but non-list value (str/dict/number) is a
    # real upstream schema problem and fails loud, matching the other
    # defensive helpers in this module.
    if value is None:
        return None
    if not isinstance(value, list):
        raise ConnectorError("UPSTREAM_SCHEMA")
    return tuple(str(item) for item in value)


def _to_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        # Tolerate a float-encoded count (e.g. "3.0") without rejecting the record.
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        raise ConnectorError("UPSTREAM_SCHEMA") from None


def parse_award_candidates(payload: RetrievedPayload | bytes, *, piid: str) -> tuple[AwardCandidate, ...]:
    """Filter the fuzzy keyword-search results to EXACT Award-ID matches.

    A PIID is not unique and the keyword search is a substring match, so only
    results whose ``Award ID`` equals the queried PIID (case-folded, trimmed) are
    kept. An exact match missing its ``generated_internal_id`` cannot reach detail
    and is a schema fault.
    """

    data = _body_json(payload)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ConnectorError("UPSTREAM_SCHEMA")
    wanted = str(piid).strip().upper()
    candidates: list[AwardCandidate] = []
    for result in data["results"]:
        if not isinstance(result, dict):
            continue
        award_id = str(result.get("Award ID", "")).strip()
        if award_id.upper() != wanted:
            continue
        generated = _optional_str(result.get("generated_internal_id"))
        if not generated:
            raise ConnectorError("UPSTREAM_SCHEMA")
        candidates.append(
            AwardCandidate(
                award_id=award_id,
                generated_internal_id=generated,
                recipient_name=_optional_str(result.get("Recipient Name")),
                subagency_name=_optional_str(result.get("Awarding Sub Agency")),
                award_amount=_to_optional_float(result.get("Award Amount")),
                start_date=_optional_str(result.get("Start Date")),
                contract_award_type=_optional_str(result.get("Contract Award Type")),
                naics_code=_nested_code(result.get("NAICS")),
                psc_code=_nested_code(result.get("PSC")),
            )
        )
    return tuple(candidates)


def parse_contract_facts(payload: RetrievedPayload, *, piid: str) -> ContractFactsRecord:
    """Map a USAspending award-detail response to a cited :class:`ContractFactsRecord`.

    Coded to the confirmed-live keys. Missing nested blocks never crash (``... or {}``);
    a missing scalar becomes ``None``. ``potential_end_date`` is stored as the RAW
    string (it carries a " 00:00:00" suffix) and is NEVER strict-parsed.
    """

    data = _body_json(payload)
    if not isinstance(data, dict):
        raise ConnectorError("UPSTREAM_SCHEMA")
    pop = _dict_block(data.get("period_of_performance"))
    agency = _dict_block(data.get("awarding_agency"))
    toptier = _dict_block(agency.get("toptier_agency"))
    subtier = _dict_block(agency.get("subtier_agency"))
    recipient = _dict_block(data.get("recipient"))
    ltcd = _dict_block(data.get("latest_transaction_contract_data"))
    place = _dict_block(data.get("place_of_performance"))
    return ContractFactsRecord(
        piid=str(data.get("piid") or piid),
        generated_unique_award_id=_optional_str(data.get("generated_unique_award_id")),
        award_type_code=_optional_str(data.get("type")),
        award_type_description=_optional_str(data.get("type_description")),
        category=_optional_str(data.get("category")),
        date_signed=_optional_str(data.get("date_signed")),
        total_obligation=_to_optional_float(data.get("total_obligation")),
        base_and_all_options=_to_optional_float(data.get("base_and_all_options")),
        period_start_date=_optional_str(pop.get("start_date")),
        period_end_date=_optional_str(pop.get("end_date")),
        period_potential_end_date=_optional_str(pop.get("potential_end_date")),
        toptier_agency_name=_optional_str(toptier.get("name")),
        subagency_name=_optional_str(subtier.get("name")),
        recipient_name=_optional_str(recipient.get("recipient_name")),
        recipient_uei=_optional_str(recipient.get("recipient_uei")),
        recipient_business_categories=_optional_str_tuple(recipient.get("business_categories")),
        set_aside_code=_optional_str(ltcd.get("type_set_aside")),
        set_aside_description=_optional_str(ltcd.get("type_set_aside_description")),
        extent_competed_code=_optional_str(ltcd.get("extent_competed")),
        extent_competed_description=_optional_str(ltcd.get("extent_competed_description")),
        number_of_offers_received=_to_optional_int(ltcd.get("number_of_offers_received")),
        naics_code=_optional_str(ltcd.get("naics")),
        naics_description=_optional_str(ltcd.get("naics_description")),
        psc_code=_optional_str(ltcd.get("product_or_service_code")),
        psc_description=_optional_str(ltcd.get("product_or_service_description")),
        description=_optional_str(data.get("description")),
        pop_city_name=_optional_str(place.get("city_name")),
        pop_county_name=_optional_str(place.get("county_name")),
        pop_state_code=_optional_str(place.get("state_code")),
        pop_country_code=_optional_str(place.get("location_country_code")),
        source_url=payload.source_uri,
        retrieved_at=payload.retrieved_at.isoformat(),
    )


def pull_contract_facts(
    piid: str,
    *,
    generated_internal_id: str | None = None,
    limit: int = DEFAULT_AWARD_SEARCH_LIMIT,
    clock: Callable[[], datetime] = utc_now,
    opener: Any | None = None,
) -> ContractFactsResolution:
    """Resolve a PIID to single-award facts, honestly handling multiplicity.

    * If ``generated_internal_id`` is supplied, skip search and fetch that detail
      directly (the analyst picked one from a prior ambiguous result).
    * Else POST the keyword search, filter to EXACT Award-ID matches:
        - exactly 1 -> fetch + parse detail -> resolved.
        - >1        -> return the candidates (ambiguous); do NOT fetch detail or pick one.
        - 0         -> raise ConnectorError("AWARD_NOT_FOUND").
    Any upstream fault propagates as a loud :class:`ConnectorError`.
    """

    piid = str(piid).strip()
    if not piid:
        raise ConnectorError("AWARD_NOT_FOUND")
    if generated_internal_id:
        detail = retrieve_award_detail(generated_internal_id, clock=clock, opener=opener)
        return ContractFactsResolution(piid=piid, record=parse_contract_facts(detail, piid=piid))
    search = retrieve_award_search(piid, limit=limit, clock=clock, opener=opener)
    candidates = parse_award_candidates(search, piid=piid)
    if len(candidates) > 1:
        return ContractFactsResolution(piid=piid, candidates=candidates)
    # A truncated (paged) result set cannot guarantee exact-match completeness, so
    # neither a lone page-1 match (which could have a twin on a later page) nor a
    # zero page-1 count (which could match on a later page) may be trusted --
    # fail loud rather than silently auto-pick or falsely report not-found.
    if _search_truncated(search, limit=limit):
        raise ConnectorError("AWARD_SEARCH_TRUNCATED")
    if not candidates:
        raise ConnectorError("AWARD_NOT_FOUND")
    only = candidates[0]
    detail = retrieve_award_detail(only.generated_internal_id, clock=clock, opener=opener)
    return ContractFactsResolution(piid=piid, record=parse_contract_facts(detail, piid=piid))


# --- Offline SYNTHETIC-example facts (ADR-025) --------------------------------
#
# The bundled Radar-handoff sample (``data/samples/sample_radar_handoff.json``)
# carries the synthetic PIID below. When an analyst pulls contract facts for
# exactly that PIID, the BD page (``bd_page.py``) serves this bundled,
# offline, honestly-labeled example instead of a live network call, so the
# guided demo reaches a populated flagship moment with no network and no red
# error. It is gated to this single PIID and never resembles a live retrieval.

SYNTHETIC_EXAMPLE_PIID = "SYNTH-A2-0001"

# An honest, non-URL provenance string -- deliberately NOT a usaspending.gov
# URL, so this record can never be cited as if it were a live retrieval.
_SYNTHETIC_EXAMPLE_SOURCE_MARKER = (
    "bundled SYNTHETIC example (offline) -- not a live USAspending retrieval"
)


def load_synthetic_example_facts() -> ContractFactsResolution:
    """Build the bundled, offline, honestly-labeled SYNTHETIC-example contract
    facts for :data:`SYNTHETIC_EXAMPLE_PIID` (ADR-025).

    Reads the committed ``data/samples/sample_usaspending_award.json`` fixture
    -- invented content, structurally shaped like a real USAspending award
    detail -- and parses it through the same :func:`parse_contract_facts` a
    live pull uses. The resulting record is then marked
    ``synthetic_example=True`` with its ``source_url`` replaced by an honest,
    non-URL provenance marker, so it can never be mistaken for, or cite, a
    live retrieval. No network is touched; this function opens no socket.
    """

    path = Path(__file__).resolve().parents[3] / "data" / "samples" / "sample_usaspending_award.json"
    body = path.read_bytes()
    payload = RetrievedPayload(
        body=body,
        retrieved_at=datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
        source_uri=_SYNTHETIC_EXAMPLE_SOURCE_MARKER,
        upstream_status=200,
    )
    record = parse_contract_facts(payload, piid=SYNTHETIC_EXAMPLE_PIID)
    record = replace(record, synthetic_example=True, source_url=_SYNTHETIC_EXAMPLE_SOURCE_MARKER)
    return ContractFactsResolution(piid=SYNTHETIC_EXAMPLE_PIID, record=record)


# --- Subawards (teaming-posture evidence for A5's incumbent-and-teaming-leads) -----
#
# A second, independent POST call an analyst may make once an award is resolved:
# does the incumbent prime report subaward records for THIS award (D1 -- scope is
# this award only, not a market-wide "who teams with NPAs" sweep), and who are the
# subawardees. FSRS/FFATA subaward reporting has a real-world reporting threshold
# and is materially under-reported, so an EMPTY result here is never "no teaming
# history" -- that honesty caveat lives in the renderer (incumbent_leads.py), not
# this connector; this module only retrieves and parses the cited facts.

_SUBAWARDS_PATH = "/subawards/"  # POST (keep trailing slash)
DEFAULT_SUBAWARDS_LIMIT = 100


@dataclass(frozen=True)
class SubawardRecord:
    """One reported subaward row, byte-in parsed, provenance carried by the result."""

    subaward_number: str | None
    recipient_name: str | None  # the SUBAWARDEE (not the prime)
    amount: float | None
    action_date: str | None
    description: str | None


@dataclass(frozen=True)
class SubawardsResult:
    """The subawards reported for one resolved award, with provenance and honesty flags.

    ``truncated`` is carried (never raised) when more records exist than were
    retrieved: unlike award-resolution truncation (which breaks a uniqueness
    guarantee and must fail loud, see ``AWARD_SEARCH_TRUNCATED`` above), a
    truncated subaward LIST is still honest evidence -- the renderer states
    that more records exist rather than the pull failing.
    """

    award_generated_internal_id: str
    records: tuple[SubawardRecord, ...]
    truncated: bool
    source_url: str
    retrieved_at: str


def subawards_url() -> str:
    return f"{USASPENDING_API_BASE}{_SUBAWARDS_PATH}"


def subawards_body(generated_internal_id: str, *, limit: int = DEFAULT_SUBAWARDS_LIMIT) -> dict[str, Any]:
    return {
        "award_id": str(generated_internal_id),
        "page": 1,
        "limit": int(limit),
        "sort": "subaward_number",
        "order": "desc",
    }


def retrieve_subawards(
    generated_internal_id: str,
    *,
    limit: int = DEFAULT_SUBAWARDS_LIMIT,
    clock: Callable[[], datetime] = utc_now,
    opener: Any | None = None,
) -> RetrievedPayload:
    """Network step: POST the subawards listing for a resolved award id."""

    body = json.dumps(subawards_body(generated_internal_id, limit=limit)).encode("utf-8")
    return http_post(subawards_url(), body, clock=clock, opener=opener)


def parse_subawards(
    payload: RetrievedPayload,
    *,
    award_generated_internal_id: str,
    limit: int = DEFAULT_SUBAWARDS_LIMIT,
) -> SubawardsResult:
    """Map a USAspending subawards listing response to a cited :class:`SubawardsResult`.

    Pure and byte-in. ``results`` absent/wrong-typed, or any row not a dict, is a
    garbled upstream shape and fails loud (``UPSTREAM_SCHEMA``) -- consistent
    with the rest of this module, a null/absent per-row field is never coerced
    to ``0``/``""``. Truncation reuses the same ``page_metadata.hasNext`` /
    full-page-fallback check as the award search (:func:`_search_truncated`),
    but is CARRIED on the result rather than raised (see
    :class:`SubawardsResult`).
    """

    data = _body_json(payload)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ConnectorError("UPSTREAM_SCHEMA")
    records: list[SubawardRecord] = []
    for row in data["results"]:
        if not isinstance(row, dict):
            raise ConnectorError("UPSTREAM_SCHEMA")
        records.append(
            SubawardRecord(
                subaward_number=_optional_str(row.get("subaward_number")),
                recipient_name=_optional_str(row.get("recipient_name")),
                amount=_to_optional_float(row.get("amount")),
                action_date=_optional_str(row.get("action_date")),
                description=_optional_str(row.get("description")),
            )
        )
    return SubawardsResult(
        award_generated_internal_id=str(award_generated_internal_id),
        records=tuple(records),
        truncated=_search_truncated(payload, limit=limit),
        source_url=payload.source_uri,
        retrieved_at=payload.retrieved_at.isoformat(),
    )


def pull_subawards(
    generated_internal_id: str,
    *,
    limit: int = DEFAULT_SUBAWARDS_LIMIT,
    clock: Callable[[], datetime] = utc_now,
    opener: Any | None = None,
) -> SubawardsResult:
    """Retrieve + parse the subawards reported for a resolved award (one POST).

    Any upstream fault propagates as a loud :class:`ConnectorError`; a garbled
    response shape is likewise loud (see :func:`parse_subawards`). A truncated
    result is NOT an error here -- it is carried on the returned result.
    """

    payload = retrieve_subawards(generated_internal_id, limit=limit, clock=clock, opener=opener)
    return parse_subawards(payload, award_generated_internal_id=generated_internal_id, limit=limit)


__all__ = [
    "AwardCandidate",
    "ContractFactsRecord",
    "ContractFactsResolution",
    "DEFAULT_AWARD_SEARCH_LIMIT",
    "DEFAULT_SUBAWARDS_LIMIT",
    "SYNTHETIC_EXAMPLE_PIID",
    "SubawardRecord",
    "SubawardsResult",
    "USASPENDING_API_BASE",
    "award_detail_url",
    "award_search_body",
    "award_search_url",
    "load_synthetic_example_facts",
    "parse_award_candidates",
    "parse_contract_facts",
    "parse_subawards",
    "pull_contract_facts",
    "pull_subawards",
    "retrieve_award_detail",
    "retrieve_award_search",
    "retrieve_subawards",
    "subawards_body",
    "subawards_url",
]
