"""Offline unit tests for the A2 Radar-handoff intake (pure parse + render).

Covers §4's exact schema contract and §5's exact Origin-section render shape:
valid minimal/full parses, every REQUIRED-field failure, wrong version, wrong
types, null semantics (member-absent vs explicit-null both render the same
honest fallback), unknown-field counting across all three scopes (top level,
``claims``, ``place_of_performance``), the two hard size/length caps,
Markdown-injection escaping in rendered lines, that no parse error ever
echoes uploaded content, negative-offers rejection, and state normalization.
"""

from __future__ import annotations

import json

import pytest

from tens_hq.radar_handoff import (
    MAX_STRING_FIELD_CHARS,
    MAX_UPLOAD_BYTES,
    RADAR_HANDOFF_SCHEMA_VERSION,
    RadarHandoffClaims,
    RadarHandoffError,
    RadarHandoffPlace,
    parse_radar_handoff,
    radar_handoff_lines,
)


def _bytes(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _minimal(**overrides: object) -> dict:
    base = {
        "schema_version": RADAR_HANDOFF_SCHEMA_VERSION,
        "snapshot_date": "2026-07-15",
        "piid": "47QRAA24D0012",
    }
    base.update(overrides)
    return base


def _full(**overrides: object) -> dict:
    base = _minimal(
        radar_source_label="GovConRadar 2.8.0",
        synthetic_sample=True,
        claims={
            "referenced_idv_piid": "47QSMD20D0001",
            "recipient_name": "EXAMPLEWORKS SERVICES LLC",
            "recipient_uei": "EXMP1234ABC7",
            "awarding_subagency": "Public Buildings Service",
            "naics_code": "561720",
            "psc_code": "S201",
            "type_of_set_aside_code": "SBA",
            "extent_competed_code": "D",
            "number_of_offers_received": 3,
            "total_obligation": 100000.0,
            "base_and_all_options": 250000.0,
            "pop_start_date": "2024-06-01",
            "pop_current_end_date": "2025-05-31",
            "pop_potential_end_date": "2028-05-31",
            "place_of_performance": {"city": "Denver", "county": "Denver", "state": "co"},
        },
    )
    base.update(overrides)
    return base


# --- Valid parses ------------------------------------------------------------


def test_valid_minimal_parses_with_empty_claims_defaults() -> None:
    handoff = parse_radar_handoff(_bytes(_minimal()))
    assert handoff.schema_version == RADAR_HANDOFF_SCHEMA_VERSION
    assert handoff.snapshot_date == "2026-07-15"
    assert handoff.piid == "47QRAA24D0012"
    assert handoff.radar_source_label is None
    assert handoff.synthetic_sample is False
    assert handoff.claims == RadarHandoffClaims()
    assert handoff.unknown_field_count == 0


def test_valid_full_parses_every_claim_and_normalizes_state() -> None:
    handoff = parse_radar_handoff(_bytes(_full()))
    assert handoff.radar_source_label == "GovConRadar 2.8.0"
    assert handoff.synthetic_sample is True
    c = handoff.claims
    assert c.referenced_idv_piid == "47QSMD20D0001"
    assert c.recipient_name == "EXAMPLEWORKS SERVICES LLC"
    assert c.recipient_uei == "EXMP1234ABC7"
    assert c.awarding_subagency == "Public Buildings Service"
    assert c.naics_code == "561720"
    assert c.psc_code == "S201"
    assert c.type_of_set_aside_code == "SBA"
    assert c.extent_competed_code == "D"
    assert c.number_of_offers_received == 3
    assert c.total_obligation == 100000.0
    assert c.base_and_all_options == 250000.0
    assert c.pop_start_date == "2024-06-01"
    assert c.pop_current_end_date == "2025-05-31"
    assert c.pop_potential_end_date == "2028-05-31"
    assert c.place_of_performance == RadarHandoffPlace(city="Denver", county="Denver", state="CO")
    assert handoff.unknown_field_count == 0


def test_piid_is_stored_verbatim_not_stripped() -> None:
    # D9: prefill writes the PIID verbatim so the strip-only match gate
    # breaks only on an actual analyst edit, never on parser normalization.
    handoff = parse_radar_handoff(_bytes(_minimal(piid="  47QRAA24D0012  ")))
    assert handoff.piid == "  47QRAA24D0012  "


# --- Required-field failures -------------------------------------------------


def test_missing_schema_version_fails_closed() -> None:
    payload = _minimal()
    del payload["schema_version"]
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(payload))
    assert exc.value.code == "MISSING_FIELD"


def test_missing_snapshot_date_fails_closed() -> None:
    payload = _minimal()
    del payload["snapshot_date"]
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(payload))
    assert exc.value.code == "MISSING_FIELD"


def test_missing_piid_fails_closed() -> None:
    payload = _minimal()
    del payload["piid"]
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(payload))
    assert exc.value.code == "MISSING_FIELD"


def test_blank_piid_after_strip_fails_closed() -> None:
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(_minimal(piid="   ")))
    assert exc.value.code == "INVALID_FIELD"


# --- Wrong schema version -----------------------------------------------------


def test_wrong_schema_version_fails_closed() -> None:
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(_minimal(schema_version="radar-handoff/v2")))
    assert exc.value.code == "SCHEMA_VERSION"


def test_wrong_type_schema_version_fails_closed() -> None:
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(_minimal(schema_version=1)))
    assert exc.value.code == "INVALID_FIELD"


# --- Malformed shape / JSON ---------------------------------------------------


def test_invalid_json_fails_closed() -> None:
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(b"{not json")
    assert exc.value.code == "INVALID_JSON"


def test_non_object_top_level_fails_closed() -> None:
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(json.dumps([1, 2, 3]).encode("utf-8"))
    assert exc.value.code == "INVALID_SHAPE"


def test_non_object_claims_fails_closed() -> None:
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(_minimal(claims="not an object")))
    assert exc.value.code == "INVALID_FIELD"


def test_non_object_place_of_performance_fails_closed() -> None:
    payload = _minimal(claims={"place_of_performance": "Denver, CO"})
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(payload))
    assert exc.value.code == "INVALID_FIELD"


# --- Wrong types on known fields ----------------------------------------------


def test_wrong_type_snapshot_date_fails_closed() -> None:
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(_minimal(snapshot_date=20260715)))
    assert exc.value.code == "INVALID_FIELD"


def test_snapshot_date_with_time_component_fails_closed() -> None:
    # "strict date.fromisoformat; no time component" (§4) -- reject anything
    # that is not exactly YYYY-MM-DD, even a technically-parseable ISO string.
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(_minimal(snapshot_date="2026-07-15T00:00:00")))
    assert exc.value.code == "INVALID_FIELD"


def test_snapshot_date_not_a_real_calendar_date_fails_closed() -> None:
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(_minimal(snapshot_date="2026-13-40")))
    assert exc.value.code == "INVALID_FIELD"


def test_wrong_type_piid_fails_closed() -> None:
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(_minimal(piid=12345)))
    assert exc.value.code == "INVALID_FIELD"


def test_wrong_type_synthetic_sample_fails_closed() -> None:
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(_minimal(synthetic_sample="yes")))
    assert exc.value.code == "INVALID_FIELD"


def test_wrong_type_radar_source_label_fails_closed() -> None:
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(_minimal(radar_source_label=42)))
    assert exc.value.code == "INVALID_FIELD"


@pytest.mark.parametrize(
    "field",
    [
        "referenced_idv_piid",
        "recipient_name",
        "recipient_uei",
        "awarding_subagency",
        "naics_code",
        "psc_code",
        "type_of_set_aside_code",
        "extent_competed_code",
        "pop_start_date",
        "pop_current_end_date",
        "pop_potential_end_date",
    ],
)
def test_wrong_type_claims_string_field_fails_closed(field: str) -> None:
    payload = _minimal(claims={field: 12345})
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(payload))
    assert exc.value.code == "INVALID_FIELD"


def test_wrong_type_number_of_offers_received_fails_closed() -> None:
    payload = _minimal(claims={"number_of_offers_received": "3"})
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(payload))
    assert exc.value.code == "INVALID_FIELD"


def test_bool_number_of_offers_received_fails_closed() -> None:
    # bool is a subclass of int in Python; a JSON boolean must not slip
    # through as 0/1.
    payload = _minimal(claims={"number_of_offers_received": True})
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(payload))
    assert exc.value.code == "INVALID_FIELD"


def test_negative_offers_rejected() -> None:
    payload = _minimal(claims={"number_of_offers_received": -1})
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(payload))
    assert exc.value.code == "INVALID_FIELD"


def test_zero_offers_is_valid() -> None:
    payload = _minimal(claims={"number_of_offers_received": 0})
    handoff = parse_radar_handoff(_bytes(payload))
    assert handoff.claims.number_of_offers_received == 0


@pytest.mark.parametrize("field", ["total_obligation", "base_and_all_options"])
def test_wrong_type_money_field_fails_closed(field: str) -> None:
    payload = _minimal(claims={field: "a lot"})
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(payload))
    assert exc.value.code == "INVALID_FIELD"


def test_bool_money_field_fails_closed() -> None:
    payload = _minimal(claims={"total_obligation": True})
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(payload))
    assert exc.value.code == "INVALID_FIELD"


def test_integer_money_field_is_accepted_as_float() -> None:
    payload = _minimal(claims={"total_obligation": 100000})
    handoff = parse_radar_handoff(_bytes(payload))
    assert handoff.claims.total_obligation == 100000.0


@pytest.mark.parametrize("field", ["city", "county", "state"])
def test_wrong_type_place_field_fails_closed(field: str) -> None:
    payload = _minimal(claims={"place_of_performance": {field: 5}})
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(payload))
    assert exc.value.code == "INVALID_FIELD"


# --- Null semantics: absent vs explicit null both render the same fallback --


def test_explicit_null_claims_object_is_treated_as_absent() -> None:
    handoff = parse_radar_handoff(_bytes(_minimal(claims=None)))
    assert handoff.claims == RadarHandoffClaims()


def test_explicit_null_claim_member_parses_as_none() -> None:
    payload = _minimal(claims={"recipient_name": None, "type_of_set_aside_code": None})
    handoff = parse_radar_handoff(_bytes(payload))
    assert handoff.claims.recipient_name is None
    assert handoff.claims.type_of_set_aside_code is None


def test_absent_and_null_claim_member_render_identically_except_set_aside() -> None:
    absent = parse_radar_handoff(_bytes(_minimal(claims={})))
    explicit_null = parse_radar_handoff(
        _bytes(_minimal(claims={"recipient_name": None, "recipient_uei": None}))
    )
    lines_absent = "\n".join(radar_handoff_lines(absent, live_facts_attached=False))
    lines_null = "\n".join(radar_handoff_lines(explicit_null, live_facts_attached=False))
    assert lines_absent == lines_null
    assert "Not in handoff" in lines_absent


def test_set_aside_null_renders_not_reported_not_generic_absent() -> None:
    handoff = parse_radar_handoff(_bytes(_minimal(claims={"type_of_set_aside_code": None})))
    lines = "\n".join(radar_handoff_lines(handoff, live_facts_attached=False))
    assert "not reported in snapshot (null)" in lines
    # The generic fallback never appears on the set-aside line specifically.
    set_aside_line = next(line for line in lines.splitlines() if "set-aside code" in line)
    assert "Not in handoff" not in set_aside_line


def test_explicit_null_place_of_performance_is_treated_as_absent() -> None:
    payload = _minimal(claims={"place_of_performance": None})
    handoff = parse_radar_handoff(_bytes(payload))
    assert handoff.claims.place_of_performance is None


# --- Unknown-field counting ---------------------------------------------------


def test_unknown_top_level_field_is_counted_and_disclosed() -> None:
    payload = _minimal(extra_field="surprise")
    handoff = parse_radar_handoff(_bytes(payload))
    assert handoff.unknown_field_count == 1
    lines = "\n".join(radar_handoff_lines(handoff, live_facts_attached=False))
    assert "1 unrecognized field(s) in the handoff were ignored." in lines


def test_unknown_claims_field_is_counted() -> None:
    payload = _minimal(claims={"mystery": 1, "recipient_name": "X"})
    handoff = parse_radar_handoff(_bytes(payload))
    assert handoff.unknown_field_count == 1
    assert handoff.claims.recipient_name == "X"


def test_unknown_place_field_is_counted() -> None:
    payload = _minimal(claims={"place_of_performance": {"zip": "80202", "city": "Denver"}})
    handoff = parse_radar_handoff(_bytes(payload))
    assert handoff.unknown_field_count == 1
    assert handoff.claims.place_of_performance.city == "Denver"


def test_unknown_fields_at_every_scope_sum_together() -> None:
    payload = _minimal(
        extra1="a",
        claims={
            "extra2": "b",
            "place_of_performance": {"extra3": "c", "city": "Denver"},
        },
    )
    handoff = parse_radar_handoff(_bytes(payload))
    assert handoff.unknown_field_count == 3


def test_zero_unknown_fields_renders_no_disclosure_line() -> None:
    handoff = parse_radar_handoff(_bytes(_minimal()))
    lines = "\n".join(radar_handoff_lines(handoff, live_facts_attached=False))
    assert "unrecognized field" not in lines


# --- Size / length caps -------------------------------------------------------


def test_oversized_upload_fails_closed() -> None:
    payload = _minimal(radar_source_label="x" * (MAX_UPLOAD_BYTES + 1000))
    data = _bytes(payload)
    assert len(data) > MAX_UPLOAD_BYTES
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(data)
    assert exc.value.code == "TOO_LARGE"


def test_string_field_over_cap_fails_closed() -> None:
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(_minimal(piid="A" * (MAX_STRING_FIELD_CHARS + 1))))
    assert exc.value.code == "FIELD_TOO_LONG"


def test_string_field_at_cap_is_accepted() -> None:
    handoff = parse_radar_handoff(_bytes(_minimal(piid="A" * MAX_STRING_FIELD_CHARS)))
    assert len(handoff.piid) == MAX_STRING_FIELD_CHARS


def test_claims_string_field_over_cap_fails_closed() -> None:
    payload = _minimal(claims={"recipient_name": "A" * (MAX_STRING_FIELD_CHARS + 1)})
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(payload))
    assert exc.value.code == "FIELD_TOO_LONG"


# --- Never echoes uploaded content on error -----------------------------------


def test_error_never_echoes_uploaded_content() -> None:
    secret = "TOP-SECRET-CANARY-VALUE-9f8e7d"
    payload = _minimal(piid=secret, schema_version="bogus")
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(payload))
    assert secret not in str(exc.value)
    assert secret not in exc.value.public_message


def test_invalid_json_error_never_echoes_uploaded_bytes() -> None:
    hostile = b'{"piid": "leak-me-if-you-can", invalid'
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(hostile)
    assert b"leak-me-if-you-can" not in str(exc.value).encode("utf-8")


def test_all_error_messages_are_fixed_and_nonempty() -> None:
    for code, message in RadarHandoffError._MESSAGES.items():  # noqa: SLF001
        err = RadarHandoffError(code)
        assert err.public_message == message
        assert message.strip()


def test_unknown_error_code_falls_back_to_generic_message() -> None:
    err = RadarHandoffError("SOMETHING_NEW")
    assert err.public_message == "The handoff could not be read."


def test_deeply_nested_json_fails_closed_as_handoff_error() -> None:
    # ~100 KB of nesting sits far under MAX_UPLOAD_BYTES but drives the json
    # scanner into RecursionError; the fail-closed contract still owes the
    # caller a RadarHandoffError, never a leaked RecursionError.
    hostile = b"[" * 50_000 + b"]" * 50_000
    assert len(hostile) < MAX_UPLOAD_BYTES
    with pytest.raises(RadarHandoffError):
        parse_radar_handoff(hostile)


def test_state_longer_than_two_chars_fails_closed() -> None:
    payload = _minimal(claims={"place_of_performance": {"state": "COL"}})
    with pytest.raises(RadarHandoffError) as exc:
        parse_radar_handoff(_bytes(payload))
    assert "COL" not in exc.value.public_message


def test_state_all_whitespace_collapses_to_absent() -> None:
    payload = _minimal(claims={"place_of_performance": {"city": "Denver", "state": "   "}})
    handoff = parse_radar_handoff(_bytes(payload))
    assert handoff.claims.place_of_performance is not None
    assert handoff.claims.place_of_performance.state is None


# --- Injection strings escaped in rendered lines ------------------------------


def test_markdown_injection_in_piid_is_escaped() -> None:
    hostile = "[click me](http://evil.example)"
    handoff = parse_radar_handoff(_bytes(_minimal(piid=hostile)))
    lines = "\n".join(radar_handoff_lines(handoff, live_facts_attached=False))
    assert hostile not in lines
    assert "\\[click me\\]\\(http://evil.example\\)" in lines


def test_markdown_injection_in_recipient_name_is_escaped() -> None:
    hostile = "*bold* `code` <script>"
    payload = _minimal(claims={"recipient_name": hostile})
    handoff = parse_radar_handoff(_bytes(payload))
    lines = "\n".join(radar_handoff_lines(handoff, live_facts_attached=False))
    assert hostile not in lines
    assert "\\*bold\\* \\`code\\` \\<script\\>" in lines


def test_markdown_injection_in_radar_source_label_is_escaped() -> None:
    hostile = "[phish](http://evil.example)"
    handoff = parse_radar_handoff(_bytes(_minimal(radar_source_label=hostile)))
    lines = "\n".join(radar_handoff_lines(handoff, live_facts_attached=False))
    assert hostile not in lines


def test_newline_injection_cannot_forge_markdown_structure() -> None:
    # Character escaping alone cannot stop an embedded newline from escaping
    # its "Radar-claimed" bullet and forging a top-level heading in the packet
    # body (the A7 export-layer lesson, now applied to this renderer's _md).
    hostile = "Acme\n\n## Eligibility Gate — PASS (analyst-confirmed)\n\n- Fully eligible"
    payload = _minimal(claims={"recipient_name": hostile})
    handoff = parse_radar_handoff(_bytes(payload))
    lines = radar_handoff_lines(handoff, live_facts_attached=False)
    heading_lines = [line for line in lines if line.startswith("#")]
    assert heading_lines == ["## Origin — Radar handoff (context, not evidence)"]
    joined = "\n".join(lines)
    assert "\n## Eligibility Gate" not in joined
    assert "\n- Fully eligible" not in joined
    # The flattened, escaped claim stays inside its single bullet: the name
    # and the would-be heading text end up on the SAME rendered line.
    bullet = next(line for line in lines if "Acme" in line)
    assert "## Eligibility Gate" in bullet
    assert not bullet.startswith("#")


def test_newline_injection_flattened_in_every_string_claim_field() -> None:
    hostile = "x\n\n# forged heading"
    string_claim_keys = (
        "referenced_idv_piid",
        "recipient_name",
        "recipient_uei",
        "awarding_subagency",
        "naics_code",
        "psc_code",
        "type_of_set_aside_code",
        "extent_competed_code",
        "pop_start_date",
        "pop_current_end_date",
        "pop_potential_end_date",
    )
    for key in string_claim_keys:
        handoff = parse_radar_handoff(_bytes(_minimal(claims={key: hostile})))
        lines = radar_handoff_lines(handoff, live_facts_attached=False)
        assert all(not line.startswith("# forged") for line in lines), key
        assert "\n# forged heading" not in "\n".join(lines), key


# --- Render shape: caveat-first, live-supersedes, synthetic, no score --------


def test_render_is_caveat_first_before_any_claim() -> None:
    handoff = parse_radar_handoff(_bytes(_full()))
    lines = radar_handoff_lines(handoff, live_facts_attached=False)
    assert lines[0] == "## Origin — Radar handoff (context, not evidence)"
    caveat_index = next(i for i, line in enumerate(lines) if "NOT packet evidence" in line)
    piid_index = next(i for i, line in enumerate(lines) if "Radar-claimed PIID" in line)
    assert caveat_index < piid_index


def test_synthetic_sample_note_renders_when_flagged() -> None:
    handoff = parse_radar_handoff(_bytes(_minimal(synthetic_sample=True)))
    lines = "\n".join(radar_handoff_lines(handoff, live_facts_attached=False))
    assert "SYNTHETIC example handoff" in lines


def test_synthetic_sample_note_absent_when_not_flagged() -> None:
    handoff = parse_radar_handoff(_bytes(_minimal()))
    lines = "\n".join(radar_handoff_lines(handoff, live_facts_attached=False))
    assert "SYNTHETIC example handoff" not in lines


def test_live_supersedes_line_only_when_flagged() -> None:
    handoff = parse_radar_handoff(_bytes(_minimal()))
    with_live = "\n".join(radar_handoff_lines(handoff, live_facts_attached=True))
    without_live = "\n".join(radar_handoff_lines(handoff, live_facts_attached=False))
    assert "live values govern" in with_live
    assert "live values govern" not in without_live


def test_never_feeds_the_gate_reminder_is_always_present() -> None:
    handoff = parse_radar_handoff(_bytes(_minimal()))
    lines = "\n".join(radar_handoff_lines(handoff, live_facts_attached=False))
    assert "never feeds the Eligibility Gate" in lines


def test_no_score_or_directive_vocabulary_anywhere() -> None:
    handoff = parse_radar_handoff(_bytes(_full()))
    lines = "\n".join(radar_handoff_lines(handoff, live_facts_attached=True)).lower()
    for forbidden in ("score", "pwin", "/100", "bid/no-bid", "tier", "rank", "recommend", "should bid", "route"):
        assert forbidden not in lines


def test_radar_source_label_absent_renders_not_stated() -> None:
    handoff = parse_radar_handoff(_bytes(_minimal()))
    lines = "\n".join(radar_handoff_lines(handoff, live_facts_attached=False))
    assert "Radar source: Not stated in handoff" in lines


def test_obligated_and_ceiling_stay_distinct_never_summed() -> None:
    handoff = parse_radar_handoff(
        _bytes(_minimal(claims={"total_obligation": 100000.0, "base_and_all_options": 250000.0}))
    )
    lines = "\n".join(radar_handoff_lines(handoff, live_facts_attached=False))
    assert "$100,000.00" in lines
    assert "$250,000.00" in lines
    assert "$350,000.00" not in lines


def test_place_of_performance_renders_only_present_parts() -> None:
    payload = _minimal(claims={"place_of_performance": {"city": "Denver"}})
    handoff = parse_radar_handoff(_bytes(payload))
    lines = "\n".join(radar_handoff_lines(handoff, live_facts_attached=False))
    place_line = next(line for line in lines.splitlines() if "place of performance" in line)
    assert place_line.endswith("Denver")


def test_state_normalization_strip_and_upper() -> None:
    payload = _minimal(claims={"place_of_performance": {"state": "  co  "}})
    handoff = parse_radar_handoff(_bytes(payload))
    assert handoff.claims.place_of_performance.state == "CO"
