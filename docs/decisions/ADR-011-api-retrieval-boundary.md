# ADR-011: Public API retrieval is a separate retrieve/parse boundary

## Status

Accepted for the A0.5 / A1 walking skeleton

## Date

2026-07-18

## Context

Through v0.2 every source was an analyst-uploaded workbook: a caller handed the
connector bytes and no socket was ever opened inside the connector layer
(ADR-006). The A1 walking skeleton adds the first *live public API* source — the
Census ACS county disability figure (Subject Table S1810) used only as N4
geography *context* on the Opportunity Recon / cited packet surface. That
introduces two things the workbook contract never had to model: a connector that
opens a network socket, and provenance (`Assurance`) that is established by the
retrieval itself rather than by an analyst attestation over an upload.

AGENTS.md rule #10 requires a decision record for material boundary and schema
changes. Adding a network egress path, two new closed-enum values, and a new
error code is exactly such a change, so it is recorded here rather than left
implicit in the connector code.

Constraints this decision has to respect:

- The offline test guarantee (`tests/conftest.py::_block_network`) must hold —
  the whole suite runs with outbound sockets blocked at the egress boundary.
- No third-party HTTP dependency may enter the demo runtime.
- An upstream failure must fail loud, never degrade to a silently-empty result
  that could read as "no geography found".
- ACS context is public, county-level aggregate data only; it must stay walled
  off from the synthetic planning model and must never carry person-level data
  (ADR-006, AGENTS rules #11–#12).

## Decision

Introduce a small API-retrieval boundary in `connectors/api.py`, parallel to but
distinct from the workbook connectors, with four load-bearing choices.

1. **Split `retrieve()` from `parse()`.** `retrieve(...)` is the *only* place a
   socket is opened; it returns a frozen `RetrievedPayload` (raw `body` bytes
   plus provenance: `retrieved_at`, `source_uri`, `upstream_status`).
   `parse(payload)` is pure and byte-in, exactly like the workbook parsers, so
   it stays fully testable offline against a hand-authored fixture
   (`tests/fixtures/census_acs_s1810_denver.json`). This preserves the
   no-network-in-parser property that made the workbook layer testable.

2. **Standard-library `urllib`, not a new dependency.** `http_get` uses
   `urllib.request` + `json` — the same stdlib discipline the AbilityOne XLSX
   reader uses instead of pulling in a spreadsheet engine. No `requests`/`httpx`
   is added to `requirements.txt`. An injected `opener` seam lets tests drive
   the retrieve path with a fake response and no socket.

3. **Two new closed-enum values, both fail-closed.** `SourceKind.CENSUS_ACS`
   names the API-retrieved geography source; it is deliberately excluded from
   `WORKBOOK_SOURCE_KINDS` so it can never be offered as a workbook upload
   target or routed through the workbook scanner. `Assurance.API_RETRIEVED`
   records provenance established by a connector's own `retrieve` step (server
   response + retrieval timestamp), alongside the existing `USER_ATTESTED`.
   `coerce_assurance` accepts exactly those two and fails closed on anything
   else, with a fixed message that never echoes the offending value.

4. **Fail-loud `ConnectorError` mapping.** Every transport/status outcome maps
   to a bounded, safe `ConnectorError` code from the shared message table:
   HTTP 429 → `RATE_LIMITED`; any other transport or 4xx/5xx fault →
   `UPSTREAM_UNAVAILABLE`; a malformed/unexpected JSON shape or suppressed ACS
   sentinel → `UPSTREAM_SCHEMA`; an unresolvable county/state → `GEOGRAPHY_NOT_FOUND`.
   Neither the URL nor the response body is echoed into the raised message.

### FIX-A: the retrieved body is read under a size cap

`http_get` previously did an unbounded `response.read()`. A spoofed or
misbehaving upstream could advertise a small (or no) `Content-Length` and then
stream an arbitrarily large body, exhausting memory. The read is now bounded,
mirroring the AbilityOne reader's `DEFAULT_MAX_*` byte-limit discipline:

- a new `DEFAULT_MAX_RESPONSE_BYTES` cap (8 MiB — an ACS/geocoder JSON is a few
  kilobytes, so this is a safety bound, not a functional limit), overridable per
  call via `max_bytes`;
- a declared `Content-Length` over the cap is rejected up front, and the body is
  then read in fixed `_READ_CHUNK_BYTES` chunks that fail the moment the
  accumulated size crosses the cap;
- exceeding the cap raises `ConnectorError("UPSTREAM_TOO_LARGE")`, a new code
  added to the `ConnectorError` message table. Because `ConnectorError`
  subclasses `ValueError`, the cap error is raised so it is never reclassified
  by the transport-fault `except (URLError, …, ValueError)` handler (an explicit
  `except ConnectorError: raise` guards the read).

## Alternatives considered

- **Fetch inside a single monolithic connector method (no retrieve/parse
  split):** rejected — it would put a live socket inside the parse path and
  break the offline test guarantee and fixture-based testing that the workbook
  layer relies on.
- **Add `requests`/`httpx`:** rejected — an ergonomic HTTP client is not worth a
  new runtime dependency for one tiny stdlib-shaped GET, and it widens the
  supply-chain surface of a single-user demo.
- **Reuse `Assurance.USER_ATTESTED` for API data:** rejected — it would falsely
  claim a human attested to a machine-retrieved figure and erase the provenance
  distinction the ledger and cited exports depend on.
- **Trust `Content-Length` alone for the size bound:** rejected — a hostile or
  buggy upstream can lie about or omit it; the chunked read is the real bound and
  the header check is only an early-exit optimization.
- **Return an empty record on upstream failure:** rejected — it violates the
  fail-loud rule and would let a transient outage masquerade as a legitimate
  "no data for this geography" answer.

## Consequences

- The connector is coded to the Census API's *documented* JSON shape and verified
  only against hand-authored fixtures; the live endpoint must be verified on the
  first real run (see the repository handoff/caveats). Offline, the suite proves
  the wiring end-to-end via an injected opener.
- ACS context remains public, county-level aggregate data with full provenance
  (source URL + retrieval time + survey vintage) on every `GeographyRecord`; it
  never joins the synthetic planning model and never becomes candidate-supply,
  capacity, or feasibility evidence (ADR-006, ADR-010).
- Any new public API source follows this same shape: a `retrieve` network step
  returning a `RetrievedPayload`, a pure `parse` step, `Assurance.API_RETRIEVED`
  provenance, stdlib transport, and bounded fail-loud `ConnectorError` mapping. A
  materially different transport, auth model, or a non-context (candidate/
  capacity) API source would require a new ADR.
- The `UPSTREAM_TOO_LARGE` cap is exercised by
  `tests/test_census_acs_connector.py` (streamed-oversize and lying-Content-Length
  cases via the fake opener); changing `DEFAULT_MAX_RESPONSE_BYTES` semantics is a
  boundary change that should update those vectors.

> **Update 2026-07-20 (ADR-016):** the Opportunity Recon page named above was
> deleted from the app. ACS geography context renders on the surviving cited
> Opportunity Packet (`bd_page.py`), which this ADR's "cited packet surface"
> language already anticipated.
