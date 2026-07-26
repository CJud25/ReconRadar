"""Whole-export assurance sweep for the bundled synthetic Contract Facts.

Single-section assertions let live-provenance claims survive elsewhere in the
packet. This module builds the complete cited export and sweeps every rendered
line, with a separate coverage guard so removing a section cannot make the
assurance pass vacuously.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from tens_hq.connectors import load_synthetic_example_facts
from tens_hq.opportunity_packet import build_opportunity_packet_markdown
from tens_hq.packet_export import (
    SectionEntry,
    assemble_packet_export,
    derive_section_ledger,
    derive_source_manifest,
)
from tens_hq.radar_handoff import parse_radar_handoff

_REPO_ROOT = Path(__file__).resolve().parents[1]
_AS_OF = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
_MIN_RENDERED_LINE_COUNT = 169

_REQUIRED_BODY_HEADERS = {
    "## Origin — Radar handoff (context, not evidence)",
    "## Eligibility gate (can the NPA prime?)",
    "## Contract Facts (SYNTHETIC example — offline, not a live retrieval)",
    "## Contract Facts (analyst-entered)",
    "## Capture window (estimated solicitation + R2a start-by band)",
    "## Incumbent & teaming leads / PL-impact context (cited)",
    "## Geography context (ACS)",
    "## R2a determination-support map (evidence toward suitability, 41 CFR 51-2.4(a))",
}

_NEGATED_LIVE = re.compile(r"\b(?:not(?:\s+a)?|no)\s+live\b", re.IGNORECASE)
_NEGATED_API_RETRIEVED = re.compile(
    r"\b(?:not|no)\s+(?:an?\s+)?API_RETRIEVED\b", re.IGNORECASE
)
_LIVE_CLAIM_PATTERNS = {
    "API_RETRIEVED": re.compile(r"\bAPI_RETRIEVED\b", re.IGNORECASE),
    "LIVE token": re.compile(r"\bLIVE\b", re.IGNORECASE),
    "live retrieval": re.compile(r"\blive\s+retrieval\b", re.IGNORECASE),
    "live pull": re.compile(r"\blive\b[^.\n|]{0,80}\bpull\b", re.IGNORECASE),
    "Live USAspending": re.compile(r"\blive\s+USAspending\b", re.IGNORECASE),
}


def _build_synthetic_export() -> tuple[tuple[SectionEntry, ...], str]:
    resolution = load_synthetic_example_facts()
    contract_facts = resolution.record
    assert contract_facts is not None
    assert contract_facts.synthetic_example is True

    handoff = parse_radar_handoff(
        (_REPO_ROOT / "data" / "samples" / "sample_radar_handoff.json").read_bytes()
    )
    assert handoff.synthetic_sample is True

    body = build_opportunity_packet_markdown(
        piid=contract_facts.piid,
        county="Denver",
        state="CO",
        eligibility=None,
        geography=None,
        pl_matches=None,
        pl_notices=None,
        contract_facts=contract_facts,
        subawards=None,
        directory_agency_names=None,
        radar_handoff=handoff,
        staffing=None,
        as_of=_AS_OF,
    )
    ledger = derive_section_ledger(
        eligibility=None,
        contract_facts=contract_facts,
        geography=None,
        pl_matches=None,
        subawards=None,
        directory_agency_names=None,
        handoff_attached=True,
        handoff_piid_matched=True,
        staffing=None,
        pl_notices=None,
    )
    manifest = derive_source_manifest(
        contract_facts=contract_facts,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
        handoff=handoff,
        handoff_source_label="sample_radar_handoff.json (SYNTHETIC example)",
        handoff_piid_matched=True,
        staffing=None,
        pl_notices=None,
    )
    rendered = assemble_packet_export(
        body_markdown=body,
        piid=contract_facts.piid,
        county="Denver",
        state="CO",
        ledger=ledger,
        manifest=manifest,
        as_of=_AS_OF,
    )
    return ledger, rendered


_LEDGER, _RENDERED_PACKET = _build_synthetic_export()
_RENDERED_LINES = _RENDERED_PACKET.splitlines()


def test_synthetic_provenance_sweep_covers_the_full_export() -> None:
    headers = {line for line in _RENDERED_LINES if line.startswith("## ")}
    assert len(_REQUIRED_BODY_HEADERS) >= 8
    assert _REQUIRED_BODY_HEADERS <= headers
    assert {"## Section ledger", "## Source manifest"} <= headers
    assert len(_LEDGER) >= 11
    assert len(_RENDERED_LINES) >= _MIN_RENDERED_LINE_COUNT


def test_synthetic_export_has_no_live_provenance_claim() -> None:
    violations: list[str] = []
    for line_number, line in enumerate(_RENDERED_LINES, start=1):
        candidate = _NEGATED_LIVE.sub("", line)
        candidate = _NEGATED_API_RETRIEVED.sub("", candidate)
        matches = [
            label for label, pattern in _LIVE_CLAIM_PATTERNS.items() if pattern.search(candidate)
        ]
        if matches:
            violations.append(f"line {line_number} [{', '.join(matches)}]: {line}")

    assert violations == [], (
        "synthetic packet carries live-provenance claim language:\n"
        + "\n".join(violations)
    )
