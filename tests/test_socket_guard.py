"""Prove the offline guarantee: the autouse socket guard blocks all egress.

The guard (in ``conftest.py``) makes any outbound socket connection fail, so no
test in the suite can reach a live host.  The Census connector's ``parse`` step
opens no socket (it is pure), while its ``retrieve`` step is the only network
boundary -- and under the guard that boundary fails loud as a ConnectorError
instead of silently returning empty data.
"""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tens_hq.connectors import (
    ConnectorError,
    RetrievedPayload,
    parse_acs_disability,
    pull_geography_context,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_direct_socket_connect_is_blocked() -> None:
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError):
            connection.connect(("127.0.0.1", 9))
    finally:
        connection.close()


def test_create_connection_is_blocked() -> None:
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", 9), timeout=0.1)


def test_acs_parse_opens_no_socket_under_the_guard() -> None:
    # A pure byte-in parse runs fine while the network is blocked, proving the
    # no-network-in-parser property holds.
    payload = RetrievedPayload(
        body=(FIXTURES / "census_acs_s1810_denver.json").read_bytes(),
        retrieved_at=datetime(2026, 7, 18, 14, 30, tzinfo=timezone.utc),
        source_uri="https://api.census.gov/data/2022/acs/acs5/subject",
    )
    record = parse_acs_disability(
        payload, county="Denver", state="CO", state_fips="08", county_fips="031", year=2022
    )
    assert record.with_disability == 78655


def test_live_retrieve_is_blocked_and_fails_loud() -> None:
    # The retrieve path is the only network step; under the guard it must raise
    # a bounded ConnectorError, never return a silently-empty result.
    with pytest.raises(ConnectorError) as error:
        pull_geography_context("Denver", "CO")
    assert error.value.code in {"UPSTREAM_UNAVAILABLE", "RATE_LIMITED"}
