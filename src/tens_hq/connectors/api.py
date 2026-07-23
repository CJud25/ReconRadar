"""Minimal API-retrieval boundary shared by the public API connectors.

The workbook connectors are byte-in only: a caller hands them bytes and no
network is ever touched inside a parser.  The API connectors keep that same
property by splitting the work in two:

* ``retrieve(...)`` performs the network request and returns a
  :class:`RetrievedPayload` (raw bytes plus provenance: retrieval time, source
  URI, upstream status).  This is the *only* place a socket is opened.
* ``parse(payload)`` is pure and byte-in, exactly like the workbook parsers, so
  it stays fully testable offline against a hand-authored fixture.

The HTTP client is the Python standard library (``urllib.request`` + ``json``)
on purpose -- the same stdlib discipline the AbilityOne XLSX reader uses -- so
no third-party HTTP dependency enters the demo runtime.  Any rate-limit or
upstream error is raised as a bounded :class:`ConnectorError`; it is never
turned into a silently-empty result.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, runtime_checkable

from .base import ConnectorError, SourceKind, utc_now

# A short, honest User-Agent identifies the pilot without leaking a machine or
# user identity.  The timeout is deliberately small so a hung upstream fails
# loud rather than blocking a single-user session.
_USER_AGENT = "reconradar/1.0.0 (public-data connector)"
DEFAULT_TIMEOUT_SECONDS = 20.0

# A public ACS/geocoder JSON response is a few kilobytes; this cap is a safety
# bound, not a real payload size.  It mirrors the AbilityOne reader's
# ``DEFAULT_MAX_*`` byte limits so a spoofed or misbehaving upstream that streams
# an unbounded body cannot exhaust memory.  ``http_get`` checks a declared
# Content-Length first and then reads in bounded chunks (see ``_read_bounded``).
DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_READ_CHUNK_BYTES = 65536


@dataclass(frozen=True)
class RetrievedPayload:
    """Raw bytes plus the provenance captured at retrieval time.

    ``body`` is the untouched response body handed to a pure parser.  The other
    fields are the provenance the ledger and cited exports require: when it was
    retrieved, where from, and the upstream status code.
    """

    body: bytes
    retrieved_at: datetime
    source_uri: str
    upstream_status: int = 200


@runtime_checkable
class ApiConnector(Protocol):
    """Protocol for a one-source public API connector.

    ``retrieve`` is the network boundary; ``parse`` is pure.  Keeping them
    separate is what preserves the no-network-in-parser property and the
    offline test story.
    """

    source_kind: SourceKind

    def retrieve(self, query: Any, *, clock: Callable[[], datetime] = utc_now) -> RetrievedPayload:
        ...

    def parse(self, payload: RetrievedPayload) -> Any:
        ...


def _utc(clock: Callable[[], datetime]) -> datetime:
    now = clock()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _read_bounded(response: Any, max_bytes: int) -> bytes:
    """Read a response body into memory without trusting its declared size.

    A misbehaving or spoofed upstream could advertise a small (or no)
    Content-Length and then stream an unbounded body.  We therefore (1) reject a
    declared Content-Length that already exceeds the cap, and (2) read in fixed
    chunks, failing loud the moment the accumulated body crosses ``max_bytes``.
    ``ConnectorError`` is raised outside any ``except ValueError`` so it is never
    reclassified (``ConnectorError`` is a ``ValueError`` subclass).
    """

    headers = getattr(response, "headers", None)
    if headers is not None:
        declared = headers.get("Content-Length")
        if declared is not None:
            try:
                declared_int = int(declared)
            except (TypeError, ValueError):
                # A non-numeric Content-Length is ignored; the chunked read
                # below remains the real bound.
                declared_int = None
            if declared_int is not None and declared_int > max_bytes:
                raise ConnectorError("UPSTREAM_TOO_LARGE")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ConnectorError("UPSTREAM_TOO_LARGE")
        chunks.append(chunk)
    return b"".join(chunks)


def http_get(
    url: str,
    *,
    clock: Callable[[], datetime] = utc_now,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    opener: Any | None = None,
) -> RetrievedPayload:
    """Perform a single stdlib HTTP GET and return a :class:`RetrievedPayload`.

    ``opener`` is an injection seam for tests (any object exposing ``open`` with
    the ``urllib`` signature); production callers leave it ``None`` and get
    ``urllib.request.urlopen``.  HTTP 429 maps to ``RATE_LIMITED``; every other
    transport or 4xx/5xx failure maps to ``UPSTREAM_UNAVAILABLE``.  The body is
    read under a ``max_bytes`` cap (``UPSTREAM_TOO_LARGE`` when exceeded) so an
    unbounded upstream cannot exhaust memory.  Neither the URL nor the response
    body is echoed into the raised message.
    """

    request = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        method="GET",
    )
    open_fn = opener.open if opener is not None else urllib.request.urlopen
    try:
        with open_fn(request, timeout=timeout) as response:
            status = int(getattr(response, "status", None) or getattr(response, "code", 200) or 200)
            body = _read_bounded(response, max_bytes)
    except ConnectorError:
        # A bounded-size failure is already the correct, safe error; do not let
        # the ValueError catch-all below reclassify it as UPSTREAM_UNAVAILABLE.
        raise
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise ConnectorError("RATE_LIMITED") from None
        raise ConnectorError("UPSTREAM_UNAVAILABLE") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        # URLError wraps the blocked/failed socket; OSError covers a raw socket
        # failure; ValueError covers a malformed URL.  All are upstream faults.
        raise ConnectorError("UPSTREAM_UNAVAILABLE") from None
    if status == 429:
        raise ConnectorError("RATE_LIMITED")
    if status >= 400:
        raise ConnectorError("UPSTREAM_UNAVAILABLE")
    return RetrievedPayload(body=bytes(body), retrieved_at=_utc(clock), source_uri=url, upstream_status=status)


def http_post(
    url: str,
    body: bytes,
    *,
    clock: Callable[[], datetime] = utc_now,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    opener: Any | None = None,
    content_type: str = "application/json",
) -> RetrievedPayload:
    """Perform a single stdlib HTTP POST and return a :class:`RetrievedPayload`.

    Mirrors :func:`http_get` exactly (bounded read, ``opener`` injection seam,
    fail-loud error mapping, no URL/body echo) but sends ``body`` bytes with a
    ``Content-Type`` header and ``method="POST"``.  HTTP 429 maps to
    ``RATE_LIMITED``; every other transport or 4xx/5xx fault maps to
    ``UPSTREAM_UNAVAILABLE``; an over-cap body maps to ``UPSTREAM_TOO_LARGE``.
    """

    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
            "Content-Type": content_type,
        },
        method="POST",
    )
    open_fn = opener.open if opener is not None else urllib.request.urlopen
    try:
        with open_fn(request, timeout=timeout) as response:
            status = int(getattr(response, "status", None) or getattr(response, "code", 200) or 200)
            body_out = _read_bounded(response, max_bytes)
    except ConnectorError:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise ConnectorError("RATE_LIMITED") from None
        raise ConnectorError("UPSTREAM_UNAVAILABLE") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ConnectorError("UPSTREAM_UNAVAILABLE") from None
    if status == 429:
        raise ConnectorError("RATE_LIMITED")
    if status >= 400:
        raise ConnectorError("UPSTREAM_UNAVAILABLE")
    return RetrievedPayload(body=bytes(body_out), retrieved_at=_utc(clock), source_uri=url, upstream_status=status)


__all__ = [
    "ApiConnector",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "RetrievedPayload",
    "http_get",
    "http_post",
]
