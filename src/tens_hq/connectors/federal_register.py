"""Federal Register PL add/delete notices connector (A4, roadmap remainder).

Given no analyst input beyond an optional free-text search term, retrieve the
AbilityOne Commission's own Federal Register notice stream: page 1 only,
newest-first, ``per_page=20`` pinned (D1 -- no pagination UI in v1, see
ADR-023). This is a *national notice list*, never a claim about any specific
contract -- the packet section built on top of it (:mod:`tens_hq.pl_activity`)
renders every notice caveat-first and never infers an add/delete
classification beyond what a title itself states.

Design (see :mod:`tens_hq.connectors.api`), mirroring ``census_acs.py`` /
``usaspending.py``:

* ``retrieve_pl_notices`` is the only network step (stdlib ``urllib`` GET).
* ``parse_pl_notices`` is pure and byte-in, coded to the *live-probed*
  Federal Register ``documents.json`` envelope (see below).
* ``pull_pl_notices`` composes the two, exactly like ``pull_geography_context``
  / ``pull_contract_facts``.

Two live-probed facts (2026-07-21) drive this module's shape -- both were
BLOCKER-severity audit corrections against an earlier draft that copied
``census_acs``'s raw f-string URL style, and both are recorded in ADR-023:

1. **The zero-match envelope is SMALL, not just empty-``results``.** A
   legitimate no-match search returns ONLY ``{"count": 0, "description":
   ...}`` -- ``results``, ``total_pages``, and ``next_page_url`` are ABSENT,
   not present-and-empty. The parse contract below is therefore: ``count``
   present-and-int is REQUIRED; ``results`` absent while ``count == 0`` is a
   LEGITIMATE EMPTY result (``records=()``), never a malformed envelope.
   ``ConnectorError("UPSTREAM_SCHEMA")`` is reserved for: ``count``
   missing/non-int/negative, ``results`` absent while ``count != 0`` (an
   envelope that claims a nonempty stream but supplies none), ``results``
   present but not a list, or any result entry that is not an object.
2. **A raw space in the search term is not survivable.** ``urllib.request``
   builds the ``Request`` object fine with an unencoded space in the query
   string, but ``http.client`` raises ``InvalidURL`` -- an ``HTTPException``
   subclass, NOT a ``URLError``/``OSError``/``ValueError`` -- the moment
   ``urlopen`` actually sends the request line. ``http_get``'s catch tuple
   (``api.py``) does not include ``HTTPException``, so an un-encoded term
   would escape as a raw, uncaught exception rather than a bounded
   ``ConnectorError``. ``notices_url`` therefore builds its ENTIRE query
   string through ``urllib.parse.urlencode`` (never an f-string
   interpolation of the term), so a multi-word, bracketed, or Unicode term
   can never reach ``urlopen`` with a raw space or control character in it.

No key, no auth (confirmed live). The agency slug (confirmed via
``/api/v1/agencies``) is the Committee for Purchase From People Who Are
Blind or Severely Disabled -- the AbilityOne Commission's Federal Register
identity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlencode

from .api import RetrievedPayload, http_get
from .base import ConnectorError, utc_now

FEDERAL_REGISTER_API_BASE = "https://www.federalregister.gov/api/v1"
_DOCUMENTS_PATH = "/documents.json"

# Confirmed live via GET /api/v1/agencies (2026-07-21): the AbilityOne
# Commission's Federal Register identity (name "Committee for Purchase From
# People Who Are Blind or Severely Disabled", short_name "CPPBSD").
ABILITYONE_COMMISSION_AGENCY_SLUG = "committee-for-purchase-from-people-who-are-blind-or-severely-disabled"

# D1: page 1 only, pinned, newest-first. No pagination UI in v1 (ADR-023).
PL_NOTICES_PER_PAGE = 20
_NOTICE_TYPE = "NOTICE"
_ORDER = "newest"

# Explicit fields (confirmed live): trims the response to exactly what this
# slice renders, never a fuller document body.
_FIELDS = ("title", "document_number", "publication_date", "html_url", "type")


@dataclass(frozen=True)
class FRNoticeRecord:
    """One Federal Register notice, copied verbatim (byte-in parsed).

    Every field is ``str | None``: a field the upstream response omits or
    sends as ``null`` becomes ``None`` here (never a fabricated placeholder);
    the renderer (:mod:`tens_hq.pl_activity`) turns ``None`` into an honest
    "Not reported" at render time, the same discipline every other connector
    record in this codebase holds. ``notice_type`` is the FR ``type`` field
    (e.g. ``"Notice"``) -- present so a title can be read alongside its own
    document type, never used here to classify add-vs-delete.
    """

    title: str | None
    document_number: str | None
    publication_date: str | None
    html_url: str | None
    notice_type: str | None


@dataclass(frozen=True)
class PLNoticesResult:
    """One page-1 pull of the Commission's Federal Register notice stream.

    ``truncated`` is ``count_total > len(records)`` -- structurally, this can
    only be ``True`` when ``count_total >= 1`` (a nonnegative ``len(records)``
    can never be exceeded by ``0``), so a ``count_total == 0`` result can
    never render "showing the newest 20 of 0" (§1.3's pinned invariant holds
    by construction, not by a separate guard). ``search_term`` is the
    analyst's cleaned (stripped, non-blank) term, or ``None`` when no term
    was supplied -- the same "blank canonicalizes to no query" discipline
    ``pl_match.py`` already holds for its own service-type query.
    """

    records: tuple[FRNoticeRecord, ...]
    count_total: int
    truncated: bool
    search_term: str | None
    source_url: str
    retrieved_at: str


def _clean_term(value: str | None) -> str | None:
    """Blank/whitespace-only/``None`` all canonicalize to ``None`` (no query)."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def notices_url(term: str | None = None) -> str:
    """Build the ``documents.json`` request URL (D1: page 1, per_page=20, newest).

    The ENTIRE query string is built through :func:`urllib.parse.urlencode`
    (never an f-string interpolation of ``term``) -- a raw space in the term
    is the audit-BLOCKER live-probed failure mode this exists to prevent (see
    the module docstring). ``safe="[]"`` keeps the Federal Register's
    documented ``conditions[agencies][]``-style bracket syntax human-readable
    in the built URL; it does not affect what gets percent-encoded (a space,
    a bracket inside the *term itself*, and non-ASCII characters are all
    still safely encoded either way).
    """

    cleaned = _clean_term(term)
    params: list[tuple[str, str]] = [
        ("conditions[type][]", _NOTICE_TYPE),
        ("conditions[agencies][]", ABILITYONE_COMMISSION_AGENCY_SLUG),
        ("per_page", str(PL_NOTICES_PER_PAGE)),
        ("order", _ORDER),
    ]
    if cleaned:
        params.append(("conditions[term]", cleaned))
    params.extend(("fields[]", field) for field in _FIELDS)
    query = urlencode(params, safe="[]")
    return f"{FEDERAL_REGISTER_API_BASE}{_DOCUMENTS_PATH}?{query}"


def retrieve_pl_notices(
    term: str | None = None,
    *,
    clock: Callable[[], datetime] = utc_now,
    opener: Any | None = None,
) -> RetrievedPayload:
    """Network step: GET the Commission's Federal Register notices (page 1)."""

    return http_get(notices_url(term), clock=clock, opener=opener)


def _body_json(payload: RetrievedPayload | bytes) -> Any:
    body = payload.body if isinstance(payload, RetrievedPayload) else bytes(payload)
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise ConnectorError("UPSTREAM_SCHEMA") from None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text != "" else None


def parse_pl_notices(payload: RetrievedPayload, *, term: str | None = None) -> PLNoticesResult:
    """Map a ``documents.json`` response to a cited :class:`PLNoticesResult`.

    Pure and byte-in. Coded to the two live-probed envelope shapes (module
    docstring): a non-empty envelope carries a list ``results``; the
    legitimate zero-match envelope carries ONLY ``count`` (``0``) and
    ``description`` -- ``results`` absent there is NOT a schema fault. Any
    other deviation (missing/non-int/negative ``count``; ``results`` absent
    while ``count != 0``; ``results`` present but not a list; a result entry
    that is not an object) fails loud with ``ConnectorError("UPSTREAM_SCHEMA")``
    and never echoes the response body.
    """

    data = _body_json(payload)
    if not isinstance(data, dict):
        raise ConnectorError("UPSTREAM_SCHEMA")
    count = data.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ConnectorError("UPSTREAM_SCHEMA")
    raw_results = data.get("results")
    if raw_results is None:
        # The live-probed zero-match envelope: legitimate ONLY when count==0.
        if count != 0:
            raise ConnectorError("UPSTREAM_SCHEMA")
        records: tuple[FRNoticeRecord, ...] = ()
    else:
        if not isinstance(raw_results, list):
            raise ConnectorError("UPSTREAM_SCHEMA")
        parsed: list[FRNoticeRecord] = []
        for row in raw_results:
            if not isinstance(row, dict):
                raise ConnectorError("UPSTREAM_SCHEMA")
            parsed.append(
                FRNoticeRecord(
                    title=_optional_str(row.get("title")),
                    document_number=_optional_str(row.get("document_number")),
                    publication_date=_optional_str(row.get("publication_date")),
                    html_url=_optional_str(row.get("html_url")),
                    notice_type=_optional_str(row.get("type")),
                )
            )
        records = tuple(parsed)
    return PLNoticesResult(
        records=records,
        count_total=count,
        truncated=count > len(records),
        search_term=_clean_term(term),
        source_url=payload.source_uri,
        retrieved_at=payload.retrieved_at.isoformat(),
    )


def pull_pl_notices(
    term: str | None = None,
    *,
    clock: Callable[[], datetime] = utc_now,
    opener: Any | None = None,
) -> PLNoticesResult:
    """Retrieve + parse the Commission's Federal Register notices (one GET).

    Orchestration only, mirroring ``pull_geography_context`` /
    ``pull_contract_facts``. Any upstream fault (rate limit, transport
    failure, oversized body, a malformed envelope) propagates as a loud
    :class:`ConnectorError`; a zero-match search is NOT an error -- it
    returns a real, empty :class:`PLNoticesResult`.
    """

    payload = retrieve_pl_notices(term, clock=clock, opener=opener)
    return parse_pl_notices(payload, term=term)


__all__ = [
    "ABILITYONE_COMMISSION_AGENCY_SLUG",
    "FEDERAL_REGISTER_API_BASE",
    "FRNoticeRecord",
    "PL_NOTICES_PER_PAGE",
    "PLNoticesResult",
    "notices_url",
    "parse_pl_notices",
    "pull_pl_notices",
    "retrieve_pl_notices",
]
