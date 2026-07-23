"""Offline unit tests for the packet-export assembler (A7). Covers every
honesty invariant in the brief §3: body-verbatim, evidence-absence wording,
no new analysis/directive vocabulary, assurance truthfulness, two-layer
escaping, filename safety, and as_of injection/determinism -- plus the two
pinned audit-finding predicates (the gate row and the analyst-set-aside
manifest row).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from conftest import counsel_gate_violations
from tens_hq.connectors import (
    ContractFactsRecord,
    FRNoticeRecord,
    GeographyRecord,
    PLNoticesResult,
    SubawardRecord,
    SubawardsResult,
)
from tens_hq.eligibility_gate import assess_eligibility
from tens_hq.opportunity_packet import PACKET_FRAMING, build_opportunity_packet_markdown
from tens_hq.pl_match import PLMatchResult
from tens_hq.radar_handoff import RadarHandoff, RadarHandoffClaims
from tens_hq.staffing_whatif import StaffingWhatIfInput, WhatIfMode, assess_staffing_whatif
from tens_hq.packet_export import (
    MANIFEST_EMPTY_NOTE,
    PACKET_EXPORT_TITLE,
    SectionEntry,
    SourceEntry,
    assemble_packet_export,
    derive_section_ledger,
    derive_source_manifest,
    packet_export_filename,
)


# --- Fixtures ------------------------------------------------------------


def _cf(**overrides: object) -> ContractFactsRecord:
    base = dict(
        piid="47QRAA24D0012",
        generated_unique_award_id="CONT_AWD_X",
        award_type_code="D",
        award_type_description="DEFINITIVE CONTRACT",
        category="contract",
        date_signed="2024-06-01",
        total_obligation=100000.0,
        base_and_all_options=250000.0,
        period_start_date="2024-06-01",
        period_end_date="2025-05-31",
        period_potential_end_date="2028-05-31 00:00:00",
        toptier_agency_name="General Services Administration",
        subagency_name="Public Buildings Service",
        recipient_name="EXAMPLEWORKS SERVICES LLC",
        recipient_uei="EXMP1234ABC7",
        recipient_business_categories=("Small Business",),
        set_aside_code="SBA",
        set_aside_description="SMALL BUSINESS SET ASIDE",
        extent_competed_code="D",
        extent_competed_description="FULL AND OPEN COMPETITION AFTER EXCLUSION OF SOURCES",
        number_of_offers_received=3,
        naics_code="561720",
        naics_description="JANITORIAL SERVICES",
        psc_code="S201",
        psc_description="HOUSEKEEPING",
        description="CUSTODIAL SUPPORT SERVICES",
        pop_city_name="FORT BELVOIR",
        pop_county_name="FAIRFAX",
        pop_state_code="VA",
        pop_country_code="USA",
        source_url="https://api.usaspending.gov/api/v2/awards/CONT_AWD_X/",
        retrieved_at="2026-07-20T12:00:00+00:00",
    )
    base.update(overrides)
    return ContractFactsRecord(**base)  # type: ignore[arg-type]


def _sub(*records: SubawardRecord, truncated: bool = False) -> SubawardsResult:
    return SubawardsResult(
        award_generated_internal_id="CONT_AWD_X",
        records=records,
        truncated=truncated,
        source_url="https://api.usaspending.gov/api/v2/subawards/",
        retrieved_at="2026-07-20T12:05:00+00:00",
    )


def _geo() -> GeographyRecord:
    return GeographyRecord(
        county_name="Denver County, Colorado",
        state_code="CO",
        state_fips="08",
        county_fips="031",
        total_population=705576,
        with_disability=78655,
        disability_percent=11.1,
        acs_survey="ACS 5-Year Estimates, Subject Table S1810 (Disability Characteristics)",
        acs_vintage_year=2022,
        source_url="https://api.census.gov/data/2022/acs/acs5/subject?get=NAME,S1810_C02_001E&for=county:031&in=state:08",
        retrieved_at="2026-07-18T14:30:00+00:00",
    )


def _pl(*, source_label: str | None = "worksheet.xlsx", retrieved_at: str | None = "2026-07-15", synthetic: bool = False) -> PLMatchResult:
    return PLMatchResult(
        city="Denver",
        state="CO",
        queried_service_type="Custodial",
        source_label=source_label,
        retrieved_at=retrieved_at,
        synthetic_sample=synthetic,
        service_type_matches=(),
        same_location_other=(),
    )


def _pl_notices(
    *,
    term: str | None = None,
    truncated: bool = False,
    count_total: int | None = None,
    records: tuple[FRNoticeRecord, ...] | None = None,
) -> PLNoticesResult:
    if records is None:
        records = (
            FRNoticeRecord(
                title="Procurement List; Proposed Deletions",
                document_number="2026-14305",
                publication_date="2026-07-16",
                html_url="https://www.federalregister.gov/documents/2026/07/16/2026-14305",
                notice_type="Notice",
            ),
        )
    if count_total is None:
        count_total = 20 if truncated else len(records)
    return PLNoticesResult(
        records=records,
        count_total=count_total,
        truncated=truncated,
        search_term=term,
        source_url="https://www.federalregister.gov/api/v1/documents.json?per_page=20",
        retrieved_at="2026-07-21T18:00:00+00:00",
    )


def _handoff(*, synthetic: bool = False) -> RadarHandoff:
    return RadarHandoff(
        schema_version="radar-handoff/v1",
        snapshot_date="2026-07-15",
        piid="47QRAA24D0012",
        radar_source_label="GovConRadar 2.8.0",
        synthetic_sample=synthetic,
        claims=RadarHandoffClaims(),
        unknown_field_count=0,
    )


def _staffing_computed():
    return assess_staffing_whatif(
        StaffingWhatIfInput(
            mode=WhatIfMode.HOURS,
            baseline_qualifying_hours=750.0,
            baseline_total_hours=1000.0,
            scenario_total_hours=200.0,
            scenario_qualifying_count=100.0,
        )
    )


def _staffing_cannot_compute():
    return assess_staffing_whatif(StaffingWhatIfInput(mode=WhatIfMode.HOURS))


_AS_OF = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


# --- Section ledger: fixed shape / order ----------------------------------


def test_ledger_has_eleven_rows_in_fixed_packet_order() -> None:
    ledger = derive_section_ledger(
        eligibility=None,
        contract_facts=None,
        geography=None,
        pl_matches=None,
        subawards=None,
        directory_agency_names=None,
    )
    names = [row.name for row in ledger]
    assert names == [
        "Origin (Radar handoff)",
        "Eligibility gate",
        "Contract Facts (live)",
        "Contract Facts (analyst-entered)",
        "Capture window",
        "Incumbent & teaming leads / PL-impact",
        "Staffing what-if",
        "Geography (ACS)",
        "PL cross-reference (R2b)",
        "Procurement List activity (Federal Register)",
        "R2a determination-support map",
    ]


def test_ledger_all_absent_render_is_honest_about_every_row() -> None:
    ledger = derive_section_ledger(
        eligibility=None,
        contract_facts=None,
        geography=None,
        pl_matches=None,
        subawards=None,
        directory_agency_names=None,
    )
    by_name = {row.name: row for row in ledger}
    assert by_name["Origin (Radar handoff)"].included is False
    assert "No handoff attached" in by_name["Origin (Radar handoff)"].basis
    assert by_name["Eligibility gate"].included is False
    assert by_name["Contract Facts (live)"].included is False
    # This row always renders -- it needs no evidence beyond the paste itself.
    assert by_name["Contract Facts (analyst-entered)"].included is True
    assert by_name["Capture window"].included is False
    assert by_name["Incumbent & teaming leads / PL-impact"].included is False
    assert by_name["Staffing what-if"].included is False
    assert "No baseline entered" in by_name["Staffing what-if"].basis
    # The builder renders Geography UNCONDITIONALLY (placeholder when nothing
    # was retrieved), so the ledger must call it included -- "Not included"
    # would misdescribe the document (adversarial-verify finding).
    assert by_name["Geography (ACS)"].included is True
    assert "placeholder" in by_name["Geography (ACS)"].basis
    assert "not yet pulled" in by_name["Geography (ACS)"].basis
    assert by_name["PL cross-reference (R2b)"].included is False
    assert by_name["Procurement List activity (Federal Register)"].included is False
    assert (
        "No Federal Register pull attached"
        in by_name["Procurement List activity (Federal Register)"].basis
    )
    # The R2a map is ALWAYS included -- it renders unconditionally,
    # routing whatever evidence is attached (or the honest absence line
    # when nothing is) onto the four suitability criteria.
    assert by_name["R2a determination-support map"].included is True
    # Every absent basis is evidence-absence, never a claim about the contract.
    for row in ledger:
        if not row.included:
            assert row.basis.strip()
            assert "no data" not in row.basis.lower()
            assert "none exists" not in row.basis.lower()


def test_ledger_everything_attached_all_included() -> None:
    cf = _cf()
    ledger = derive_section_ledger(
        eligibility=assess_eligibility("SBA"),
        contract_facts=cf,
        geography=_geo(),
        pl_matches=_pl(),
        subawards=_sub(SubawardRecord("1", "Sub Co", 100.0, "2025-01-01", "d")),
        directory_agency_names=["Sub Co"],
        handoff_attached=True,
        handoff_piid_matched=True,
        staffing=_staffing_computed(),
        pl_notices=_pl_notices(),
    )
    assert all(row.included for row in ledger)
    leads_row = next(r for r in ledger if r.name == "Incumbent & teaming leads / PL-impact")
    assert "facts + subawards + directory" in leads_row.basis


# --- PL activity (Federal Register) row: attached tracks "was it pulled" ---


def test_pl_notices_row_not_included_when_none() -> None:
    row = next(
        r
        for r in derive_section_ledger(
            eligibility=None,
            contract_facts=None,
            geography=None,
            pl_matches=None,
            subawards=None,
            directory_agency_names=None,
        )
        if r.name == "Procurement List activity (Federal Register)"
    )
    assert row.included is False
    assert row.basis == "No Federal Register pull attached."


def test_pl_notices_row_included_even_with_zero_records() -> None:
    # A real, empty pull (0 notices matched) is still an attached pull -- the
    # ledger row tracks "was it pulled," never "did it find anything," the
    # same discipline the R2b row already holds.
    empty = _pl_notices(records=(), truncated=False, count_total=0)
    row = next(
        r
        for r in derive_section_ledger(
            eligibility=None,
            contract_facts=None,
            geography=None,
            pl_matches=None,
            subawards=None,
            directory_agency_names=None,
            pl_notices=empty,
        )
        if r.name == "Procurement List activity (Federal Register)"
    )
    assert row.included is True


def test_ledger_order_pins_r2b_before_pl_activity_before_r2a_map() -> None:
    ledger = derive_section_ledger(
        eligibility=None,
        contract_facts=None,
        geography=None,
        pl_matches=_pl(),
        subawards=None,
        directory_agency_names=None,
        pl_notices=_pl_notices(),
    )
    names = [row.name for row in ledger]
    assert names.index("PL cross-reference (R2b)") < names.index(
        "Procurement List activity (Federal Register)"
    )
    assert names.index("Procurement List activity (Federal Register)") < names.index(
        "R2a determination-support map"
    )


# --- Staffing what-if row: attached tracks "was a baseline entered" --------


def test_staffing_row_not_included_when_none() -> None:
    row = next(
        r
        for r in derive_section_ledger(
            eligibility=None,
            contract_facts=None,
            geography=None,
            pl_matches=None,
            subawards=None,
            directory_agency_names=None,
        )
        if r.name == "Staffing what-if"
    )
    assert row.included is False
    assert row.basis == "No baseline entered."


def test_staffing_row_included_when_computed() -> None:
    row = next(
        r
        for r in derive_section_ledger(
            eligibility=None,
            contract_facts=None,
            geography=None,
            pl_matches=None,
            subawards=None,
            directory_agency_names=None,
            staffing=_staffing_computed(),
        )
        if r.name == "Staffing what-if"
    )
    assert row.included is True


def test_staffing_row_included_even_when_cannot_compute() -> None:
    # A CANNOT_COMPUTE result (a partial baseline) is still an ENTERED
    # baseline -- the section still renders the honest partial-entry
    # message, so the ledger row is still included (tracks "was a baseline
    # entered," never "did it validate").
    row = next(
        r
        for r in derive_section_ledger(
            eligibility=None,
            contract_facts=None,
            geography=None,
            pl_matches=None,
            subawards=None,
            directory_agency_names=None,
            staffing=_staffing_cannot_compute(),
        )
        if r.name == "Staffing what-if"
    )
    assert row.included is True


# --- Origin (Radar handoff) row: the three honest bases (D7) ---------------


def test_handoff_row_not_attached() -> None:
    row = next(
        r
        for r in derive_section_ledger(
            eligibility=None,
            contract_facts=None,
            geography=None,
            pl_matches=None,
            subawards=None,
            directory_agency_names=None,
        )
        if r.name == "Origin (Radar handoff)"
    )
    assert row.included is False
    assert "No handoff attached" in row.basis


def test_handoff_row_attached_but_piid_mismatched() -> None:
    row = next(
        r
        for r in derive_section_ledger(
            eligibility=None,
            contract_facts=None,
            geography=None,
            pl_matches=None,
            subawards=None,
            directory_agency_names=None,
            handoff_attached=True,
            handoff_piid_matched=False,
        )
        if r.name == "Origin (Radar handoff)"
    )
    assert row.included is False
    assert "no longer matches this packet's current PIID" in row.basis


def test_handoff_row_attached_and_matched() -> None:
    row = next(
        r
        for r in derive_section_ledger(
            eligibility=None,
            contract_facts=None,
            geography=None,
            pl_matches=None,
            subawards=None,
            directory_agency_names=None,
            handoff_attached=True,
            handoff_piid_matched=True,
        )
        if r.name == "Origin (Radar handoff)"
    )
    assert row.included is True


def test_leads_row_evidence_text_facts_only() -> None:
    row = next(
        r
        for r in derive_section_ledger(
            eligibility=None,
            contract_facts=_cf(),
            geography=None,
            pl_matches=None,
            subawards=None,
            directory_agency_names=None,
        )
        if r.name == "Incumbent & teaming leads / PL-impact"
    )
    assert row.included is True
    assert "facts only" in row.basis


def test_leads_row_evidence_text_facts_plus_subawards() -> None:
    row = next(
        r
        for r in derive_section_ledger(
            eligibility=None,
            contract_facts=_cf(),
            geography=None,
            pl_matches=None,
            subawards=_sub(),
            directory_agency_names=None,
        )
        if r.name == "Incumbent & teaming leads / PL-impact"
    )
    assert "facts + subawards" in row.basis
    assert "directory" not in row.basis


# --- Pinned predicate #1: the gate row ------------------------------------


def test_gate_row_pinned_predicate_contract_facts_present_eligibility_none() -> None:
    # Required test per the audit pin: contract_facts present + eligibility=None
    # -> gate row included with a retrieved-live basis.
    ledger = derive_section_ledger(
        eligibility=None,
        contract_facts=_cf(),
        geography=None,
        pl_matches=None,
        subawards=None,
        directory_agency_names=None,
    )
    gate_row = next(r for r in ledger if r.name == "Eligibility gate")
    assert gate_row.included is True
    assert "live" in gate_row.basis.lower() or "retrieved" in gate_row.basis.lower()
    assert "analyst-entered" not in gate_row.basis.lower()


def test_gate_row_analyst_entered_only_when_no_live_facts() -> None:
    gate = assess_eligibility("SBA")
    ledger = derive_section_ledger(
        eligibility=gate,
        contract_facts=None,
        geography=None,
        pl_matches=None,
        subawards=None,
        directory_agency_names=None,
    )
    gate_row = next(r for r in ledger if r.name == "Eligibility gate")
    assert gate_row.included is True
    assert "analyst-entered" in gate_row.basis.lower()


def test_gate_row_analyst_entered_still_wins_wording_for_blank_typed_value() -> None:
    # assess_eligibility("") still returns a real (non-None) EligibilityGate
    # object (UNKNOWN state) -- the ledger cares about "was a gate object
    # supplied", not its internal state.
    gate = assess_eligibility("")
    ledger = derive_section_ledger(
        eligibility=gate,
        contract_facts=None,
        geography=None,
        pl_matches=None,
        subawards=None,
        directory_agency_names=None,
    )
    gate_row = next(r for r in ledger if r.name == "Eligibility gate")
    assert gate_row.included is True


def test_gate_row_not_included_when_both_absent() -> None:
    ledger = derive_section_ledger(
        eligibility=None,
        contract_facts=None,
        geography=None,
        pl_matches=None,
        subawards=None,
        directory_agency_names=None,
    )
    gate_row = next(r for r in ledger if r.name == "Eligibility gate")
    assert gate_row.included is False


def test_gate_row_live_facts_win_over_a_supplied_analyst_gate() -> None:
    # Both supplied: the builder's own precedent is that live facts win.
    gate = assess_eligibility("SBA")
    ledger = derive_section_ledger(
        eligibility=gate,
        contract_facts=_cf(),
        geography=None,
        pl_matches=None,
        subawards=None,
        directory_agency_names=None,
    )
    gate_row = next(r for r in ledger if r.name == "Eligibility gate")
    assert gate_row.included is True
    assert "analyst-entered" not in gate_row.basis.lower()


# --- Source manifest: order, fields, absence -------------------------------


def test_manifest_all_absent_is_empty() -> None:
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
    )
    assert manifest == ()


def test_manifest_everything_attached_deterministic_order() -> None:
    cf = _cf()
    manifest = derive_source_manifest(
        contract_facts=cf,
        subawards=_sub(SubawardRecord("1", "Sub Co", 100.0, "2025-01-01", "d")),
        geography=_geo(),
        pl_matches=_pl(),
        directory_source_label="npa_directory.xlsx",
        set_aside_analyst_value="SBA",  # ignored: contract_facts is attached
        staffing=_staffing_computed(),
        pl_notices=_pl_notices(),
    )
    sources = [entry.source for entry in manifest]
    assert sources == [
        "Contract Facts (live, USAspending award detail)",
        "Subaward records (live, USAspending FSRS/FFATA)",
        "AbilityOne NPA directory (analyst upload)",
        "Staffing what-if inputs (analyst-entered)",
        "ACS geography context (Census, live)",
        "Procurement List cross-reference workbook (R2b)",
        "Procurement List activity (live, Federal Register)",
    ]
    # Re-deriving is byte-identical (no dict/set nondeterminism).
    again = derive_source_manifest(
        contract_facts=cf,
        subawards=_sub(SubawardRecord("1", "Sub Co", 100.0, "2025-01-01", "d")),
        geography=_geo(),
        pl_matches=_pl(),
        directory_source_label="npa_directory.xlsx",
        set_aside_analyst_value="SBA",
        staffing=_staffing_computed(),
        pl_notices=_pl_notices(),
    )
    assert manifest == again


def test_manifest_matched_handoff_row_sorts_first_ahead_of_live_rows() -> None:
    # Locks the Origin-first placement (D3/D7) in COMBINATION with every other
    # attached source, not just in isolation.
    manifest = derive_source_manifest(
        contract_facts=_cf(),
        subawards=_sub(SubawardRecord("1", "Sub Co", 100.0, "2025-01-01", "d")),
        geography=_geo(),
        pl_matches=_pl(),
        directory_source_label="npa_directory.xlsx",
        set_aside_analyst_value=None,
        handoff=_handoff(),
        handoff_source_label="sample_radar_handoff.json",
        handoff_piid_matched=True,
        staffing=_staffing_computed(),
        pl_notices=_pl_notices(),
    )
    sources = [entry.source for entry in manifest]
    assert sources == [
        "Radar handoff (analyst upload)",
        "Contract Facts (live, USAspending award detail)",
        "Subaward records (live, USAspending FSRS/FFATA)",
        "AbilityOne NPA directory (analyst upload)",
        "Staffing what-if inputs (analyst-entered)",
        "ACS geography context (Census, live)",
        "Procurement List cross-reference workbook (R2b)",
        "Procurement List activity (live, Federal Register)",
    ]


def test_manifest_contract_facts_row_assurance_and_reference() -> None:
    cf = _cf()
    manifest = derive_source_manifest(
        contract_facts=cf,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
    )
    assert len(manifest) == 1
    row = manifest[0]
    assert row.assurance == "API_RETRIEVED"
    assert row.reference == cf.source_url
    assert row.retrieved_at == cf.retrieved_at


def test_manifest_subawards_truncated_note() -> None:
    manifest = derive_source_manifest(
        contract_facts=_cf(),
        subawards=_sub(SubawardRecord("1", "Sub Co", 100.0, "2025-01-01", "d"), truncated=True),
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
    )
    sub_row = next(r for r in manifest if r.source.startswith("Subaward"))
    assert "more subaward records exist" in sub_row.notes.lower()


def test_manifest_geography_row_carries_vintage_note() -> None:
    geo = _geo()
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=geo,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
    )
    row = manifest[0]
    assert row.assurance == "API_RETRIEVED"
    assert "2022" in row.notes


def test_manifest_pl_synthetic_sample_carries_exact_note() -> None:
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=_pl(synthetic=True),
        directory_source_label=None,
        set_aside_analyst_value=None,
    )
    row = manifest[0]
    assert row.assurance == "USER_ATTESTED"
    assert "SYNTHETIC example workbook" in row.notes
    assert "not real Procurement List data" in row.notes


def test_manifest_pl_non_synthetic_carries_no_synthetic_note() -> None:
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=_pl(synthetic=False),
        directory_source_label=None,
        set_aside_analyst_value=None,
    )
    row = manifest[0]
    assert "SYNTHETIC" not in row.notes


def test_manifest_pl_missing_retrieved_at_renders_not_supplied() -> None:
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=_pl(retrieved_at=None),
        directory_source_label=None,
        set_aside_analyst_value=None,
    )
    row = manifest[0]
    assert row.retrieved_at == "Not supplied (analyst attestation absent)"


# --- PL activity (Federal Register) manifest row (ADR-023, D4) -------------


def test_manifest_pl_notices_row_absent_when_none() -> None:
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
    )
    assert manifest == ()


def test_manifest_pl_notices_row_present_api_retrieved() -> None:
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
        pl_notices=_pl_notices(),
    )
    assert len(manifest) == 1
    row = manifest[0]
    assert row.source == "Procurement List activity (live, Federal Register)"
    assert row.assurance == "API_RETRIEVED"
    assert row.reference == "https://www.federalregister.gov/api/v1/documents.json?per_page=20"
    assert row.retrieved_at == "2026-07-21T18:00:00+00:00"


def test_manifest_pl_notices_notes_carry_truncation_and_search_term_together() -> None:
    # D4: notes carry BOTH the truncation disclosure AND the search term when
    # both apply to the same pull -- not either/or.
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
        pl_notices=_pl_notices(term="Procurement List", truncated=True, count_total=45),
    )
    row = manifest[0]
    assert "newest" in row.notes.lower()
    assert "45" in row.notes
    assert "Procurement List" in row.notes


def test_manifest_pl_notices_notes_empty_when_not_truncated_and_no_term() -> None:
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
        pl_notices=_pl_notices(truncated=False, count_total=1),
    )
    row = manifest[0]
    assert row.notes == ""


def test_manifest_directory_row_has_no_retrieved_at_and_is_user_attested() -> None:
    manifest = derive_source_manifest(
        contract_facts=_cf(),
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label="npa_directory.xlsx",
        set_aside_analyst_value=None,
    )
    by_source = {entry.source: entry for entry in manifest}
    row = by_source["AbilityOne NPA directory (analyst upload)"]
    assert row.assurance == "USER_ATTESTED"
    assert row.retrieved_at == "Not supplied (analyst attestation absent)"
    assert row.reference == "npa_directory.xlsx"


def test_manifest_directory_row_requires_contract_facts_no_phantom_source() -> None:
    # Without contract facts the leads section never renders, so the uploaded
    # directory contributed nothing to the document -- listing it would cite a
    # phantom source (adversarial-verify finding).
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label="npa_directory.xlsx",
        set_aside_analyst_value=None,
    )
    assert manifest == ()


def test_manifest_blank_directory_label_is_not_attached() -> None:
    manifest = derive_source_manifest(
        contract_facts=_cf(),
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label="   ",
        set_aside_analyst_value=None,
    )
    assert all(
        entry.source != "AbilityOne NPA directory (analyst upload)" for entry in manifest
    )


# --- Staffing what-if manifest row: attached tracks "was a baseline entered" -


def test_manifest_staffing_row_absent_when_none() -> None:
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
    )
    assert manifest == ()


def test_manifest_staffing_row_present_and_user_attested() -> None:
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
        staffing=_staffing_computed(),
    )
    assert len(manifest) == 1
    row = manifest[0]
    assert row.source == "Staffing what-if inputs (analyst-entered)"
    assert row.assurance == "USER_ATTESTED"
    assert "HOURS" in row.reference
    assert row.retrieved_at == "Not supplied (analyst attestation absent)"


def test_manifest_staffing_row_present_even_when_cannot_compute() -> None:
    # No live-supersession branch: the staffing inputs are never superseded
    # by anything else in the packet -- attached tracks "was a baseline
    # entered," same as the ledger row.
    manifest = derive_source_manifest(
        contract_facts=_cf(),
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
        staffing=_staffing_cannot_compute(),
    )
    assert any(entry.source == "Staffing what-if inputs (analyst-entered)" for entry in manifest)


# --- Radar-handoff manifest row: attached-AND-matched only (D7) -----------


def test_manifest_handoff_row_absent_when_no_handoff() -> None:
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
    )
    assert manifest == ()


def test_manifest_handoff_row_absent_when_attached_but_mismatched() -> None:
    # A handoff attached but no longer PIID-matched influenced nothing in
    # this render -- listing it would cite a phantom source, the same rule
    # the directory row already follows.
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
        handoff=_handoff(),
        handoff_source_label="sample_radar_handoff.json",
        handoff_piid_matched=False,
    )
    assert manifest == ()


def test_manifest_handoff_row_present_when_attached_and_matched() -> None:
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
        handoff=_handoff(),
        handoff_source_label="sample_radar_handoff.json",
        handoff_piid_matched=True,
    )
    assert len(manifest) == 1
    row = manifest[0]
    assert row.source == "Radar handoff (analyst upload)"
    assert row.reference == "sample_radar_handoff.json"
    assert row.retrieved_at == "2026-07-15"
    assert row.assurance == "USER_ATTESTED"
    assert "not independently verified" in row.notes


def test_manifest_handoff_row_synthetic_note() -> None:
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
        handoff=_handoff(synthetic=True),
        handoff_source_label="sample_radar_handoff.json",
        handoff_piid_matched=True,
    )
    row = manifest[0]
    assert "SYNTHETIC example handoff" in row.notes


def test_manifest_handoff_row_missing_label_falls_back_to_not_supplied() -> None:
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
        handoff=_handoff(),
        handoff_source_label=None,
        handoff_piid_matched=True,
    )
    row = manifest[0]
    assert row.reference == "Not supplied (analyst attestation absent)"


# --- Pinned predicate #2: the analyst-set-aside manifest row ---------------


def test_manifest_analyst_set_aside_row_pinned_predicate_present() -> None:
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value="SBA",
    )
    assert len(manifest) == 1
    row = manifest[0]
    assert row.source == "Set-aside status (analyst-entered)"
    assert row.assurance == "USER_ATTESTED"
    assert row.reference == "SBA"


def test_manifest_blank_set_aside_and_no_facts_yields_no_row() -> None:
    # Required test per the audit pin: blank set-aside + no facts -> no
    # set-aside manifest row (blank is not an attached source).
    manifest = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value="   ",
    )
    assert manifest == ()

    manifest_none = derive_source_manifest(
        contract_facts=None,
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value=None,
    )
    assert manifest_none == ()


def test_manifest_set_aside_row_absent_when_contract_facts_present() -> None:
    # A typed value is ignored once live facts are attached (the gate no
    # longer runs off it), so it must not become a manifest row either.
    manifest = derive_source_manifest(
        contract_facts=_cf(),
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=None,
        set_aside_analyst_value="SBA",
    )
    assert not any(row.source.startswith("Set-aside status") for row in manifest)


# --- Filename safety --------------------------------------------------------


@pytest.mark.parametrize(
    "piid,expect_contains,forbid",
    [
        ("47QRAA24D0012", "47QRAA24D0012", None),
        ("", None, None),
        ("   ", None, None),
    ],
)
def test_packet_export_filename_normal_and_empty(piid, expect_contains, forbid) -> None:
    name = packet_export_filename(piid, _AS_OF)
    assert name.startswith("opportunity-packet-")
    assert name.endswith("-20260720.md")
    if expect_contains:
        assert expect_contains in name
    else:
        assert "no-piid" in name


def test_packet_export_filename_path_traversal_is_inert() -> None:
    name = packet_export_filename("../../etc/passwd", _AS_OF)
    # No path separator or leading/trailing dot survives into the sanitized
    # segment -- "../../etc/passwd" collapses to "etc-passwd".
    segment = name[len("opportunity-packet-") : -len("-20260720.md")]
    assert "/" not in segment
    assert "\\" not in segment
    assert not segment.startswith(".")
    assert not segment.endswith(".")
    assert segment == "etc-passwd"


def test_packet_export_filename_reserved_device_name_is_character_safe() -> None:
    # CON has no disallowed characters, so the sanitizer (a character filter,
    # not an OS reserved-name blocklist) passes it through unchanged.
    name = packet_export_filename("CON", _AS_OF)
    assert name == "opportunity-packet-CON-20260720.md"


def test_packet_export_filename_spaces_collapse_to_single_dash() -> None:
    name = packet_export_filename("A   B", _AS_OF)
    segment = name[len("opportunity-packet-") : -len("-20260720.md")]
    assert segment == "A-B"


def test_packet_export_filename_unicode_is_stripped_to_ascii_safe() -> None:
    name = packet_export_filename("PIID-日本語", _AS_OF)
    segment = name[len("opportunity-packet-") : -len("-20260720.md")]
    assert all(ch.isascii() for ch in segment)
    assert segment == "PIID"


def test_packet_export_filename_200_char_string_is_capped_at_40() -> None:
    name = packet_export_filename("A" * 200, _AS_OF)
    segment = name[len("opportunity-packet-") : -len("-20260720.md")]
    assert len(segment) <= 40


def test_packet_export_filename_never_ends_on_bare_separator_after_cap() -> None:
    # 39 safe chars + a hyphen landing exactly at the 40-char cut boundary,
    # followed by more content -- the cap must not leave a trailing "-".
    hostile = ("A" * 39) + "-" + ("B" * 10)
    name = packet_export_filename(hostile, _AS_OF)
    segment = name[len("opportunity-packet-") : -len("-20260720.md")]
    assert not segment.endswith("-")
    assert not segment.endswith(".")
    assert len(segment) <= 40


def test_packet_export_filename_as_of_drives_date_not_clock() -> None:
    later = datetime(2030, 1, 2, tzinfo=timezone.utc)
    earlier = datetime(2020, 12, 31, tzinfo=timezone.utc)
    assert packet_export_filename("X", later).endswith("-20300102.md")
    assert packet_export_filename("X", earlier).endswith("-20201231.md")


# --- Assembler: body-verbatim, escaping, absence wording, no analysis -----


def test_body_verbatim_invariant() -> None:
    body = "# Opportunity Packet\n\n- As of: 2026-07-20T12:00:00+00:00\n- Some fact.\n"
    export_doc = assemble_packet_export(
        body_markdown=body,
        piid="X",
        county="Denver",
        state="CO",
        ledger=derive_section_ledger(
            eligibility=None, contract_facts=None, geography=None, pl_matches=None, subawards=None, directory_agency_names=None
        ),
        manifest=(),
        as_of=_AS_OF,
    )
    assert body in export_doc


def test_export_title_and_appendix_headers_present() -> None:
    export_doc = assemble_packet_export(
        body_markdown="body\n",
        piid="X",
        county="Denver",
        state="CO",
        ledger=derive_section_ledger(
            eligibility=None, contract_facts=None, geography=None, pl_matches=None, subawards=None, directory_agency_names=None
        ),
        manifest=(),
        as_of=_AS_OF,
    )
    assert PACKET_EXPORT_TITLE in export_doc
    assert "## Section ledger" in export_doc
    assert "## Source manifest" in export_doc
    assert PACKET_FRAMING in export_doc


def test_empty_manifest_renders_honest_fallback_line() -> None:
    export_doc = assemble_packet_export(
        body_markdown="body\n",
        piid="X",
        county="Denver",
        state="CO",
        ledger=derive_section_ledger(
            eligibility=None, contract_facts=None, geography=None, pl_matches=None, subawards=None, directory_agency_names=None
        ),
        manifest=(),
        as_of=_AS_OF,
    )
    assert MANIFEST_EMPTY_NOTE in export_doc


def test_hostile_manifest_reference_is_two_layer_escaped_in_table_cell() -> None:
    hostile = "[x](http://evil)|EXTRA"
    manifest = (
        SourceEntry(
            source="AbilityOne NPA directory (analyst upload)",
            reference=hostile,
            retrieved_at="Not supplied (analyst attestation absent)",
            assurance="USER_ATTESTED",
            notes="",
        ),
    )
    export_doc = assemble_packet_export(
        body_markdown="body\n",
        piid="X",
        county="Denver",
        state="CO",
        ledger=(),
        manifest=manifest,
        as_of=_AS_OF,
    )
    assert hostile not in export_doc
    assert "](http://evil)" not in export_doc
    # The pipe must not survive raw inside the rendered cell (it would break
    # the table); it is replaced with "/" after markdown-escaping.
    assert "\\)/EXTRA" in export_doc


def test_manifest_bracketed_source_url_is_autolinked_not_backslash_escaped() -> None:
    # §5.8: a cited source_url (FR here, but this is the one render point
    # shared by contract facts/ACS/subawards too) legitimately carries "[]"
    # in query params. It must paste-and-resolve cleanly from the downloaded
    # export -- no visible backslash escapes -- while a non-URL reference
    # (e.g. an uploaded filename) still routes through the escaped `_cell`.
    bracketed_url = (
        "https://www.federalregister.gov/api/v1/documents.json"
        "?conditions[type][]=NOTICE&per_page=20"
    )
    manifest = (
        SourceEntry(
            source="Procurement List activity (live, Federal Register)",
            reference=bracketed_url,
            retrieved_at="2026-07-21T18:00:00+00:00",
            assurance="API_RETRIEVED",
            notes="",
        ),
        SourceEntry(
            source="AbilityOne NPA directory (analyst upload)",
            reference="npa_directory[2026].xlsx",
            retrieved_at="Not supplied (analyst attestation absent)",
            assurance="USER_ATTESTED",
            notes="",
        ),
    )
    export_doc = assemble_packet_export(
        body_markdown="body\n",
        piid="X",
        county="Denver",
        state="CO",
        ledger=(),
        manifest=manifest,
        as_of=_AS_OF,
    )
    # The URL's own brackets are never backslash-escaped, and it pastes
    # verbatim inside a CommonMark autolink.
    assert "conditions\\[type\\]\\[\\]" not in export_doc
    assert "conditions[type][]=NOTICE" in export_doc
    assert f"<{bracketed_url}>" in export_doc
    # The non-URL filename reference is unaffected -- still escaped, not autolinked.
    assert "npa_directory\\[2026\\].xlsx" in export_doc
    assert "<npa_directory" not in export_doc


def test_hostile_piid_and_county_are_escaped_in_header() -> None:
    export_doc = assemble_packet_export(
        body_markdown="body\n",
        piid="[evil](http://x)",
        county="[c](http://y)",
        state="CO",
        ledger=(),
        manifest=(),
        as_of=_AS_OF,
    )
    assert "[evil](http://x)" not in export_doc
    assert "[c](http://y)" not in export_doc


def test_no_score_or_directive_vocabulary_in_appendices() -> None:
    export_doc = assemble_packet_export(
        body_markdown="body\n",
        piid="X",
        county="Denver",
        state="CO",
        ledger=derive_section_ledger(
            eligibility=assess_eligibility("SBA"),
            contract_facts=_cf(),
            geography=_geo(),
            pl_matches=_pl(),
            subawards=_sub(SubawardRecord("1", "Sub Co", 100.0, "2025-01-01", "d")),
            directory_agency_names=["Sub Co"],
        ),
        manifest=derive_source_manifest(
            contract_facts=_cf(),
            subawards=_sub(SubawardRecord("1", "Sub Co", 100.0, "2025-01-01", "d")),
            geography=_geo(),
            pl_matches=_pl(),
            directory_source_label="npa.xlsx",
            set_aside_analyst_value=None,
        ),
        as_of=_AS_OF,
    )
    # Scope the sweep to the two NEW appendix sections (§3's "no new
    # analysis" invariant concerns them): the header carries the imported
    # PACKET_FRAMING/attestation disclaimers, which legitimately mention
    # "ranking"/"recommendation" as NEGATIONS ("no ranking... no
    # recommendation") and would otherwise false-positive this sweep.
    appendices = export_doc.split("## Section ledger", 1)[1].lower()
    for forbidden in ("score", "pwin", "/100", "bid/no-bid", "tier", "rank", "recommend", "pursue", "should bid", "reach out to"):
        assert forbidden not in appendices


def test_absence_rows_use_evidence_absence_wording_not_negative_claims() -> None:
    export_doc = assemble_packet_export(
        body_markdown="body\n",
        piid="X",
        county="Denver",
        state="CO",
        ledger=derive_section_ledger(
            eligibility=None, contract_facts=None, geography=None, pl_matches=None, subawards=None, directory_agency_names=None
        ),
        manifest=(),
        as_of=_AS_OF,
    )
    assert "no live contract-facts pull attached" in export_doc.lower()
    assert "no acs context retrieved" in export_doc.lower()
    assert "no PL workbook cross-referenced this render".lower() in export_doc.lower()
    assert "none exists" not in export_doc.lower()
    assert "no data" not in export_doc.lower()


def test_as_of_injection_two_datetimes_only_stamps_differ() -> None:
    ledger = derive_section_ledger(
        eligibility=None, contract_facts=None, geography=None, pl_matches=None, subawards=None, directory_agency_names=None
    )
    doc_a = assemble_packet_export(
        body_markdown="body\n", piid="X", county="Denver", state="CO", ledger=ledger, manifest=(), as_of=_AS_OF
    )
    other = datetime(2030, 3, 4, 5, 6, tzinfo=timezone.utc)
    doc_b = assemble_packet_export(
        body_markdown="body\n", piid="X", county="Denver", state="CO", ledger=ledger, manifest=(), as_of=other
    )
    assert doc_a != doc_b
    assert doc_a.replace(_AS_OF.isoformat(), "STAMP") == doc_b.replace(other.isoformat(), "STAMP")


def test_end_to_end_as_of_agrees_between_body_and_export_header() -> None:
    # Mirrors the wiring commit's single-resolved-as_of contract: the SAME
    # as_of fed to both the packet builder and the assembler must produce
    # matching "As of" stamps in the body and the export header.
    as_of = datetime(2026, 7, 20, 9, 30, tzinfo=timezone.utc)
    body = build_opportunity_packet_markdown(piid="X", county="Denver", state="CO", as_of=as_of)
    export_doc = assemble_packet_export(
        body_markdown=body,
        piid="X",
        county="Denver",
        state="CO",
        ledger=derive_section_ledger(
            eligibility=None, contract_facts=None, geography=None, pl_matches=None, subawards=None, directory_agency_names=None
        ),
        manifest=(),
        as_of=as_of,
    )
    assert export_doc.count(as_of.isoformat()) >= 2
    assert body in export_doc


def test_newline_in_manifest_reference_cannot_split_the_table_row() -> None:
    # A POSIX/browser-supplied upload filename may legally contain a newline;
    # unflattened it splits the manifest table row and injects attacker rows
    # (adversarial-verify finding). Line boundaries flatten to spaces BEFORE
    # escaping, so the rendered row stays on one physical line.
    hostile = "evil.xlsx |x\n| INJECTED | ROW | pwn | now |"
    manifest = derive_source_manifest(
        contract_facts=_cf(),
        subawards=None,
        geography=None,
        pl_matches=None,
        directory_source_label=hostile,
        set_aside_analyst_value=None,
    )
    export_doc = assemble_packet_export(
        body_markdown="BODY\n",
        piid="P",
        county="C",
        state="FL",
        ledger=derive_section_ledger(
            eligibility=None,
            contract_facts=_cf(),
            geography=None,
            pl_matches=None,
            subawards=None,
            directory_agency_names=None,
        ),
        manifest=manifest,
        as_of=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    directory_lines = [
        line for line in export_doc.splitlines() if "AbilityOne NPA directory" in line
    ]
    assert len(directory_lines) == 1
    # The whole hostile value lives inside that single line, pipes defused.
    assert "INJECTED" in directory_lines[0]
    assert "| INJECTED |" not in export_doc
    assert "\nINJECTED" not in export_doc


def test_newline_in_header_value_is_flattened() -> None:
    export_doc = assemble_packet_export(
        body_markdown="BODY\n",
        piid="PIID\nWITH\r\nBREAKS",
        county="C",
        state="FL",
        ledger=derive_section_ledger(
            eligibility=None,
            contract_facts=None,
            geography=None,
            pl_matches=None,
            subawards=None,
            directory_agency_names=None,
        ),
        manifest=(),
        as_of=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    piid_lines = [line for line in export_doc.splitlines() if "PIID" in line and "WITH" in line]
    assert len(piid_lines) == 1
    assert "PIID WITH BREAKS" in piid_lines[0]


# --- Counsel-gated C3/C4 absence guard over the WHOLE export ---------------
#
# test_r2a_map.py locks the R2a-map section's constants against counsel-gated
# C3/C4 copy; this widens the same guard (shared term list in
# tests/conftest.py) to the full packet body AND the complete export document
# -- stamped header, verbatim body, Section ledger, Source manifest -- in
# both the nothing-attached and everything-attached states. These renders
# exercise ONE branch of each section; the branch-independent net is the
# source sweep in test_counsel_gate_sweep.py, which checks the modules'
# whole source text (adversarial-verify MAJOR: single-branch renders let
# constants on other branches escape).


def _packet_body(*, everything: bool) -> str:
    return build_opportunity_packet_markdown(
        piid="47QRAA24D0012",
        county="Denver",
        state="CO",
        # everything=False still carries the UNKNOWN gate: bd_page always
        # passes a gate object (blank input renders the UNKNOWN copy), so a
        # gateless packet is a state the app never produces.
        eligibility=assess_eligibility("SBA" if everything else ""),
        geography=_geo() if everything else None,
        pl_matches=_pl() if everything else None,
        pl_notices=_pl_notices() if everything else None,
        contract_facts=_cf() if everything else None,
        subawards=_sub(SubawardRecord("1", "Sub Co", 100.0, "2025-01-01", "d"))
        if everything
        else None,
        directory_agency_names=("EXAMPLEWORKS SERVICES LLC",) if everything else None,
        radar_handoff=_handoff() if everything else None,
        staffing=_staffing_computed() if everything else None,
        as_of=_AS_OF,
    )


def _full_export_doc(*, everything: bool) -> str:
    cf = _cf() if everything else None
    subawards = (
        _sub(SubawardRecord("1", "Sub Co", 100.0, "2025-01-01", "d")) if everything else None
    )
    geography = _geo() if everything else None
    pl_matches = _pl() if everything else None
    pl_notices = _pl_notices() if everything else None
    staffing = _staffing_computed() if everything else None
    directory_names = ("EXAMPLEWORKS SERVICES LLC",) if everything else None
    ledger = derive_section_ledger(
        eligibility=assess_eligibility("SBA" if everything else ""),
        contract_facts=cf,
        geography=geography,
        pl_matches=pl_matches,
        subawards=subawards,
        directory_agency_names=directory_names,
        handoff_attached=everything,
        handoff_piid_matched=everything,
        staffing=staffing,
        pl_notices=pl_notices,
    )
    manifest = derive_source_manifest(
        contract_facts=cf,
        subawards=subawards,
        geography=geography,
        pl_matches=pl_matches,
        directory_source_label="npa_directory.xlsx" if everything else None,
        # everything=False keeps an analyst-typed set-aside so the
        # USER_ATTESTED manifest row (suppressed once live facts attach)
        # renders in at least one parametrization.
        set_aside_analyst_value="SBA",
        handoff=_handoff() if everything else None,
        handoff_source_label="sample_radar_handoff.json" if everything else None,
        handoff_piid_matched=everything,
        staffing=staffing,
        pl_notices=pl_notices,
    )
    return assemble_packet_export(
        body_markdown=_packet_body(everything=everything),
        piid="47QRAA24D0012",
        county="Denver",
        state="CO",
        ledger=ledger,
        manifest=manifest,
        as_of=_AS_OF,
    )


def test_full_export_body_contains_award_description_line() -> None:
    """The whole export preserves the live award description in its verbatim body."""

    export_doc = _full_export_doc(everything=True)
    assert (
        "- Award description (FPDS free text, as reported): CUSTODIAL SUPPORT SERVICES"
        in export_doc
    )


@pytest.mark.parametrize("everything", [False, True])
def test_no_counsel_gated_c3_c4_content_in_full_packet_body(everything: bool) -> None:
    assert counsel_gate_violations(_packet_body(everything=everything)) == []


@pytest.mark.parametrize("everything", [False, True])
def test_no_counsel_gated_c3_c4_content_in_full_export(everything: bool) -> None:
    assert counsel_gate_violations(_full_export_doc(everything=everything)) == []
