"""The cited Opportunity Packet surface (A1): Contract Facts + Geography context.

The packet is rendered by a pure function so it can be tested directly, fully
offline.  It must (1) present pasted identifiers as analyst-entered, (2) cite
the ACS geography figure with its source URL, retrieval date, and survey
vintage, (3) label geography as context, NOT candidate supply (N2/N4), and
(4) never render a score (N1).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from tens_hq.connectors import (
    ContractFactsRecord,
    FRNoticeRecord,
    GeographyRecord,
    PLNoticesResult,
    SubawardRecord,
    SubawardsResult,
)
from tens_hq.eligibility_gate import assess_eligibility
from tens_hq.opportunity_packet import build_opportunity_packet_markdown, geography_lines
from tens_hq.pl_match import PLMatchResult, PLServiceMatch
from tens_hq.radar_handoff import RadarHandoff, RadarHandoffClaims
from tens_hq.staffing_whatif import StaffingWhatIfInput, WhatIfMode, assess_staffing_whatif


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


def _geography() -> GeographyRecord:
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
        retrieved_at=datetime(2026, 7, 18, 14, 30, tzinfo=timezone.utc).isoformat(),
    )


def test_geography_upstream_strings_cannot_forge_markdown_structure() -> None:
    """ACS-derived strings render through the same flatten-then-escape _md as
    the live contract facts: a line break in an upstream county name (or any
    other ACS string) collapses into the bullet instead of forging a heading
    in the packet body and export."""

    hostile = replace(
        _geography(), county_name="Denver County\n## Forged geography heading"
    )
    lines = geography_lines(hostile)
    rendered = "\n".join(lines)
    assert not any(
        line.startswith("## Forged") for line in rendered.splitlines()
    )
    assert any(
        "Denver County ## Forged geography heading" in line for line in lines
    )


def test_packet_shows_contract_facts_as_analyst_entered() -> None:
    packet = build_opportunity_packet_markdown(
        piid="47QRAA24D0012", county="Denver", state="CO", geography=None
    )
    assert "47QRAA24D0012" in packet
    assert "Denver" in packet
    # The pasted identifiers are clearly labeled analyst-entered, not verified.
    assert "analyst-entered" in packet.lower()
    # With no geography pulled yet, the panel says so rather than inventing data.
    assert "not yet retrieved" in packet.lower()


def test_packet_cites_geography_with_source_and_retrieval_and_vintage() -> None:
    record = _geography()
    packet = build_opportunity_packet_markdown(
        piid="47QRAA24D0012", county="Denver", state="CO", geography=record
    )
    # The figure and its full citation are present.
    assert "78,655" in packet or "78655" in packet
    assert record.source_url in packet
    assert record.retrieved_at in packet
    assert "2022" in packet
    assert "S1810" in packet


def test_packet_labels_geography_as_context_not_candidate_supply() -> None:
    packet = build_opportunity_packet_markdown(
        piid="47QRAA24D0012", county="Denver", state="CO", geography=_geography()
    ).lower()
    assert "context" in packet
    # The N2/N4 disclaimer: this is not a supply/capacity/eligibility claim.
    assert "not a" in packet
    assert "candidate" in packet or "supply" in packet


def test_packet_contains_no_score() -> None:
    packet = build_opportunity_packet_markdown(
        piid="47QRAA24D0012", county="Denver", state="CO", geography=_geography()
    ).lower()
    # N1: no numeric feasibility/PWin/readiness score anywhere in the packet.
    assert "score" not in packet
    assert "pwin" not in packet
    assert "/100" not in packet
    assert "bid/no-bid" not in packet


# --- N6 eligibility gate section --------------------------------------------


def test_packet_eligibility_gate_precedes_contract_facts() -> None:
    packet = build_opportunity_packet_markdown(
        piid="47QRAA24D0012",
        county="Denver",
        state="CO",
        eligibility=assess_eligibility("8A"),
    )
    assert packet.index("## Eligibility gate") < packet.index("## Contract Facts")


def test_packet_without_eligibility_omits_gate() -> None:
    packet = build_opportunity_packet_markdown(
        piid="47QRAA24D0012", county="Denver", state="CO", eligibility=None
    )
    assert "## Eligibility gate" not in packet


# --- R2b Procurement List cross-reference section ----------------------------


def _pl_match(**overrides: object) -> PLServiceMatch:
    base = dict(
        cna="ExampleWorks CNA",
        service_type="Custodial",
        service_location="Denver, CO 80202",
        parsed_city="Denver",
        parsed_state="CO",
        parsed_zip="80202",
        mandatory_for_contracting_activity=True,
        source_row=7,
    )
    base.update(overrides)
    return PLServiceMatch(**base)  # type: ignore[arg-type]


def _pl_result(
    *,
    service_type_matches: tuple[PLServiceMatch, ...] = (),
    same_location_other: tuple[PLServiceMatch, ...] = (),
    queried_service_type: str | None = "Custodial",
    synthetic_sample: bool = False,
    source_label: str | None = "PL_Services_2026Q2.xlsx",
    retrieved_at: str | None = "2026-07-15",
) -> PLMatchResult:
    return PLMatchResult(
        city="Denver",
        state="CO",
        queried_service_type=queried_service_type,
        source_label=source_label,
        retrieved_at=retrieved_at,
        synthetic_sample=synthetic_sample,
        service_type_matches=service_type_matches,
        same_location_other=same_location_other,
    )


def test_packet_pl_section_contains_no_score() -> None:
    # N1 with the R2b section populated (the base no-score test renders WITHOUT
    # pl_matches, so this exercises the new render path explicitly). This guards
    # the renderer's OWN strings against manufacturing a rating; it does not
    # police workbook-supplied cell text, which is echoed verbatim under an
    # explicit "cited string fact, not a finding" caveat (and Markdown-escaped).
    packet = build_opportunity_packet_markdown(
        piid="47QRAA24D0012",
        county="Denver",
        state="CO",
        geography=_geography(),
        pl_matches=_pl_result(service_type_matches=(_pl_match(),), same_location_other=(_pl_match(service_type="Grounds Maintenance"),)),
    ).lower()
    assert "score" not in packet
    assert "pwin" not in packet
    assert "/100" not in packet
    assert "bid/no-bid" not in packet


def test_packet_without_pl_matches_omits_section() -> None:
    packet = build_opportunity_packet_markdown(
        piid="47QRAA24D0012", county="Denver", state="CO", geography=_geography()
    )
    assert "Procurement List cross-reference" not in packet


def test_packet_pl_non_convertibility_caveat_present() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        pl_matches=_pl_result(service_type_matches=(_pl_match(),)),
    ).lower()
    # B1: a match must never imply the pasted contract is convertible/winnable.
    assert "not evidence" in packet
    assert "convertible to the procurement list" in packet
    assert "winnable" in packet


def test_packet_pl_whose_line_and_cna_not_holder() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        pl_matches=_pl_result(service_type_matches=(_pl_match(cna="ExampleWorks CNA"),)),
    )
    # The whose-line gate + the CNA-is-not-the-holder clarification (M4).
    assert "does not name which nonprofit agency" in packet.lower()
    assert "not the performing agency" in packet.lower()
    # The CNA value is shown but explicitly labeled as the intermediary.
    assert "ExampleWorks CNA" in packet


def test_packet_pl_exact_match_is_a_string_fact() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        pl_matches=_pl_result(service_type_matches=(_pl_match(service_type="Custodial"),)),
    ).lower()
    # M1: a character-equal service type is a string fact, not a service match.
    assert "character-equal" in packet
    assert "not a same-service or capability finding" in packet


def test_packet_pl_cites_provenance_and_staleness() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        pl_matches=_pl_result(service_type_matches=(_pl_match(),)),
    )
    # N3/M2: source label, retrieval date, and the Federal Register staleness note.
    assert "PL_Services_2026Q2.xlsx" in packet
    assert "2026-07-15" in packet
    assert "Federal Register" in packet


def test_packet_pl_no_match_is_absence_not_negative() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO", pl_matches=_pl_result()
    ).lower()
    # B2: a no-match renders as evidence-absence, never "not on the PL".
    assert "not evidence the worksite is off the procurement list" in packet
    assert "exact city/state matching does not see" in packet
    # No character-equal claims when nothing matched.
    assert "character-equal" not in packet


def test_packet_pl_other_lines_are_subordinate_presence_not_relevance() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        pl_matches=_pl_result(
            service_type_matches=(),
            same_location_other=(_pl_match(service_type="Grounds Maintenance"),),
        ),
    ).lower()
    # M3: location-only lines are labeled presence, not matches, and not ranked.
    assert "presence is not relevance" in packet
    assert "character-equal" not in packet


def test_packet_pl_synthetic_sample_is_labeled() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        pl_matches=_pl_result(service_type_matches=(_pl_match(),), synthetic_sample=True),
    )
    # m2: the bundled synthetic example must be labeled in the OUTPUT, not just
    # the filename, so it can't be screenshotted as a real finding.
    assert "EXAMPLE DATA" in packet
    assert "SYNTHETIC" in packet


# --- PL activity (Federal Register) section (A4) ----------------------------


def test_packet_without_pl_notices_omits_section() -> None:
    packet = build_opportunity_packet_markdown(
        piid="47QRAA24D0012", county="Denver", state="CO", geography=_geography()
    )
    assert "Procurement List activity (Federal Register)" not in packet


def test_packet_pl_notices_section_present_and_lists_titles() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO", pl_notices=_pl_notices()
    )
    assert "## Procurement List activity (Federal Register)" in packet
    assert "Procurement List; Proposed Deletions" in packet
    assert "2026-14305" in packet


def test_packet_pl_notices_order_r2b_before_pl_activity_before_r2a_map() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X",
        county="Denver",
        state="CO",
        pl_matches=_pl_result(service_type_matches=(_pl_match(),)),
        pl_notices=_pl_notices(),
    )
    r2b_idx = packet.index("## Procurement List cross-reference (R2b)")
    pl_activity_idx = packet.index("## Procurement List activity (Federal Register)")
    r2a_idx = packet.index("## R2a determination-support map")
    assert r2b_idx < pl_activity_idx < r2a_idx


def test_packet_pl_notices_stream_caveat_present() -> None:
    # D3: the Commission's FULL notice stream (non-PL notices included), no
    # silent filtering, and never a claim any notice relates to this contract.
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO", pl_notices=_pl_notices()
    )
    assert "full notice stream" in packet.lower()
    assert "never interpreted" in packet.lower()


def test_packet_pl_notices_search_term_is_labeled_a_text_search() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X",
        county="Denver",
        state="CO",
        pl_notices=_pl_notices(term="Procurement List"),
    )
    assert "notices matching the analyst's search term" in packet.lower()
    assert "text search, not a relevance determination" in packet.lower()


def test_packet_pl_notices_truncated_shows_showing_newest_of_total() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X",
        county="Denver",
        state="CO",
        pl_notices=_pl_notices(truncated=True, count_total=3070),
    )
    assert "showing the newest 1 of 3070 total notices" in packet.lower()


def test_packet_pl_notices_small_nontruncated_shows_all_n() -> None:
    two = (
        FRNoticeRecord("A", "1", "2026-01-01", "http://x/1", "Notice"),
        FRNoticeRecord("B", "2", "2026-01-02", "http://x/2", "Notice"),
    )
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        pl_notices=_pl_notices(records=two, truncated=False, count_total=2),
    )
    assert "all 2 notices." in packet.lower()


def test_packet_pl_notices_zero_match_with_term_is_text_search_absence() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X",
        county="Denver",
        state="CO",
        pl_notices=_pl_notices(term="zzz-no-such-term", records=(), truncated=False, count_total=0),
    )
    lowered = packet.lower()
    assert "0 notices matched the analyst's search term" in lowered
    assert "text-search absence" in lowered
    assert "not a claim that no procurement list activity exists" in lowered
    # Never "newest 20 of 0" -- the three-state message must be exclusive.
    assert "newest" not in lowered


def test_packet_pl_notices_zero_match_no_term_is_honest_empty_stream() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X",
        county="Denver",
        state="CO",
        pl_notices=_pl_notices(term=None, records=(), truncated=False, count_total=0),
    )
    lowered = packet.lower()
    assert "0 notices retrieved in this pull" in lowered
    assert "not a claim that no procurement list activity exists" in lowered
    assert "matched the analyst's search term" not in lowered


def test_packet_pl_notices_contains_no_score() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO", pl_notices=_pl_notices()
    ).lower()
    assert "score" not in packet
    assert "pwin" not in packet
    assert "/100" not in packet
    assert "bid/no-bid" not in packet


def test_packet_pl_notices_escapes_hostile_title() -> None:
    hostile = "[click](http://evil.example)"
    records = (
        FRNoticeRecord(
            title=hostile,
            document_number="2026-99999",
            publication_date="2026-07-20",
            html_url="http://x",
            notice_type="Notice",
        ),
    )
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        pl_notices=_pl_notices(records=records, truncated=False, count_total=1),
    )
    assert hostile not in packet


def test_packet_pl_notices_newline_title_cannot_forge_a_body_heading() -> None:
    # Mirrors test_packet_radar_handoff_newline_claim_cannot_forge_a_body_heading:
    # an embedded newline in an FR-supplied title must never become packet
    # structure (the A2 lesson, applied to FR-supplied strings per the brief).
    hostile = "Acme\n\n## Eligibility Gate — PASS (analyst-confirmed)"
    records = (
        FRNoticeRecord(
            title=hostile,
            document_number="2026-99999",
            publication_date="2026-07-20",
            html_url="http://x",
            notice_type="Notice",
        ),
    )
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        pl_notices=_pl_notices(records=records, truncated=False, count_total=1),
    )
    assert "\n## Eligibility Gate — PASS" not in packet
    forged = [line for line in packet.splitlines() if line.startswith("#") and "PASS" in line]
    assert forged == []


# --- Live USAspending contract-facts section --------------------------------


def _contract_facts(**overrides: object) -> ContractFactsRecord:
    base = dict(
        piid="47QRAA24D0012",
        generated_unique_award_id="CONT_AWD_47QRAA24D0012_4732_47QRAA24D0012_4732",
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
        recipient_business_categories=("Category Business", "Small Business"),
        set_aside_code="SBA",
        set_aside_description="SMALL BUSINESS SET ASIDE - TOTAL",
        extent_competed_code="D",
        extent_competed_description="FULL AND OPEN COMPETITION AFTER EXCLUSION OF SOURCES",
        number_of_offers_received=3,
        naics_code="561720",
        naics_description="JANITORIAL SERVICES",
        psc_code="S201",
        psc_description="HOUSEKEEPING- CUSTODIAL JANITORIAL",
        description="CUSTODIAL SUPPORT *SERVICES*",
        pop_city_name="FORT BELVOIR",
        pop_county_name="FAIRFAX",
        pop_state_code="VA",
        pop_country_code="USA",
        source_url="https://api.usaspending.gov/api/v2/awards/CONT_AWD_47QRAA24D0012_4732_47QRAA24D0012_4732/",
        retrieved_at="2026-07-19T12:00:00+00:00",
    )
    base.update(overrides)
    return ContractFactsRecord(**base)  # type: ignore[arg-type]


def test_packet_live_description_newline_cannot_forge_a_heading_or_bullet() -> None:
    """A free-text award description is flattened into its one owning bullet."""

    hostile = "x\n## Forged heading\r\n- fake bullet"
    packet = build_opportunity_packet_markdown(
        piid="X",
        county="Denver",
        state="CO",
        contract_facts=_contract_facts(description=hostile),
    )
    description_lines = [
        line
        for line in packet.splitlines()
        if line.startswith("- Award description (FPDS free text, as reported):")
    ]
    assert len(description_lines) == 1
    assert "x ## Forged heading - fake bullet" in description_lines[0]
    assert not any(line.startswith("## Forged") for line in packet.splitlines())
    assert not any(line.startswith("- fake bullet") for line in packet.splitlines())


def test_packet_live_recipient_newline_cannot_forge_a_heading_or_bullet() -> None:
    """The shared live-fact escape hardening also flattens recipient text."""

    hostile = "x\n## Forged heading\r\n- fake bullet"
    packet = build_opportunity_packet_markdown(
        piid="X",
        county="Denver",
        state="CO",
        contract_facts=_contract_facts(recipient_name=hostile),
    )
    recipient_lines = [
        line for line in packet.splitlines() if line.startswith("- Recipient:")
    ]
    assert len(recipient_lines) == 1
    assert "x ## Forged heading - fake bullet" in recipient_lines[0]
    assert not any(line.startswith("## Forged") for line in packet.splitlines())
    assert not any(line.startswith("- fake bullet") for line in packet.splitlines())


def test_packet_live_description_renders_full_and_markdown_escaped() -> None:
    """The reported description renders in full while Markdown syntax is neutralized."""

    description = "FULL *FREE-TEXT* DESCRIPTION [AS REPORTED]"
    packet = build_opportunity_packet_markdown(
        piid="X",
        county="Denver",
        state="CO",
        contract_facts=_contract_facts(description=description),
    )
    assert (
        "- Award description (FPDS free text, as reported): "
        "FULL \\*FREE-TEXT\\* DESCRIPTION \\[AS REPORTED\\]"
    ) in packet


def test_packet_live_place_renders_components_without_domestic_country() -> None:
    """City, county, and state stay separate, while an exact USA code is omitted."""

    packet = build_opportunity_packet_markdown(
        piid="X",
        county="Denver",
        state="CO",
        contract_facts=_contract_facts(),
    )
    place_lines = [
        line for line in packet.splitlines() if line.startswith("- Place of performance —")
    ]
    assert place_lines == [
        "- Place of performance — city: FORT BELVOIR · county: FAIRFAX · state: VA"
    ]
    assert "country:" not in place_lines[0]
    assert "The COUNTY (not the city) keys the ACS Geography section" in packet
    assert "the CITY is the R2b worksite key" in packet


def test_packet_live_absent_description_is_not_reported() -> None:
    """A missing award description renders as unknown rather than an empty claim."""

    packet = build_opportunity_packet_markdown(
        piid="X",
        county="Denver",
        state="CO",
        contract_facts=_contract_facts(description=None),
    )
    assert "- Award description (FPDS free text, as reported): Not reported" in packet


def test_packet_live_all_absent_place_is_one_not_reported_line() -> None:
    """Four absent PoP components collapse only to the required honest fallback."""

    packet = build_opportunity_packet_markdown(
        piid="X",
        county="Denver",
        state="CO",
        contract_facts=_contract_facts(
            pop_city_name=None,
            pop_county_name=None,
            pop_state_code=None,
            pop_country_code=None,
        ),
    )
    live_section = packet[
        packet.index("## Contract Facts (live") : packet.index(
            "## Contract Facts (analyst-entered)"
        )
    ]
    place_lines = [
        line
        for line in live_section.splitlines()
        if line.startswith("- Place of performance")
    ]
    assert place_lines == ["- Place of performance: Not reported"]
    assert "The COUNTY (not the city) keys the ACS Geography section" not in live_section


def test_packet_live_non_usa_place_includes_country_code() -> None:
    """A reported non-USA country remains visible with the separate PoP components."""

    packet = build_opportunity_packet_markdown(
        piid="X",
        county="Denver",
        state="CO",
        contract_facts=_contract_facts(pop_country_code="CAN"),
    )
    assert (
        "- Place of performance — city: FORT BELVOIR · county: FAIRFAX · "
        "state: VA · country: CAN"
    ) in packet


def test_packet_analyst_county_markdown_is_escaped() -> None:
    """A prefilled or typed county cannot create emphasis in the analyst block."""

    packet = build_opportunity_packet_markdown(
        piid="X", county="*evil*", state="CO"
    )
    assert "- Place of performance: \\*evil\\*, CO" in packet


def test_packet_live_obligated_distinct_from_ceiling() -> None:  # T16
    packet = build_opportunity_packet_markdown(piid="X", county="Denver", state="CO", contract_facts=_contract_facts())
    assert "Obligated to date" in packet
    assert "Ceiling (base + all options)" in packet
    assert "100,000" in packet and "250,000" in packet
    assert "NOT money obligated" in packet


def test_packet_live_facts_are_cited() -> None:  # T17
    record = _contract_facts()
    packet = build_opportunity_packet_markdown(piid="X", county="Denver", state="CO", contract_facts=record)
    assert record.source_url in packet
    assert record.retrieved_at in packet


def test_packet_live_extent_shows_code() -> None:  # T18
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO", contract_facts=_contract_facts(extent_competed_code="A")
    )
    assert "extent" in packet.lower()
    assert "FPDS code A" in packet


def test_packet_live_potential_end_date_is_safe() -> None:  # T19
    # The " 00:00:00" suffix must render without raising (never strict-parsed).
    # The renderer safely displays just the date; the raw string is preserved on
    # the record itself (connector test T6).
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        contract_facts=_contract_facts(period_potential_end_date="2019-03-20 00:00:00"),
    )
    assert "2019-03-20" in packet


def test_packet_live_set_aside_feeds_gate_retrieved_provenance() -> None:  # T20
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO", contract_facts=_contract_facts(set_aside_code="SBA")
    )
    assert "## Eligibility gate" in packet
    assert "13 CFR 121.105" in packet  # SBA is a small-business set-aside
    assert "retrieved LIVE from USAspending" in packet
    # The gate's default analyst-entered source line is NOT used for retrieved data.
    assert "analyst-entered set-aside value" not in packet


def test_packet_live_null_set_aside_is_unknown_not_unrestricted() -> None:  # T21
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO", contract_facts=_contract_facts(set_aside_code=None, set_aside_description=None)
    )
    assert "### UNKNOWN" in packet
    assert "not reported" in packet.lower()
    # A null must never read as unrestricted.
    assert "### NO SET-ASIDE" not in packet


def test_packet_live_and_analyst_blocks_both_present() -> None:  # T22
    packet = build_opportunity_packet_markdown(piid="47QRAA24D0012", county="Denver", state="CO", contract_facts=_contract_facts())
    assert "## Contract Facts (live — USAspending, cited)" in packet
    assert "## Contract Facts (analyst-entered)" in packet


def test_packet_live_escapes_markdown_in_retrieved_values() -> None:  # T23
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        contract_facts=_contract_facts(recipient_name="[x](http://evil)"),
    )
    assert "](http://evil)" not in packet  # link neutralized
    assert "\\[x\\]\\(http://evil\\)" in packet


def test_packet_live_contains_no_score() -> None:  # T24
    packet = build_opportunity_packet_markdown(piid="X", county="Denver", state="CO", contract_facts=_contract_facts()).lower()
    assert "score" not in packet
    assert "pwin" not in packet
    assert "/100" not in packet
    assert "bid/no-bid" not in packet


def test_packet_builder_back_compat_without_contract_facts() -> None:  # T25
    packet = build_opportunity_packet_markdown(piid="47QRAA24D0012", county="Denver", state="CO")
    assert "## Contract Facts (live" not in packet
    assert "## Contract Facts (analyst-entered)" in packet


# --- Capture window (roadmap SS4.2, ADR-015) ---------------------------------


def test_packet_capture_window_omitted_without_contract_facts() -> None:  # T26
    packet = build_opportunity_packet_markdown(piid="X", county="Denver", state="CO")
    assert "## Capture window" not in packet


def test_packet_capture_window_present_between_contract_facts_and_geography() -> None:  # T27
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        contract_facts=_contract_facts(),
        geography=_geography(),
        as_of=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    assert "## Capture window" in packet
    assert packet.index("## Contract Facts (analyst-entered)") < packet.index("## Capture window")
    assert packet.index("## Capture window") < packet.index("## Geography context")


def test_packet_capture_window_is_a_band_anchored_to_solicitation() -> None:  # T28
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        contract_facts=_contract_facts(period_potential_end_date="2028-05-31 00:00:00"),
        as_of=datetime(2026, 7, 19, tzinfo=timezone.utc),
    ).casefold()
    assert "2027-05-31 to 2027-11-30" in packet  # solicitation window, a range
    assert "not the contract's potential period end date" in packet
    assert "owner-attested" in packet
    assert "the human decides" in packet


def test_packet_capture_window_unknown_on_unparseable_or_missing_date() -> None:  # T29
    for raw in (None, "", "garbled-not-a-date"):
        packet = build_opportunity_packet_markdown(
            piid="X", county="Denver", state="CO",
            contract_facts=_contract_facts(period_potential_end_date=raw),
            as_of=datetime(2026, 7, 19, tzinfo=timezone.utc),
        )
        assert "capture window unknown" in packet.casefold()


def test_packet_capture_window_past_is_honest_not_hidden() -> None:  # T30
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        contract_facts=_contract_facts(period_potential_end_date="2019-03-20 00:00:00"),
        as_of=datetime(2026, 7, 19, tzinfo=timezone.utc),
    ).casefold()
    assert "already elapsed" in packet
    # Neutral timing fact only -- no capture-route recommendation (N1 / AGENTS #8).
    # (The standing "pursue-or-not recommendation" disclaimer is fine.)
    assert "as a teammate this cycle" not in packet
    assert "r2a next" not in packet


def test_packet_capture_window_contains_no_score() -> None:  # T31
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        contract_facts=_contract_facts(),
        as_of=datetime(2026, 7, 19, tzinfo=timezone.utc),
    ).casefold()
    assert "score" not in packet
    assert "pwin" not in packet
    assert "/100" not in packet
    assert "bid/no-bid" not in packet


# --- Incumbent & teaming leads / PL-impact context (A5) -----------------------


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


def _subawards(*records: SubawardRecord, truncated: bool = False) -> SubawardsResult:
    return SubawardsResult(
        award_generated_internal_id="CONT_AWD_47QRAA24D0012_4732_47QRAA24D0012_4732",
        records=records,
        truncated=truncated,
        source_url="https://api.usaspending.gov/api/v2/subawards/",
        retrieved_at="2026-07-20T12:05:00+00:00",
    )


def test_packet_leads_section_omitted_without_contract_facts() -> None:
    packet = build_opportunity_packet_markdown(piid="X", county="Denver", state="CO")
    assert "Incumbent & teaming leads" not in packet


def test_packet_leads_section_present_with_contract_facts() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO", contract_facts=_contract_facts()
    )
    assert "## Incumbent & teaming leads / PL-impact context (cited)" in packet


def test_packet_leads_section_order_capture_window_then_leads_then_geography() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        contract_facts=_contract_facts(),
        geography=_geography(),
        as_of=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    capture_idx = packet.index("## Capture window")
    leads_idx = packet.index("## Incumbent & teaming leads")
    geography_idx = packet.index("## Geography context")
    assert capture_idx < leads_idx < geography_idx


def test_packet_leads_staffing_geography_order_pin() -> None:
    # Order pin (audit catch, §3): leads < Staffing < Geography, in
    # combination with every other section this render also has attached.
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        contract_facts=_contract_facts(),
        geography=_geography(),
        staffing=_staffing_computed(),
        as_of=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    leads_idx = packet.index("## Incumbent & teaming leads")
    staffing_idx = packet.index("## Staffing what-if")
    geography_idx = packet.index("## Geography context")
    assert leads_idx < staffing_idx < geography_idx


def test_packet_staffing_section_renders_without_contract_facts() -> None:
    # Staffing is independent of live Contract Facts -- it renders on its own.
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        staffing=_staffing_computed(),
    )
    assert "## Staffing what-if" in packet
    assert "## Incumbent & teaming leads" not in packet


def test_packet_staffing_section_omitted_when_none() -> None:
    packet = build_opportunity_packet_markdown(piid="X", county="Denver", state="CO")
    assert "## Staffing what-if" not in packet


def test_packet_leads_section_renders_subawards_enrichment() -> None:
    subs = _subawards(SubawardRecord("1", "ExampleWorks Sub LLC", 5000.0, "2025-01-01", "custodial support"))
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        contract_facts=_contract_facts(),
        subawards=subs,
    )
    assert "ExampleWorks Sub LLC" in packet
    assert "1 subaward record(s) reported" in packet


def test_packet_leads_section_renders_directory_enrichment() -> None:
    subs = _subawards(SubawardRecord("1", "ExampleWorks Sub LLC", 5000.0, "2025-01-01", "custodial support"))
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        contract_facts=_contract_facts(),
        subawards=subs,
        directory_agency_names=["ExampleWorks Sub LLC"],
    )
    assert "Coincident:" in packet
    assert "AbilityOne directory cross-reference" in packet


def test_packet_leads_section_without_subawards_shows_absence_caveat() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO", contract_facts=_contract_facts()
    )
    assert "No subaward records were retrieved for this award" in packet


def test_packet_leads_escapes_hostile_subawardee_name() -> None:
    subs = _subawards(SubawardRecord("1", "[x](http://evil)", 100.0, "2025-01-01", "d"))
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        contract_facts=_contract_facts(),
        subawards=subs,
    )
    assert "](http://evil)" not in packet
    assert "\\[x\\]\\(http://evil\\)" in packet


def test_packet_leads_section_no_score_or_directive() -> None:
    subs = _subawards(SubawardRecord("1", "ExampleWorks Sub LLC", 5000.0, "2025-01-01", "d"))
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        contract_facts=_contract_facts(),
        subawards=subs,
        directory_agency_names=["ExampleWorks Sub LLC"],
        staffing=_staffing_computed(),
    )
    # Isolate the new section: the surrounding packet's OWN standing framing
    # (e.g. PACKET_FRAMING's "no pursue-or-decline recommendation") legitimately
    # contains negated forbidden words, so the directive-vocabulary guard is
    # scoped to this section's own text, not the whole packet. Retargeted
    # (audit catch, §3) to end at the Staffing header now that Staffing
    # renders between Leads and Geography, so this slice stays scoped to
    # Leads only -- Staffing gets its own sibling guard below.
    start = packet.index("## Incumbent & teaming leads")
    end = packet.index("## Staffing what-if")
    section = packet[start:end].lower()
    assert "score" not in section
    assert "pwin" not in section
    assert "/100" not in section
    assert "bid/no-bid" not in section
    assert "pursue" not in section
    assert "call " not in section


def test_packet_staffing_section_no_score_or_directive() -> None:
    # Sibling guard (audit catch, §3): the Staffing section's own text must
    # avoid every guarded token, scoped from its own header to Geography.
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO",
        contract_facts=_contract_facts(),
        staffing=_staffing_computed(),
    )
    start = packet.index("## Staffing what-if")
    end = packet.index("## Geography context")
    section = packet[start:end].lower()
    assert "score" not in section
    assert "pwin" not in section
    assert "/100" not in section
    assert "bid/no-bid" not in section
    assert "pursue" not in section
    assert "call " not in section


def test_packet_leads_section_has_pl_impact_block_no_ratio() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO", contract_facts=_contract_facts()
    )
    assert "PL-impact context" in packet
    assert "no share is computed here" in packet


# --- A2: Origin (Radar handoff) section wiring ------------------------------


def _handoff(**overrides: object) -> RadarHandoff:
    base = dict(
        schema_version="radar-handoff/v1",
        snapshot_date="2026-07-15",
        piid="SYNTH-A2-0001",
        radar_source_label="GovConRadar 2.8.0",
        synthetic_sample=False,
        claims=RadarHandoffClaims(recipient_name="EXAMPLE CO"),
        unknown_field_count=0,
    )
    base.update(overrides)
    return RadarHandoff(**base)  # type: ignore[arg-type]


def test_packet_without_radar_handoff_omits_origin_section() -> None:
    packet = build_opportunity_packet_markdown(piid="X", county="Denver", state="CO")
    assert "Origin" not in packet


def test_packet_radar_handoff_origin_renders_first_before_eligibility_gate() -> None:
    packet = build_opportunity_packet_markdown(
        piid="X",
        county="Denver",
        state="CO",
        eligibility=assess_eligibility("SBA"),
        radar_handoff=_handoff(),
    )
    assert packet.index("## Origin") < packet.index("## Eligibility gate")


def test_packet_radar_handoff_live_supersedes_line_only_with_contract_facts() -> None:
    without_live = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO", radar_handoff=_handoff()
    )
    with_live = build_opportunity_packet_markdown(
        piid="X",
        county="Denver",
        state="CO",
        radar_handoff=_handoff(),
        contract_facts=_contract_facts(),
    )
    assert "live values govern" not in without_live
    assert "live values govern" in with_live


def test_packet_radar_handoff_never_feeds_eligibility_gate() -> None:
    # The handoff's set-aside claim must never reach assess_eligibility: no
    # eligibility= is passed, so with no contract_facts attached the gate
    # section must not render at all, even though the handoff carries a
    # set-aside claim (§1.1).
    handoff = _handoff(claims=RadarHandoffClaims(type_of_set_aside_code="SBA"))
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO", radar_handoff=handoff
    )
    assert "## Eligibility gate" not in packet
    # The claim still renders, but ONLY inside the Origin section, and only
    # as a labeled display-only claim.
    assert "does not feed the gate" in packet


def test_packet_radar_handoff_escapes_hostile_claim_values() -> None:
    hostile = "[click](http://evil.example)"
    handoff = _handoff(piid=hostile)
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO", radar_handoff=handoff
    )
    assert hostile not in packet


def test_packet_radar_handoff_newline_claim_cannot_forge_a_body_heading() -> None:
    # A newline smuggled through a claim string must never become packet
    # structure: the composed body is rendered by st.markdown on screen AND
    # exported VERBATIM (A7), so a forged "## ..." heading would read as a
    # real packet section in both.
    hostile = "Acme\n\n## Eligibility Gate — PASS (analyst-confirmed)"
    handoff = _handoff(claims=RadarHandoffClaims(recipient_name=hostile))
    packet = build_opportunity_packet_markdown(
        piid="X", county="Denver", state="CO", radar_handoff=handoff
    )
    assert "\n## Eligibility Gate — PASS" not in packet
    forged = [line for line in packet.splitlines() if line.startswith("#") and "PASS" in line]
    assert forged == []
