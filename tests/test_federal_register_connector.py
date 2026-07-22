"""Offline tests for the Federal Register PL-notices connector (A4).

Every network step is driven through an injected fake opener, or (for the
socket-guard test) left to the autouse conftest guard; no test opens a real
socket. Fixtures are hand-authored but structurally faithful to the
live-probed Federal Register ``documents.json`` envelope shapes.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tens_hq.connectors import (
    FRNoticeRecord,
    PLNoticesResult,
    RetrievedPayload,
    SourceKind,
    WORKBOOK_SOURCE_KINDS,
    notices_url,
    parse_pl_notices,
    pull_pl_notices,
)
from tens_hq.connectors.base import ConnectorError

FIXTURES = Path(__file__).resolve().parent / "fixtures"
_RETRIEVED_AT = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
_SOURCE_URL = "https://www.federalregister.gov/api/v1/documents.json?per_page=20"


def _fx(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _payload(body: bytes, *, source_uri: str = _SOURCE_URL) -> RetrievedPayload:
    return RetrievedPayload(body=body, retrieved_at=_RETRIEVED_AT, source_uri=source_uri)


# --- notices_url: term encoding (audit BLOCKER) -----------------------------


def test_notices_url_has_no_term_by_default() -> None:
    url = notices_url()
    assert "conditions%5Bterm%5D" not in url
    assert "conditions[term]" not in url
    assert "per_page=20" in url
    assert "order=newest" in url
    assert "conditions%5Btype%5D%5B%5D=NOTICE" in url or "conditions[type][]=NOTICE" in url
    assert "committee-for-purchase-from-people-who-are-blind-or-severely-disabled" in url


def test_notices_url_blank_and_none_term_both_omit_the_term_param() -> None:
    for blank in (None, "", "   "):
        url = notices_url(blank)
        assert "conditions" in url  # sanity: still a real URL
        assert "conditions%5Bterm%5D" not in url
        assert "conditions[term]" not in url


@pytest.mark.parametrize(
    "term",
    [
        "procurement list additions",
        "[bracketed] term",
        "café société",
        "a\tterm\nwith\rcontrol\x00chars",
    ],
)
def test_notices_url_multiword_bracket_unicode_terms_build_valid_urls_without_raw_space_or_control_chars(
    term: str,
) -> None:
    url = notices_url(term)
    assert url.startswith("https://www.federalregister.gov/api/v1/documents.json?")
    # The audit BLOCKER this exists to prevent: a raw space (or any control
    # character) in the built URL would raise http.client.InvalidURL the
    # moment urlopen tries to send it -- an exception http_get's catch tuple
    # does not cover (see the module docstring / ADR-023).
    assert " " not in url
    assert all(ord(ch) >= 0x20 for ch in url)
    assert all(ch.isascii() for ch in url)


def test_notices_url_term_is_percent_or_plus_encoded_not_raw_interpolated() -> None:
    url = notices_url("procurement list")
    assert "procurement+list" in url or "procurement%20list" in url
    assert "procurement list" not in url


# --- parse_pl_notices: non-empty envelope -----------------------------------


def test_parse_pl_notices_non_empty_page_builds_records_with_provenance() -> None:
    result = parse_pl_notices(_payload(_fx("federal_register_notices_page.json")), term=None)
    assert isinstance(result, PLNoticesResult)
    assert result.count_total == 3070
    assert len(result.records) == 3
    assert result.truncated is True  # count (3070) > len(records) (3)
    assert result.search_term is None
    assert result.source_url == _SOURCE_URL
    assert result.retrieved_at == _RETRIEVED_AT.isoformat()
    first = result.records[0]
    assert isinstance(first, FRNoticeRecord)
    assert first.title == "Procurement List; Proposed Deletions"
    assert first.document_number == "2026-14305"
    assert first.publication_date == "2026-07-16"
    assert first.notice_type == "Notice"
    assert "2026-14305" in first.html_url


def test_parse_pl_notices_retains_non_pl_notices_without_silent_filtering() -> None:
    # The stream also carries non-PL notices (meetings, etc.); the parser
    # must never drop one silently -- that judgment belongs to the analyst,
    # never this connector (brief §2 / D3).
    result = parse_pl_notices(_payload(_fx("federal_register_notices_small.json")), term=None)
    assert result.count_total == 2
    assert len(result.records) == 2
    assert result.truncated is False  # 0 < count(2) <= 20
    titles = [r.title for r in result.records]
    assert "Sunshine Act Meeting" in titles
    assert "Procurement List; Additions" in titles


def test_parse_pl_notices_carries_the_cleaned_search_term() -> None:
    result = parse_pl_notices(
        _payload(_fx("federal_register_notices_small.json")), term="  Procurement List  "
    )
    assert result.search_term == "Procurement List"
    # Blank/whitespace-only term canonicalizes to no query (None).
    result_blank = parse_pl_notices(_payload(_fx("federal_register_notices_small.json")), term="   ")
    assert result_blank.search_term is None


# --- parse_pl_notices: the live-probed ZERO-MATCH envelope (audit BLOCKER) --


def test_parse_pl_notices_zero_match_envelope_is_a_legitimate_empty_result() -> None:
    # The live-probed shape: ONLY {"count": 0, "description": ...} -- results,
    # total_pages, next_page_url are ALL ABSENT. This must NOT raise; it is a
    # real, honest empty result, never a malformed-envelope ConnectorError.
    result = parse_pl_notices(
        _payload(_fx("federal_register_notices_zero_match.json")), term="zzz-no-such-term-zzz"
    )
    assert result.count_total == 0
    assert result.records == ()
    assert result.truncated is False  # structurally guaranteed: 0 > 0 is False
    assert result.search_term == "zzz-no-such-term-zzz"


def test_parse_pl_notices_zero_match_never_reports_truncated() -> None:
    # Pins §1.3's "never 'newest 20 of 0'" invariant directly against the
    # connector's own truncated flag, independent of any renderer.
    body = json.dumps({"count": 0, "description": "x"}).encode("utf-8")
    result = parse_pl_notices(_payload(body), term=None)
    assert result.truncated is False


# --- parse_pl_notices: malformed envelopes fail loud ------------------------


def test_parse_pl_notices_fails_loud_on_non_json_body() -> None:
    with pytest.raises(ConnectorError) as error:
        parse_pl_notices(_payload(b"{not json"))
    assert error.value.code == "UPSTREAM_SCHEMA"


def test_parse_pl_notices_fails_loud_on_non_object_body() -> None:
    body = json.dumps([1, 2, 3]).encode("utf-8")
    with pytest.raises(ConnectorError) as error:
        parse_pl_notices(_payload(body))
    assert error.value.code == "UPSTREAM_SCHEMA"


def test_parse_pl_notices_fails_loud_on_missing_count() -> None:
    body = json.dumps({"results": []}).encode("utf-8")
    with pytest.raises(ConnectorError) as error:
        parse_pl_notices(_payload(body))
    assert error.value.code == "UPSTREAM_SCHEMA"


def test_parse_pl_notices_fails_loud_on_non_int_count() -> None:
    body = json.dumps({"count": "3", "results": []}).encode("utf-8")
    with pytest.raises(ConnectorError) as error:
        parse_pl_notices(_payload(body))
    assert error.value.code == "UPSTREAM_SCHEMA"


def test_parse_pl_notices_fails_loud_on_bool_count() -> None:
    # bool is a subclass of int in Python; must not silently pass as a count.
    body = json.dumps({"count": True, "results": []}).encode("utf-8")
    with pytest.raises(ConnectorError) as error:
        parse_pl_notices(_payload(body))
    assert error.value.code == "UPSTREAM_SCHEMA"


def test_parse_pl_notices_fails_loud_on_negative_count() -> None:
    body = json.dumps({"count": -1, "results": []}).encode("utf-8")
    with pytest.raises(ConnectorError) as error:
        parse_pl_notices(_payload(body))
    assert error.value.code == "UPSTREAM_SCHEMA"


def test_parse_pl_notices_fails_loud_on_results_absent_while_count_nonzero() -> None:
    # An envelope that CLAIMS a nonempty stream but supplies no results is a
    # garbled shape, not the legitimate zero-match envelope (that one is
    # count==0 specifically).
    body = json.dumps({"count": 5, "description": "x"}).encode("utf-8")
    with pytest.raises(ConnectorError) as error:
        parse_pl_notices(_payload(body))
    assert error.value.code == "UPSTREAM_SCHEMA"


def test_parse_pl_notices_fails_loud_on_results_not_a_list() -> None:
    body = json.dumps({"count": 1, "results": {"oops": "dict"}}).encode("utf-8")
    with pytest.raises(ConnectorError) as error:
        parse_pl_notices(_payload(body))
    assert error.value.code == "UPSTREAM_SCHEMA"


def test_parse_pl_notices_fails_loud_on_non_object_result_entry() -> None:
    body = json.dumps({"count": 1, "results": ["not-an-object"]}).encode("utf-8")
    with pytest.raises(ConnectorError) as error:
        parse_pl_notices(_payload(body))
    assert error.value.code == "UPSTREAM_SCHEMA"


def test_parse_pl_notices_missing_record_fields_become_none() -> None:
    body = json.dumps({"count": 1, "results": [{"title": "Only a title"}]}).encode("utf-8")
    result = parse_pl_notices(_payload(body))
    record = result.records[0]
    assert record.title == "Only a title"
    assert record.document_number is None
    assert record.publication_date is None
    assert record.html_url is None
    assert record.notice_type is None


# --- Never echoes the response body or the search term in an error ---------


def test_error_never_echoes_response_body_or_search_term() -> None:
    canary = "TOP-SECRET-CANARY-9f8e7d"
    body = f'{{"count": "not-an-int", "canary": "{canary}"}}'.encode("utf-8")
    with pytest.raises(ConnectorError) as exc:
        parse_pl_notices(_payload(body), term=canary)
    assert canary not in str(exc.value)
    assert canary not in exc.value.public_message


# --- Socket guard / opener wiring -------------------------------------------


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


class _FakeOpener:
    def __init__(self, body: bytes):
        self._body = body

    def open(self, request, timeout=None):  # noqa: ANN001 - mirrors urllib signature
        return _FakeResponse(self._body)


def test_pull_pl_notices_orchestrates_retrieve_and_parse_offline() -> None:
    opener = _FakeOpener(_fx("federal_register_notices_page.json"))
    result = pull_pl_notices("Procurement List", clock=lambda: _RETRIEVED_AT, opener=opener)
    assert result.count_total == 3070
    assert result.truncated is True
    assert result.search_term == "Procurement List"
    assert "documents.json" in result.source_url
    assert result.retrieved_at == _RETRIEVED_AT.isoformat()


def test_no_opener_hits_socket_guard() -> None:
    # Real urllib path with the autouse conftest network block active -> a
    # loud ConnectorError, never a raw, uncaught exception and never a live
    # egress attempt.
    with pytest.raises(ConnectorError):
        pull_pl_notices("procurement list", clock=lambda: _RETRIEVED_AT)


# --- Closed-enum wiring ------------------------------------------------------


def test_federal_register_notices_excluded_from_workbook_kinds() -> None:
    assert SourceKind.FEDERAL_REGISTER_NOTICES not in WORKBOOK_SOURCE_KINDS
    assert SourceKind.FEDERAL_REGISTER_NOTICES.value == "FEDERAL_REGISTER_NOTICES"
