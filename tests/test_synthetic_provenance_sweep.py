"""Whole-export assurance sweep for the bundled synthetic Contract Facts.

Single-section assertions let live-provenance claims survive elsewhere in the
packet. This module builds the complete cited export and sweeps every rendered
line, with a separate coverage guard so removing a section cannot make the
assurance pass vacuously.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from tens_hq.connectors import SubawardRecord, SubawardsResult, load_synthetic_example_facts
from tens_hq.eligibility_gate import assess_eligibility
from tens_hq.opportunity_packet import build_opportunity_packet_markdown
from tens_hq.packet_export import (
    SectionEntry,
    SourceEntry,
    assemble_packet_export,
    derive_section_ledger,
    derive_source_manifest,
)
from tens_hq.pl_match import R2B_HEADER, PLMatchResult
from tens_hq.radar_handoff import parse_radar_handoff
from tens_hq.staffing_whatif import (
    STAFFING_HEADER,
    StaffingWhatIfInput,
    WhatIfMode,
    assess_staffing_whatif,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_AS_OF = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
_MIN_RENDERED_LINE_COUNT = 216

_REQUIRED_BODY_HEADERS = {
    "## Origin — Radar handoff (context, not evidence)",
    "## Eligibility gate (can the NPA prime?)",
    "## Contract Facts (SYNTHETIC example — offline, not a live retrieval)",
    "## Contract Facts (analyst-entered)",
    "## Capture window (estimated solicitation + R2a start-by band)",
    "## Incumbent & teaming leads / PL-impact context (cited)",
    STAFFING_HEADER,
    "## Geography context (ACS)",
    R2B_HEADER,
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


def _build_synthetic_export() -> tuple[
    tuple[SectionEntry, ...], tuple[SourceEntry, ...], str
]:
    resolution = load_synthetic_example_facts()
    contract_facts = resolution.record
    assert contract_facts is not None
    assert contract_facts.synthetic_example is True
    contract_facts_raw_set_aside = "8A"
    contract_facts = replace(
        contract_facts,
        set_aside_code=contract_facts_raw_set_aside,
        set_aside_description="8(A) SET-ASIDE",
    )

    handoff = parse_radar_handoff(
        (_REPO_ROOT / "data" / "samples" / "sample_radar_handoff.json").read_bytes()
    )
    assert handoff.synthetic_sample is True

    subawards = SubawardsResult(
        award_generated_internal_id=contract_facts.generated_unique_award_id or "",
        records=(
            SubawardRecord(
                subaward_number="SYNTH-SUB-001",
                recipient_name="ExampleWorks Sub LLC",
                amount=5000.0,
                action_date="2026-07-01",
                description="Synthetic custodial support",
            ),
        ),
        truncated=False,
        source_url="https://example.test/synthetic-subawards",
        retrieved_at="2026-07-24T12:05:00+00:00",
    )
    assert (subawards.source_url, subawards.retrieved_at) != (
        contract_facts.source_url,
        contract_facts.retrieved_at,
    )
    directory_agency_names = ["ExampleWorks Sub LLC"]
    staffing = assess_staffing_whatif(
        StaffingWhatIfInput(
            mode=WhatIfMode.HOURS,
            baseline_qualifying_hours=750.0,
            baseline_total_hours=1000.0,
            scenario_total_hours=200.0,
            scenario_qualifying_count=100.0,
        )
    )
    pl_matches = PLMatchResult(
        city="Denver",
        state="CO",
        queried_service_type="Custodial",
        source_label="sample_nib_npa.xlsx (SYNTHETIC example)",
        retrieved_at="2026-07-24",
        synthetic_sample=True,
        service_type_matches=(),
        same_location_other=(),
    )

    body = build_opportunity_packet_markdown(
        piid=contract_facts.piid,
        county="Denver",
        state="CO",
        eligibility=assess_eligibility(contract_facts_raw_set_aside),
        geography=None,
        pl_matches=pl_matches,
        # ACS geography and FR notices are independent of award provenance.
        # Their API_RETRIEVED assurance can be honest in a synthetic award run.
        pl_notices=None,
        contract_facts=contract_facts,
        subawards=subawards,
        directory_agency_names=directory_agency_names,
        radar_handoff=handoff,
        staffing=staffing,
        as_of=_AS_OF,
    )
    ledger = derive_section_ledger(
        eligibility=assess_eligibility(contract_facts_raw_set_aside),
        contract_facts=contract_facts,
        geography=None,
        pl_matches=pl_matches,
        subawards=subawards,
        directory_agency_names=directory_agency_names,
        handoff_attached=True,
        handoff_piid_matched=True,
        staffing=staffing,
        pl_notices=None,
    )
    manifest = derive_source_manifest(
        contract_facts=contract_facts,
        subawards=subawards,
        geography=None,
        pl_matches=pl_matches,
        directory_source_label="sample_nib_npa.xlsx (SYNTHETIC example)",
        set_aside_analyst_value=contract_facts_raw_set_aside,
        handoff=handoff,
        handoff_source_label="sample_radar_handoff.json (SYNTHETIC example)",
        handoff_piid_matched=True,
        staffing=staffing,
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
    return ledger, manifest, rendered


_LEDGER, _MANIFEST, _RENDERED_PACKET = _build_synthetic_export()
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


def test_synthetic_manifest_assurances_are_never_live() -> None:
    assert _MANIFEST
    assert {row.assurance for row in _MANIFEST} <= {
        "SYNTHETIC_EXAMPLE",
        "USER_ATTESTED",
    }
