"""A2 Radar-handoff intake: a versioned, offline parse of one GovConRadar claim.

An analyst can carry ONE opportunity from GovConRadar into the Opportunity
Packet tab as an uploaded ``radar-handoff/v1`` JSON file. This module parses
that file offline and renders it as a caveat-first *Origin* section. The
handoff is a claim from a snapshot, never packet evidence:

* **The handoff never feeds any assessment (§1.1).** Nothing parsed here is
  ever passed to ``assess_eligibility``, ``assess_capture_window``, or
  ``derive_incumbent_leads``. In particular ``claims.type_of_set_aside_code``
  is display-only and must never be written into the analyst set-aside input
  -- that would launder a Radar claim into "analyst-entered".
* **Every value renders as a labeled claim, caveat-first (§1.3).** All of it
  goes through this module's own ``_md`` escape chokepoint, exactly like
  ``opportunity_packet.py`` / ``pl_match.py`` / ``eligibility_gate.py`` (the
  anti-circular-import convention this module simply follows: each renderer
  keeps its own narrow ``_MD_ESCAPE`` copy rather than importing one).
* **Three honest field states, not two.** Within ``claims``, a member key
  that is simply absent and a member key that is explicitly JSON ``null``
  both collapse to Python ``None`` here -- the parser does not retain which
  one it was, since neither carries packet evidence either way. The ONE field
  where that distinction is called out explicitly in the render is
  ``type_of_set_aside_code``: it always reads "not reported in snapshot
  (null)" rather than the generic "Not in handoff" fallback, echoing the
  Eligibility Gate's own "blank is not unrestricted" discipline (null != NONE
  != unrestricted) so a missing set-aside claim can never be misread as "no
  restriction reported".
* **Not every parsed claim is rendered.** The schema (§4) is intentionally
  wider than the Origin section's render (§5) -- ``referenced_idv_piid``,
  ``awarding_subagency``, ``extent_competed_code``, and
  ``number_of_offers_received`` are parsed (and available on
  :class:`RadarHandoffClaims` for tests / future use) but are not part of the
  Origin section's rendered lines, keeping that section terse and clearly
  distinct from the live-retrieved Contract Facts block it never duplicates.

This module is pure (no Streamlit, no network, no filesystem, no clock):
``parse_radar_handoff(data: bytes) -> RadarHandoff`` is byte-in,
dataclass-out, and every parse failure raises the single
:class:`RadarHandoffError` with a fixed, safe message that never echoes
upload content, a filename, or a field value (house style:
``connectors.base.ConnectorError`` / ``coerce_source_kind``, reimplemented
here rather than imported, because the handoff is not connector-routed --
it is a packet-local pure parse, like ``pl_match.py``). See ADR-019.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re
from typing import Any

RADAR_HANDOFF_SCHEMA_VERSION = "radar-handoff/v1"

# Hard caps (§4): violations fail closed rather than being silently truncated.
MAX_UPLOAD_BYTES = 1_000_000
MAX_STRING_FIELD_CHARS = 500

_SNAPSHOT_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class RadarHandoffError(ValueError):
    """A safe, user-facing handoff-parse failure with a fixed message.

    ``code`` is suitable for structured audit logging. ``public_message`` is
    fixed and intentionally omits uploaded content, filenames, and field
    values -- it is safe to interpolate directly into ``st.error``.
    """

    _MESSAGES = {
        "TOO_LARGE": "The handoff file exceeds the permitted size.",
        "INVALID_JSON": "The handoff file is not valid JSON.",
        "INVALID_SHAPE": "The handoff file is not a valid handoff object.",
        "SCHEMA_VERSION": "This handoff's schema version is not supported.",
        "MISSING_FIELD": "The handoff is missing a required field.",
        "INVALID_FIELD": "The handoff contains an invalid field value.",
        "FIELD_TOO_LONG": "The handoff contains a field value that is too long.",
    }

    def __init__(self, code: str):
        self.code = str(code)
        self.public_message = self._MESSAGES.get(self.code, "The handoff could not be read.")
        super().__init__(self.public_message)


@dataclass(frozen=True, slots=True)
class RadarHandoffPlace:
    """A claimed place of performance from the Radar snapshot (never geocoded).

    ``state`` is normalized to ``strip().upper()`` on parse (§4); ``city`` and
    ``county`` are carried verbatim (no strict-parse discipline, mirrors the
    period-of-performance date fields, ADR-014).
    """

    city: str | None = None
    county: str | None = None
    state: str | None = None


@dataclass(frozen=True, slots=True)
class RadarHandoffClaims:
    """The optional per-contract claims carried in a Radar handoff snapshot.

    Every member is optional and independently nullable. ``None`` means
    either "the field was absent from the handoff" or "the field was
    explicitly ``null`` in the handoff" -- both collapse to the same
    "not available from this snapshot" meaning for rendering (see the module
    docstring and :func:`radar_handoff_lines`). Money fields
    (``total_obligation``, ``base_and_all_options``) stay distinct and are
    never summed or conflated, matching the live Contract Facts discipline.
    """

    referenced_idv_piid: str | None = None
    recipient_name: str | None = None
    recipient_uei: str | None = None
    awarding_subagency: str | None = None
    naics_code: str | None = None
    psc_code: str | None = None
    type_of_set_aside_code: str | None = None
    extent_competed_code: str | None = None
    number_of_offers_received: int | None = None
    total_obligation: float | None = None
    base_and_all_options: float | None = None
    pop_start_date: str | None = None
    pop_current_end_date: str | None = None
    pop_potential_end_date: str | None = None
    place_of_performance: RadarHandoffPlace | None = None


@dataclass(frozen=True, slots=True)
class RadarHandoff:
    """One parsed, versioned Radar-handoff snapshot (offline, pure).

    ``piid`` is stored VERBATIM (not stripped): a UI prefill writes the exact
    handoff value into the packet's PIID input, so the PIID-match gate's
    strip-only compare (D9, mirrors ``bd_page.py:583``) breaks only on an
    actual analyst edit, never on a parser normalization.
    """

    schema_version: str
    snapshot_date: str
    piid: str
    radar_source_label: str | None
    synthetic_sample: bool
    claims: RadarHandoffClaims
    unknown_field_count: int


# --- Parsing ---------------------------------------------------------------

_KNOWN_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "snapshot_date",
        "piid",
        "radar_source_label",
        "synthetic_sample",
        "claims",
    }
)

_CLAIMS_STRING_KEYS = (
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

_KNOWN_CLAIMS_KEYS = frozenset(_CLAIMS_STRING_KEYS) | frozenset(
    {
        "number_of_offers_received",
        "total_obligation",
        "base_and_all_options",
        "place_of_performance",
    }
)

_KNOWN_PLACE_KEYS = frozenset({"city", "county", "state"})


def _require_string(container: dict[str, Any], key: str) -> str:
    if key not in container:
        raise RadarHandoffError("MISSING_FIELD")
    value = container[key]
    if not isinstance(value, str):
        raise RadarHandoffError("INVALID_FIELD")
    if len(value) > MAX_STRING_FIELD_CHARS:
        raise RadarHandoffError("FIELD_TOO_LONG")
    return value


def _optional_string(container: dict[str, Any], key: str) -> str | None:
    if key not in container:
        return None
    value = container[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise RadarHandoffError("INVALID_FIELD")
    if len(value) > MAX_STRING_FIELD_CHARS:
        raise RadarHandoffError("FIELD_TOO_LONG")
    return value


def _optional_nonneg_int(container: dict[str, Any], key: str) -> int | None:
    if key not in container:
        return None
    value = container[key]
    if value is None:
        return None
    # bool is a subclass of int in Python; exclude it explicitly so a JSON
    # `true`/`false` is never silently accepted as 1/0.
    if isinstance(value, bool) or not isinstance(value, int):
        raise RadarHandoffError("INVALID_FIELD")
    if value < 0:
        raise RadarHandoffError("INVALID_FIELD")
    return value


def _optional_number(container: dict[str, Any], key: str) -> float | None:
    if key not in container:
        return None
    value = container[key]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RadarHandoffError("INVALID_FIELD")
    return float(value)


def parse_radar_handoff(data: bytes) -> RadarHandoff:
    """Parse and validate a ``radar-handoff/v1`` upload (pure, offline).

    Fails closed (:class:`RadarHandoffError`, fixed message, content never
    echoed) on: an oversized payload, invalid JSON, a non-object top level, a
    missing or wrong-version ``schema_version``, a missing/blank/wrong-type
    ``piid``, a malformed ``snapshot_date``, a non-2-char (after strip/upper)
    ``place_of_performance.state``, or any wrong TYPE on a known
    field. Unknown keys (top level, inside ``claims``, or inside
    ``place_of_performance``) are silently ignored but counted into
    ``RadarHandoff.unknown_field_count`` so the Origin section can disclose
    them (§4/D6) -- an unrecognized field is forward-compatibility noise, not
    a parse failure.
    """

    if len(data) > MAX_UPLOAD_BYTES:
        raise RadarHandoffError("TOO_LARGE")
    try:
        parsed = json.loads(data)
    except (ValueError, UnicodeDecodeError, RecursionError):
        # json.loads raises UnicodeDecodeError for bytes it cannot decode and
        # json.JSONDecodeError (a ValueError subclass) for malformed JSON.
        # RecursionError covers a deeply-nested payload under the byte cap --
        # without it the fail-closed single-exception contract leaks an
        # uncaught error to callers.
        raise RadarHandoffError("INVALID_JSON") from None
    if not isinstance(parsed, dict):
        raise RadarHandoffError("INVALID_SHAPE")

    schema_version = _require_string(parsed, "schema_version")
    if schema_version != RADAR_HANDOFF_SCHEMA_VERSION:
        raise RadarHandoffError("SCHEMA_VERSION")

    snapshot_date = _require_string(parsed, "snapshot_date")
    if not _SNAPSHOT_DATE_RE.match(snapshot_date):
        raise RadarHandoffError("INVALID_FIELD")
    try:
        date.fromisoformat(snapshot_date)
    except ValueError:
        raise RadarHandoffError("INVALID_FIELD") from None

    piid = _require_string(parsed, "piid")
    if not piid.strip():
        raise RadarHandoffError("INVALID_FIELD")

    radar_source_label = _optional_string(parsed, "radar_source_label")

    synthetic_sample = False
    if "synthetic_sample" in parsed:
        raw_synthetic = parsed["synthetic_sample"]
        if not isinstance(raw_synthetic, bool):
            raise RadarHandoffError("INVALID_FIELD")
        synthetic_sample = raw_synthetic

    unknown_field_count = sum(1 for key in parsed if key not in _KNOWN_TOP_LEVEL_KEYS)

    claims_raw = parsed.get("claims")
    if claims_raw is None:
        claims = RadarHandoffClaims()
    else:
        if not isinstance(claims_raw, dict):
            raise RadarHandoffError("INVALID_FIELD")
        unknown_field_count += sum(1 for key in claims_raw if key not in _KNOWN_CLAIMS_KEYS)

        claim_values: dict[str, Any] = {
            key: _optional_string(claims_raw, key) for key in _CLAIMS_STRING_KEYS
        }
        claim_values["number_of_offers_received"] = _optional_nonneg_int(
            claims_raw, "number_of_offers_received"
        )
        claim_values["total_obligation"] = _optional_number(claims_raw, "total_obligation")
        claim_values["base_and_all_options"] = _optional_number(
            claims_raw, "base_and_all_options"
        )

        place_raw = claims_raw.get("place_of_performance")
        if place_raw is None:
            place = None
        else:
            if not isinstance(place_raw, dict):
                raise RadarHandoffError("INVALID_FIELD")
            unknown_field_count += sum(
                1 for key in place_raw if key not in _KNOWN_PLACE_KEYS
            )
            city = _optional_string(place_raw, "city")
            county = _optional_string(place_raw, "county")
            state = _optional_string(place_raw, "state")
            if state is not None:
                state = state.strip().upper()
                # The schema contract is a 2-char state after normalization
                # (§4). Enforce it fail-closed: a longer value would bypass
                # the state widget's own max_chars=2 guard via the prefill's
                # programmatic session-state write. All-whitespace collapses
                # to absent rather than to an empty claim.
                if not state:
                    state = None
                elif len(state) != 2:
                    raise RadarHandoffError("INVALID_FIELD")
            place = RadarHandoffPlace(city=city, county=county, state=state)
        claim_values["place_of_performance"] = place

        claims = RadarHandoffClaims(**claim_values)

    return RadarHandoff(
        schema_version=schema_version,
        snapshot_date=snapshot_date,
        piid=piid,
        radar_source_label=radar_source_label,
        synthetic_sample=synthetic_sample,
        claims=claims,
        unknown_field_count=unknown_field_count,
    )


# --- Rendering ---------------------------------------------------------------
#
# Caveat FIRST (§5): the standing "this is a claim, not evidence" framing and
# the never-feeds-the-gate reminder always precede every fact-pair, so no
# claim can be read in isolation as packet evidence.

RADAR_HANDOFF_HEADER = "## Origin — Radar handoff (context, not evidence)"

RADAR_HANDOFF_SYNTHETIC_NOTE = "SYNTHETIC example handoff — not real Radar output."

RADAR_HANDOFF_LIVE_SUPERSEDES = (
    "Live USAspending Contract Facts are attached to this packet; where they "
    "differ from these snapshot claims, the live values govern."
)

_NOT_IN_HANDOFF = "Not in handoff"
_NOT_STATED_IN_HANDOFF = "Not stated in handoff"
_SET_ASIDE_NOT_REPORTED = "not reported in snapshot (null)"


# A Radar-supplied claim string is interpolated into Markdown rendered by
# ``st.markdown``. Keep the same deliberately narrow escape set every other
# packet renderer uses (link/code/emphasis/autolink syntax only) -- this is a
# LOCAL copy, not an import, matching the established anti-circular-import
# convention (see ``packet_export.py``'s own note on the same choice).
_MD_ESCAPE = {ch: "\\" + ch for ch in "\\`*[]()<>"}


def _md(value: object) -> str:
    if value is None:
        return ""
    # Flatten every line-boundary class BEFORE escaping (the A7 export-layer
    # fix, packet_export._md): an embedded newline in an uploaded claim string
    # would otherwise escape its "Radar-claimed" bullet and forge top-level
    # Markdown structure (a heading, a bullet) in the on-screen packet AND the
    # verbatim export body. Character escaping alone cannot stop that.
    flat = " ".join(str(value).splitlines())
    return "".join(_MD_ESCAPE.get(ch, ch) for ch in flat)


def _claim_text(value: str | None) -> str:
    if value is None or not str(value).strip():
        return _NOT_IN_HANDOFF
    return _md(value)


def _money_claim_text(value: float | None) -> str:
    if value is None:
        return _NOT_IN_HANDOFF
    return f"${value:,.2f}"


def _place_claim_text(place: RadarHandoffPlace | None) -> str:
    if place is None:
        return _NOT_IN_HANDOFF
    parts = [p for p in (place.city, place.county, place.state) if p and str(p).strip()]
    if not parts:
        return _NOT_IN_HANDOFF
    return ", ".join(_md(p) for p in parts)


def radar_handoff_lines(handoff: RadarHandoff, *, live_facts_attached: bool) -> list[str]:
    """Render the Origin section as caveat-first Markdown lines (pure, §5).

    Every interpolation goes through :func:`_md`. No route, no directive, no
    score, no "match", and no recommendation anywhere (N1, AGENTS #8/#11) --
    this section presents labeled claims from a snapshot, nothing more.
    """

    claims = handoff.claims
    lines: list[str] = [
        RADAR_HANDOFF_HEADER,
        "",
        "- This packet's target was handed off from a Radar snapshot dated "
        f"{_md(handoff.snapshot_date)}. Every value below is a claim from "
        "that snapshot — NOT packet evidence. Every fact this packet "
        "asserts is either retrieved live with its own citation or "
        "explicitly analyst-entered. The handoff never feeds the "
        "Eligibility Gate or any other assessment.",
    ]
    if handoff.synthetic_sample:
        lines.append(f"- {RADAR_HANDOFF_SYNTHETIC_NOTE}")
    if live_facts_attached:
        lines.append(f"- {RADAR_HANDOFF_LIVE_SUPERSEDES}")
    source_text = _md(handoff.radar_source_label) if handoff.radar_source_label else ""
    lines.append(f"- Radar source: {source_text or _NOT_STATED_IN_HANDOFF}")
    lines.append(f"- Radar-claimed PIID: {_md(handoff.piid)}")
    lines.append(
        f"- Radar-claimed recipient: {_claim_text(claims.recipient_name)} · "
        f"UEI {_claim_text(claims.recipient_uei)}"
    )
    lines.append(
        f"- Radar-claimed NAICS / PSC: {_claim_text(claims.naics_code)} / "
        f"{_claim_text(claims.psc_code)}"
    )
    set_aside_text = (
        _md(claims.type_of_set_aside_code)
        if claims.type_of_set_aside_code and claims.type_of_set_aside_code.strip()
        else _SET_ASIDE_NOT_REPORTED
    )
    lines.append(
        f"- Radar-claimed set-aside code (snapshot): {set_aside_text} — this "
        "value is displayed only; it does not feed the gate."
    )
    lines.append(
        f"- Radar-claimed obligated: {_money_claim_text(claims.total_obligation)} · "
        f"ceiling (base + all options): {_money_claim_text(claims.base_and_all_options)} "
        "— ceiling is potential value, not money obligated."
    )
    lines.append(
        f"- Radar-claimed period: start {_claim_text(claims.pop_start_date)} · "
        f"current end {_claim_text(claims.pop_current_end_date)} · potential "
        f"end {_claim_text(claims.pop_potential_end_date)}"
    )
    lines.append(
        f"- Radar-claimed place of performance: {_place_claim_text(claims.place_of_performance)}"
    )
    if handoff.unknown_field_count > 0:
        lines.append(
            f"- {handoff.unknown_field_count} unrecognized field(s) in the handoff "
            "were ignored."
        )
    lines.append("")
    return lines


__all__ = [
    "MAX_STRING_FIELD_CHARS",
    "MAX_UPLOAD_BYTES",
    "RADAR_HANDOFF_HEADER",
    "RADAR_HANDOFF_LIVE_SUPERSEDES",
    "RADAR_HANDOFF_SCHEMA_VERSION",
    "RADAR_HANDOFF_SYNTHETIC_NOTE",
    "RadarHandoff",
    "RadarHandoffClaims",
    "RadarHandoffError",
    "RadarHandoffPlace",
    "parse_radar_handoff",
    "radar_handoff_lines",
]
