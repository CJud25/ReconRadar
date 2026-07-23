"""Offline tests for the USAspending single-award contract-facts connector.

Every network step is driven through an injected fake opener; no test opens a
socket (the autouse conftest guard would fail it if one tried). Fixtures are
hand-authored but structurally faithful to the confirmed-live API shapes.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path
import urllib.error

import pytest

from tens_hq.connectors import SourceKind, WORKBOOK_SOURCE_KINDS
from tens_hq.connectors.api import http_post
from tens_hq.connectors.base import ConnectorError
from tens_hq.connectors.usaspending import (
    SYNTHETIC_EXAMPLE_PIID,
    load_synthetic_example_facts,
    parse_award_candidates,
    parse_contract_facts,
    parse_subawards,
    pull_contract_facts,
    pull_subawards,
    subawards_body,
    subawards_url,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
_FIXED = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def _fx(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class _FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200, headers=None):
        self._buf = io.BytesIO(body)
        self.status = status
        self.headers = headers or {}

    def read(self, amt: int = -1) -> bytes:
        return self._buf.read(amt)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeUsaOpener:
    """Serves USAspending fixtures offline. search={PIID_UPPER: bytes}, detail={id_substr: bytes}."""

    def __init__(self, *, search=None, detail=None):
        self._search = search or {}
        self._detail = detail or {}

    def open(self, request, timeout=None):
        data = getattr(request, "data", None)
        if data:  # POST search: route by keyword PIID in the JSON body
            payload = json.loads(data.decode("utf-8"))
            kw = payload.get("filters", {}).get("keywords", [])
            piid = (kw[0] if kw else "").strip().upper()
            body = self._search.get(piid)
            if body is None:
                raise AssertionError(f"no search fixture for {piid}")
            return _FakeResponse(body)
        url = request.full_url  # GET detail: route by internal id substring
        for needle, body in self._detail.items():
            if needle in url:
                return _FakeResponse(body)
        raise AssertionError(f"unexpected detail url: {url}")


class _RaisingOpener:
    def __init__(self, exc: Exception):
        self._exc = exc

    def open(self, request, timeout=None):
        raise self._exc


def test_single_exact_candidate() -> None:  # T1
    cands = parse_award_candidates(_fx("usaspending_search_single.json"), piid="47QRAA24D0012")
    assert len(cands) == 1
    assert cands[0].award_id == "47QRAA24D0012"
    assert cands[0].generated_internal_id


def test_piid_is_not_unique_three_candidates() -> None:  # T2
    cands = parse_award_candidates(_fx("usaspending_search_zsmg_multi.json"), piid="ZSMG")
    assert len(cands) == 3
    assert all(c.award_id == "ZSMG" for c in cands)
    assert len({c.generated_internal_id for c in cands}) == 3


def test_exact_filter_drops_superset_match() -> None:  # T3
    cands = parse_award_candidates(_fx("usaspending_search_nomatch.json"), piid="NOPE123")
    assert cands == ()  # the "NOPE1234" superset is not an exact match


def test_key_mapping_null_set_aside() -> None:  # T4
    rec = parse_contract_facts(_payload(_fx("usaspending_award_detail_null_set_aside.json")), piid="ZSMG")
    assert rec.total_obligation == 7112.26
    assert rec.base_and_all_options == 7112.26
    assert rec.subagency_name == "Department of the Army"
    assert rec.extent_competed_code == "A"
    assert rec.set_aside_code is None
    assert rec.number_of_offers_received is None
    assert rec.naics_code == "532411"
    assert rec.psc_code == "V119"
    assert rec.period_potential_end_date == "2019-03-20 00:00:00"  # raw suffix preserved


def test_obligated_distinct_from_ceiling() -> None:  # T5
    rec = parse_contract_facts(_payload(_fx("usaspending_award_detail_set_aside.json")), piid="47QRAA24D0012")
    assert rec.total_obligation == 100000.0
    assert rec.base_and_all_options == 250000.0
    assert rec.total_obligation != rec.base_and_all_options
    assert rec.set_aside_code == "SBA"
    assert rec.extent_competed_code == "D"
    assert rec.number_of_offers_received == 3


def test_description_and_place_of_performance_parse_from_detail_fixture() -> None:
    """The detail parser preserves description and every allowlisted PoP component."""

    rec = parse_contract_facts(
        _payload(_fx("usaspending_award_detail_set_aside.json")),
        piid="47QRAA24D0012",
    )
    assert rec.description == (
        "JOINT ADDITIVE MANUFACTURING MODEL EXCHANGE (JAMMEX) DEVELOPMENT AND SUSTAINMENT"
    )
    assert rec.pop_city_name == "FORT BELVOIR"
    assert rec.pop_county_name == "FAIRFAX"
    assert rec.pop_state_code == "VA"
    assert rec.pop_country_code == "USA"


def test_place_of_performance_absent_preserves_none_components() -> None:
    """An absent PoP block remains four unknown values while the record still parses."""

    rec = parse_contract_facts(
        _payload(_fx("usaspending_award_detail_null_set_aside.json")),
        piid="ZSMG",
    )
    assert rec.pop_city_name is None
    assert rec.pop_county_name is None
    assert rec.pop_state_code is None
    assert rec.pop_country_code is None


def test_place_of_performance_wrong_typed_fails_loud() -> None:
    """A present non-object PoP block is an upstream schema error, never absence."""

    body = json.dumps({"piid": "X", "place_of_performance": ["oops-a-list"]}).encode(
        "utf-8"
    )
    with pytest.raises(ConnectorError) as exc:
        parse_contract_facts(_payload(body), piid="X")
    assert exc.value.code == "UPSTREAM_SCHEMA"


def test_description_absent_preserves_none() -> None:
    """An award detail with no description keeps the fact unknown rather than empty."""

    rec = parse_contract_facts(
        _payload(_fx("usaspending_award_detail_null_set_aside.json")),
        piid="ZSMG",
    )
    assert rec.description is None


def test_potential_end_date_not_strict_parsed() -> None:  # T6
    rec = parse_contract_facts(_payload(_fx("usaspending_award_detail_null_set_aside.json")), piid="ZSMG")
    # Round-trips as the raw string; a future strptime would break this.
    assert rec.period_potential_end_date == "2019-03-20 00:00:00"


def test_pull_resolved_single_match() -> None:  # T7
    opener = _FakeUsaOpener(
        search={"47QRAA24D0012": _fx("usaspending_search_single.json")},
        detail={"47QRAA24D0012": _fx("usaspending_award_detail_set_aside.json")},
    )
    res = pull_contract_facts("47QRAA24D0012", opener=opener, clock=lambda: _FIXED)
    assert res.resolved
    assert res.record.set_aside_code == "SBA"
    assert res.record.retrieved_at == _FIXED.isoformat()


def test_pull_ambiguous_never_fetches_detail() -> None:  # T8
    # No detail fixtures provided: if the connector tried to fetch a detail in the
    # ambiguous state, the fake opener would raise. It must NOT.
    opener = _FakeUsaOpener(search={"ZSMG": _fx("usaspending_search_zsmg_multi.json")})
    res = pull_contract_facts("ZSMG", opener=opener, clock=lambda: _FIXED)
    assert res.ambiguous
    assert res.record is None
    assert len(res.candidates) == 3


def test_pull_single_match_under_truncated_page_fails_loud() -> None:  # T14
    # A lone page-1 exact match under a truncated (hasNext) result set could have
    # a twin on a later page, so the connector must NOT silently auto-resolve it.
    # No detail fixture is supplied: if it wrongly fetched detail, it would raise
    # AssertionError, not the expected AWARD_SEARCH_TRUNCATED.
    opener = _FakeUsaOpener(search={"47QRAA24D0012": _fx("usaspending_search_single_truncated.json")})
    with pytest.raises(ConnectorError) as exc:
        pull_contract_facts("47QRAA24D0012", opener=opener, clock=lambda: _FIXED)
    assert exc.value.code == "AWARD_SEARCH_TRUNCATED"


def test_contract_facts_to_public_payload_round_trips() -> None:
    rec = parse_contract_facts(_payload(_fx("usaspending_award_detail_set_aside.json")), piid="47QRAA24D0012")
    payload = rec.to_public_payload()
    assert payload["total_obligation"] == 100000.0
    assert payload["base_and_all_options"] == 250000.0
    assert payload["set_aside_code"] == "SBA"
    assert payload["subagency_name"] == "Public Buildings Service"
    assert set(payload) == set(rec.__dataclass_fields__)


def test_pull_zero_match_is_loud_not_found() -> None:  # T9
    opener = _FakeUsaOpener(search={"NOPE123": _fx("usaspending_search_nomatch.json")})
    with pytest.raises(ConnectorError) as exc:
        pull_contract_facts("NOPE123", opener=opener, clock=lambda: _FIXED)
    assert exc.value.code == "AWARD_NOT_FOUND"


def test_pull_direct_internal_id_skips_search() -> None:  # T10
    # Only a detail fixture is provided; the analyst-picked path must not search.
    opener = _FakeUsaOpener(detail={"HTC71114DR027": _fx("usaspending_award_detail_null_set_aside.json")})
    res = pull_contract_facts(
        "ZSMG",
        generated_internal_id="CONT_AWD_ZSMG_9700_HTC71114DR027_9700",
        opener=opener,
        clock=lambda: _FIXED,
    )
    assert res.resolved
    assert res.record.set_aside_code is None


def test_http_post_error_mapping() -> None:  # T11
    http_error = urllib.error.HTTPError("http://x", 429, "rate", {}, None)
    with pytest.raises(ConnectorError) as rate:
        http_post("http://x", b"{}", opener=_RaisingOpener(http_error), clock=lambda: _FIXED)
    assert rate.value.code == "RATE_LIMITED"
    with pytest.raises(ConnectorError) as down:
        http_post("http://x", b"{}", opener=_RaisingOpener(urllib.error.URLError("boom")), clock=lambda: _FIXED)
    assert down.value.code == "UPSTREAM_UNAVAILABLE"


def test_schema_failures_are_loud() -> None:  # T12
    with pytest.raises(ConnectorError) as e1:
        parse_contract_facts(_payload(b"{not json"), piid="X")
    assert e1.value.code == "UPSTREAM_SCHEMA"
    with pytest.raises(ConnectorError) as e2:
        parse_award_candidates(b'{"no_results": true}', piid="X")
    assert e2.value.code == "UPSTREAM_SCHEMA"


def test_wrong_typed_nested_block_fails_loud() -> None:
    # A garbled shape (a nested block of the wrong TYPE, not merely absent) fails
    # loud with ConnectorError, never a raw AttributeError.
    body = json.dumps({"piid": "X", "period_of_performance": ["oops-a-list"]}).encode("utf-8")
    with pytest.raises(ConnectorError) as exc:
        parse_contract_facts(_payload(body), piid="X")
    assert exc.value.code == "UPSTREAM_SCHEMA"


def test_no_opener_hits_socket_guard() -> None:  # T13
    # Real urllib path with the autouse network block active -> loud, no egress.
    with pytest.raises(ConnectorError):
        pull_contract_facts("ZSMG", clock=lambda: _FIXED)


def test_usaspending_award_excluded_from_workbook_kinds() -> None:  # T15
    assert SourceKind.USASPENDING_AWARD not in WORKBOOK_SOURCE_KINDS


# --- helper: wrap fixture bytes as a RetrievedPayload for parse_contract_facts ---
def _payload(body: bytes):
    from tens_hq.connectors.api import RetrievedPayload

    return RetrievedPayload(
        body=body,
        retrieved_at=_FIXED,
        source_uri="https://api.usaspending.gov/api/v2/awards/TEST/",
    )


# --- Recipient business categories (A5) ---------------------------------------


def test_business_categories_present_parses_as_tuple() -> None:
    rec = parse_contract_facts(_payload(_fx("usaspending_award_detail_set_aside.json")), piid="47QRAA24D0012")
    assert rec.recipient_business_categories == ("Category Business", "Small Business")


def test_business_categories_absent_is_none_not_empty_tuple() -> None:
    body = json.dumps({"piid": "X", "recipient": {"recipient_name": "No Categories LLC"}}).encode("utf-8")
    rec = parse_contract_facts(_payload(body), piid="X")
    assert rec.recipient_business_categories is None


def test_business_categories_null_is_none() -> None:
    body = json.dumps({"piid": "X", "recipient": {"business_categories": None}}).encode("utf-8")
    rec = parse_contract_facts(_payload(body), piid="X")
    assert rec.recipient_business_categories is None


def test_business_categories_wrong_typed_fails_loud() -> None:
    body = json.dumps({"piid": "X", "recipient": {"business_categories": "Small Business"}}).encode("utf-8")
    with pytest.raises(ConnectorError) as exc:
        parse_contract_facts(_payload(body), piid="X")
    assert exc.value.code == "UPSTREAM_SCHEMA"


def test_business_categories_in_public_payload() -> None:
    rec = parse_contract_facts(_payload(_fx("usaspending_award_detail_set_aside.json")), piid="47QRAA24D0012")
    payload = rec.to_public_payload()
    assert payload["recipient_business_categories"] == ("Category Business", "Small Business")
    assert set(payload) == set(rec.__dataclass_fields__)


# --- Subawards retrieval (A5 teaming-posture evidence) ------------------------


class _FakeSubawardsOpener:
    """Serves subawards fixtures offline, routed by ``award_id`` in the POST body."""

    def __init__(self, *, by_award_id=None):
        self._by_award_id = by_award_id or {}

    def open(self, request, timeout=None):
        data = getattr(request, "data", None)
        payload = json.loads(data.decode("utf-8"))
        award_id = payload.get("award_id")
        body = self._by_award_id.get(award_id)
        if body is None:
            raise AssertionError(f"no subawards fixture for award_id {award_id!r}")
        return _FakeResponse(body)


def test_subawards_body_shape() -> None:
    body = subawards_body("CONT_AWD_X", limit=100)
    assert body == {
        "award_id": "CONT_AWD_X",
        "page": 1,
        "limit": 100,
        "sort": "subaward_number",
        "order": "desc",
    }
    assert subawards_url() == "https://api.usaspending.gov/api/v2/subawards/"


def test_subawards_happy_path_parses_records() -> None:
    result = parse_subawards(
        _payload(_fx("usaspending_subawards_page.json")), award_generated_internal_id="CONT_AWD_X"
    )
    assert result.award_generated_internal_id == "CONT_AWD_X"
    assert len(result.records) == 2
    assert result.records[0].recipient_name == "ExampleWorks Janitorial Sub LLC"
    assert result.records[0].amount == 45250.00
    assert result.truncated is False


def test_subawards_empty_results_is_not_an_error() -> None:
    result = parse_subawards(
        _payload(_fx("usaspending_subawards_empty.json")), award_generated_internal_id="CONT_AWD_X"
    )
    assert result.records == ()
    assert result.truncated is False


def test_subawards_null_fields_stay_none() -> None:
    result = parse_subawards(
        _payload(_fx("usaspending_subawards_null_fields.json")), award_generated_internal_id="CONT_AWD_X"
    )
    assert len(result.records) == 1
    row = result.records[0]
    assert row.subaward_number is None
    assert row.recipient_name is None
    assert row.amount is None
    assert row.action_date is None
    assert row.description is None


def test_subawards_truncated_via_has_next() -> None:
    result = parse_subawards(
        _payload(_fx("usaspending_subawards_truncated.json")), award_generated_internal_id="CONT_AWD_X"
    )
    assert result.truncated is True
    assert len(result.records) == 1  # still-honest partial evidence, not discarded


def test_subawards_truncated_via_full_page_fallback() -> None:
    # No page_metadata at all: falls back to "len(results) >= limit". Using a
    # small limit=1 keeps the fixture tiny while exercising the same fallback
    # path already covered for award search.
    body = json.dumps(
        {"results": [{"subaward_number": "1", "recipient_name": "A", "amount": 1.0, "action_date": "2025-01-01", "description": "d"}]}
    ).encode("utf-8")
    result = parse_subawards(_payload(body), award_generated_internal_id="CONT_AWD_X", limit=1)
    assert result.truncated is True


def test_subawards_results_not_a_list_fails_loud() -> None:
    body = json.dumps({"results": "not-a-list"}).encode("utf-8")
    with pytest.raises(ConnectorError) as exc:
        parse_subawards(_payload(body), award_generated_internal_id="CONT_AWD_X")
    assert exc.value.code == "UPSTREAM_SCHEMA"


def test_subawards_row_not_a_dict_fails_loud() -> None:
    body = json.dumps({"results": ["not-a-dict"]}).encode("utf-8")
    with pytest.raises(ConnectorError) as exc:
        parse_subawards(_payload(body), award_generated_internal_id="CONT_AWD_X")
    assert exc.value.code == "UPSTREAM_SCHEMA"


def test_subawards_non_numeric_amount_fails_loud() -> None:
    body = json.dumps(
        {"results": [{"subaward_number": "1", "recipient_name": "A", "amount": "not-a-number", "action_date": None, "description": None}]}
    ).encode("utf-8")
    with pytest.raises(ConnectorError) as exc:
        parse_subawards(_payload(body), award_generated_internal_id="CONT_AWD_X")
    assert exc.value.code == "UPSTREAM_SCHEMA"


def test_subawards_garbled_body_fails_loud() -> None:
    with pytest.raises(ConnectorError) as exc:
        parse_subawards(_payload(b"{not json"), award_generated_internal_id="CONT_AWD_X")
    assert exc.value.code == "UPSTREAM_SCHEMA"


def test_pull_subawards_wires_retrieve_and_parse() -> None:
    opener = _FakeSubawardsOpener(by_award_id={"CONT_AWD_X": _fx("usaspending_subawards_page.json")})
    result = pull_subawards("CONT_AWD_X", opener=opener, clock=lambda: _FIXED)
    assert result.award_generated_internal_id == "CONT_AWD_X"
    assert len(result.records) == 2
    assert result.retrieved_at == _FIXED.isoformat()
    assert result.source_url == subawards_url()


def test_pull_subawards_no_opener_hits_socket_guard() -> None:
    # Real urllib path with the autouse network block active -> loud, no egress.
    with pytest.raises(ConnectorError):
        pull_subawards("CONT_AWD_X", clock=lambda: _FIXED)


def test_usaspending_subaward_excluded_from_workbook_kinds() -> None:
    assert SourceKind.USASPENDING_SUBAWARD not in WORKBOOK_SOURCE_KINDS


# --- Offline SYNTHETIC-example facts (ADR-025) ----------------------------


def test_load_synthetic_example_facts_is_resolved_and_honestly_labeled() -> None:
    # No opener/clock involved -- this reads a bundled file, never a socket
    # (the autouse socket guard would fail this test if it tried).
    resolution = load_synthetic_example_facts()
    assert resolution.resolved
    assert resolution.piid == SYNTHETIC_EXAMPLE_PIID
    record = resolution.record
    assert record.synthetic_example is True
    assert record.piid == SYNTHETIC_EXAMPLE_PIID
    # Obligated must stay distinct from the ceiling, same discipline as a
    # real record (never coerced/collapsed to a single figure).
    assert record.total_obligation != record.base_and_all_options
    assert record.total_obligation is not None
    assert record.base_and_all_options is not None
    # Never a live USAspending URL -- the honesty guarantee this whole ADR
    # exists to keep.
    assert "usaspending.gov" not in record.source_url
    assert "api.usaspending" not in record.source_url


def test_load_synthetic_example_facts_never_claims_live_via_to_public_payload() -> None:
    payload = load_synthetic_example_facts().record.to_public_payload()
    assert payload["synthetic_example"] is True
    assert "usaspending.gov" not in str(payload["source_url"])
