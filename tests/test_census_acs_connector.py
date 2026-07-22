"""Offline tests for the Census ACS geography connector (A1 walking skeleton).

These tests never touch the network.  The parser is exercised against a
hand-authored fixture that matches the documented Census ACS JSON shape
(a header row followed by value rows), and the network error mapping is
exercised through an injected fake opener.  The connector's ``retrieve`` step
is the only place a socket is opened; ``parse`` is pure and byte-in.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tens_hq.connectors import (
    Assurance,
    ConnectorError,
    GeographyRecord,
    RetrievedPayload,
    STATE_FIPS,
    SourceKind,
    SourceMetadata,
    http_get,
    parse_acs_disability,
    parse_county_fips,
    pull_geography_context,
    retrieve_county_index,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
_ACS_URL = (
    "https://api.census.gov/data/2022/acs/acs5/subject"
    "?get=NAME,S1810_C01_001E,S1810_C02_001E,S1810_C03_001E&for=county:031&in=state:08"
)
_RETRIEVED_AT = datetime(2026, 7, 18, 14, 30, tzinfo=timezone.utc)


def _disability_payload() -> RetrievedPayload:
    body = (FIXTURES / "census_acs_s1810_denver.json").read_bytes()
    return RetrievedPayload(body=body, retrieved_at=_RETRIEVED_AT, source_uri=_ACS_URL)


def _county_payload() -> RetrievedPayload:
    body = (FIXTURES / "census_county_fips_colorado.json").read_bytes()
    return RetrievedPayload(
        body=body,
        retrieved_at=_RETRIEVED_AT,
        source_uri="https://api.census.gov/data/2022/acs/acs5?get=NAME&for=county:*&in=state:08",
    )


def test_parse_acs_disability_builds_geography_record_with_values_and_provenance() -> None:
    record = parse_acs_disability(
        _disability_payload(),
        county="Denver",
        state="CO",
        state_fips="08",
        county_fips="031",
        year=2022,
    )
    assert isinstance(record, GeographyRecord)
    # Values come straight from the documented ACS S1810 columns.
    assert record.total_population == 705576
    assert record.with_disability == 78655
    assert record.disability_percent == pytest.approx(11.1)
    assert record.county_fips == "031"
    assert record.state_fips == "08"
    # Provenance is captured: source URL, retrieval time, and survey vintage.
    assert record.source_url == _ACS_URL
    assert record.retrieved_at == _RETRIEVED_AT.isoformat()
    assert record.acs_vintage_year == 2022
    assert "S1810" in record.acs_survey


def test_parse_county_fips_resolves_county_to_documented_fips() -> None:
    resolved = parse_county_fips(_county_payload(), county="Denver", state="CO")
    assert resolved.state_fips == "08"
    assert resolved.county_fips == "031"
    # A trailing "County" and casing are not substantive differences.
    assert parse_county_fips(_county_payload(), county="denver county", state="CO").county_fips == "031"


def test_parse_county_fips_fails_loud_on_unknown_county() -> None:
    with pytest.raises(ConnectorError) as error:
        parse_county_fips(_county_payload(), county="Nowhere", state="CO")
    assert error.value.code == "GEOGRAPHY_NOT_FOUND"


def test_parse_acs_disability_fails_closed_on_malformed_response() -> None:
    bad = RetrievedPayload(body=b"{not json", retrieved_at=_RETRIEVED_AT, source_uri=_ACS_URL)
    with pytest.raises(ConnectorError) as error:
        parse_acs_disability(bad, county="Denver", state="CO", state_fips="08", county_fips="031", year=2022)
    assert error.value.code == "UPSTREAM_SCHEMA"


def test_state_fips_lookup_is_present_for_states() -> None:
    assert STATE_FIPS["CO"] == "08"
    assert STATE_FIPS["CA"] == "06"


def test_source_metadata_accepts_api_retrieved_assurance() -> None:
    # The closed enum now carries an API provenance value, and __post_init__ no
    # longer rejects everything that is not USER_ATTESTED.
    metadata = SourceMetadata(SourceKind.CENSUS_ACS, assurance=Assurance.API_RETRIEVED)
    assert metadata.provenance_assurance == "API_RETRIEVED"
    assert metadata.source_kind is SourceKind.CENSUS_ACS
    # A workbook's default remains user-attested and unchanged.
    assert SourceMetadata(SourceKind.NIB_NPA).provenance_assurance == "USER_ATTESTED"


def test_source_metadata_still_fails_closed_on_unknown_assurance() -> None:
    with pytest.raises(ValueError):
        SourceMetadata(SourceKind.CENSUS_ACS, assurance="SELF_SIGNED")


class _RaisingOpener:
    """A fake urllib opener that raises on open (no real network involved)."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def open(self, request, timeout=None):  # noqa: ANN001 - mirrors urllib signature
        raise self._exc


def test_http_get_maps_rate_limit_to_connector_error() -> None:
    import urllib.error

    opener = _RaisingOpener(urllib.error.HTTPError(_ACS_URL, 429, "Too Many Requests", {}, None))
    with pytest.raises(ConnectorError) as error:
        http_get(_ACS_URL, opener=opener)
    assert error.value.code == "RATE_LIMITED"


def test_http_get_maps_upstream_failure_to_connector_error() -> None:
    import urllib.error

    opener = _RaisingOpener(urllib.error.URLError("connection refused"))
    with pytest.raises(ConnectorError) as error:
        http_get(_ACS_URL, opener=opener)
    assert error.value.code == "UPSTREAM_UNAVAILABLE"

    server_error = _RaisingOpener(urllib.error.HTTPError(_ACS_URL, 503, "Service Unavailable", {}, None))
    with pytest.raises(ConnectorError) as error:
        http_get(_ACS_URL, opener=server_error)
    assert error.value.code == "UPSTREAM_UNAVAILABLE"


class _FakeResponse:
    """A minimal stream-like stand-in for an ``http.client`` response.

    ``read(amt)`` mirrors the real streaming signature so the connector's
    bounded, chunked read exercises the same code path it will in production,
    and ``headers`` lets a test advertise a (possibly lying) ``Content-Length``.
    """

    def __init__(self, body: bytes, *, headers: dict[str, str] | None = None, status: int = 200) -> None:
        self._buffer = io.BytesIO(body)
        self.status = status
        self.headers = headers or {}

    def read(self, amt: int = -1) -> bytes:
        return self._buffer.read(amt)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc) -> bool:
        return False


class _FakeOpener:
    """Serves the two fixtures by URL substring -- no socket is ever opened."""

    def __init__(self, mapping: dict[str, bytes], *, headers: dict[str, str] | None = None) -> None:
        self._mapping = mapping
        self._headers = headers

    def open(self, request, timeout=None):  # noqa: ANN001 - mirrors urllib signature
        url = request.full_url
        for needle, body in self._mapping.items():
            if needle in url:
                return _FakeResponse(body, headers=self._headers)
        raise AssertionError(f"unexpected url: {url}")


def test_http_get_rejects_streamed_oversized_body() -> None:
    # A misbehaving/spoofed upstream streams far more than the cap. The bounded
    # chunked read must fail loud (UPSTREAM_TOO_LARGE) rather than buffer it all
    # into memory, even when no Content-Length is advertised.
    oversized = b"x" * 4096
    opener = _FakeOpener({"acs5": oversized})
    with pytest.raises(ConnectorError) as error:
        http_get(_ACS_URL, opener=opener, max_bytes=1024)
    assert error.value.code == "UPSTREAM_TOO_LARGE"


def test_http_get_rejects_oversized_content_length_before_read() -> None:
    # A declared Content-Length over the cap is rejected up front, even when the
    # body that follows is tiny (a lying header must not slip through).
    opener = _FakeOpener({"acs5": b"{}"}, headers={"Content-Length": "999999"})
    with pytest.raises(ConnectorError) as error:
        http_get(_ACS_URL, opener=opener, max_bytes=1024)
    assert error.value.code == "UPSTREAM_TOO_LARGE"


def test_http_get_allows_body_within_cap() -> None:
    # A normal, in-cap body still returns a payload; the cap is a safety bound,
    # not a functional limit on real ACS/geocoder responses.
    body = b'[["NAME"],["Denver County, Colorado"]]'
    opener = _FakeOpener({"acs5": body}, headers={"Content-Length": str(len(body))})
    payload = http_get(_ACS_URL, opener=opener, max_bytes=1024)
    assert payload.body == body


def test_pull_geography_context_orchestrates_retrieve_and_parse_offline() -> None:
    # The whole retrieve->parse->retrieve->parse pipeline, driven by an injected
    # opener so it runs fully offline while still proving the wiring.
    opener = _FakeOpener(
        {
            "for=county:*": (FIXTURES / "census_county_fips_colorado.json").read_bytes(),
            "acs5/subject": (FIXTURES / "census_acs_s1810_denver.json").read_bytes(),
        }
    )
    record = pull_geography_context(
        "Denver", "CO", year=2022, clock=lambda: _RETRIEVED_AT, opener=opener
    )
    assert record.county_fips == "031"
    assert record.state_fips == "08"
    assert record.with_disability == 78655
    assert record.disability_percent == pytest.approx(11.1)
    # Provenance flows from the retrieve step into the record.
    assert record.retrieved_at == _RETRIEVED_AT.isoformat()
    assert "acs5/subject" in record.source_url
    assert "S1810" in record.source_url


# --- Census API key: keyed request, keyless citation, actionable failure ----
#
# Observed live 2026-07-22 (real-PIID dry run): api.census.gov returns an
# HTML "Missing Key" page with HTTP 200 for keyless requests. The connector
# must (a) recognize that page and fail with an actionable code instead of
# the generic UPSTREAM_SCHEMA, (b) send the analyst's key on the wire when
# configured, and (c) NEVER let the key reach a cited source URL -- the
# packet and export render source_url verbatim.

_MISSING_KEY_HTML = (
    b"\n<html>\n<head><title>Missing Key</title></head>\n<body><p>A valid "
    b"<em>key</em> must be included with each data API request. You may sign "
    b'up for one <a href="key_signup.html">here</a>.</p></body>\n</html>\n'
)


class _RecordingOpener:
    """Serves fixture bodies by URL substring and records every request URL."""

    def __init__(self, mapping: dict[str, bytes]) -> None:
        self._mapping = mapping
        self.requested_urls: list[str] = []

    def open(self, request, timeout=None):  # noqa: ANN001 - mirrors urllib signature
        url = request.full_url
        self.requested_urls.append(url)
        for needle, body in self._mapping.items():
            if needle in url:
                return _FakeResponse(body, headers={"Content-Length": str(len(body))})
        raise AssertionError(f"unexpected url: {url}")


def test_missing_key_page_maps_to_actionable_error() -> None:
    with pytest.raises(ConnectorError) as error:
        parse_county_fips(_MISSING_KEY_HTML, county="Fairfax", state="VA")
    assert error.value.code == "CENSUS_KEY_REQUIRED"
    assert "TENS_HQ_CENSUS_API_KEY" in str(error.value)


def test_other_html_garbage_still_maps_to_upstream_schema() -> None:
    with pytest.raises(ConnectorError) as error:
        parse_county_fips(b"<html>gateway timeout</html>", county="Fairfax", state="VA")
    assert error.value.code == "UPSTREAM_SCHEMA"


def test_no_key_configured_sends_keyless_request(monkeypatch) -> None:
    monkeypatch.delenv("TENS_HQ_CENSUS_API_KEY", raising=False)
    body = (FIXTURES / "census_county_fips_colorado.json").read_bytes()
    opener = _RecordingOpener({"acs5": body})
    payload = retrieve_county_index("08", opener=opener)
    assert len(opener.requested_urls) == 1
    assert "&key=" not in opener.requested_urls[0]
    assert "&key=" not in payload.source_uri


def test_key_rides_the_wire_but_never_the_citation(monkeypatch) -> None:
    monkeypatch.setenv("TENS_HQ_CENSUS_API_KEY", "SECRETKEY123")
    county_body = (FIXTURES / "census_county_fips_colorado.json").read_bytes()
    subject_body = (FIXTURES / "census_acs_s1810_denver.json").read_bytes()
    opener = _RecordingOpener(
        {"acs5/subject": subject_body, "acs5?get=NAME": county_body}
    )
    record = pull_geography_context("Denver", "CO", opener=opener)
    assert len(opener.requested_urls) == 2
    for url in opener.requested_urls:
        assert "&key=SECRETKEY123" in url
    # The cited URL -- rendered verbatim in the packet and export -- is keyless.
    assert "SECRETKEY123" not in record.source_url
    assert "&key=" not in record.source_url
    assert record.county_name.startswith("Denver County")


def test_key_is_url_quoted_on_the_wire(monkeypatch) -> None:
    monkeypatch.setenv("TENS_HQ_CENSUS_API_KEY", "ab&cd ef")
    body = (FIXTURES / "census_county_fips_colorado.json").read_bytes()
    opener = _RecordingOpener({"acs5": body})
    retrieve_county_index("08", opener=opener)
    assert "&key=ab%26cd%20ef" in opener.requested_urls[0]
