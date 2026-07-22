"""Offline unit tests for the Incumbent & teaming leads / PL-impact context
module (A5). Covers every honesty invariant in the brief §3: band assignment,
the entailed-offers no-corroboration rule, code-not-text no-guess
classification, the single-offer conflation guard, the FSRS absence caveat, directory
Coincident-band matching, citation enforcement, deterministic ordering, and
the N1/no-directive language guards.
"""

from __future__ import annotations

import pytest

from tens_hq.connectors.usaspending import ContractFactsRecord, SubawardRecord, SubawardsResult
from tens_hq.incumbent_leads import (
    DIRECTORY_NO_MATCH_NOTE,
    INCUMBENT_LEADS_WHY_UNKNOWN,
    SUBAWARDS_ABSENCE_CAVEAT,
    IncumbentLeads,
    Lead,
    LeadBand,
    derive_incumbent_leads,
    incumbent_leads_lines,
)


def _cf(**overrides: object) -> ContractFactsRecord:
    base = dict(
        piid="X",
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
        recipient_business_categories=("Category Business", "Small Business"),
        set_aside_code="SBA",
        set_aside_description="SMALL BUSINESS SET ASIDE",
        extent_competed_code="D",
        extent_competed_description="FULL AND OPEN COMPETITION AFTER EXCLUSION OF SOURCES",
        number_of_offers_received=3,
        naics_code="561720",
        naics_description="JANITORIAL SERVICES",
        psc_code="S201",
        psc_description="HOUSEKEEPING",
        description=None,
        pop_city_name=None,
        pop_county_name=None,
        pop_state_code=None,
        pop_country_code=None,
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


def _render(assessment: IncumbentLeads, contract_facts: ContractFactsRecord) -> str:
    return "\n".join(incumbent_leads_lines(assessment, contract_facts=contract_facts))


# --- Band assignment / code-not-text / conflation guard -----------------------


def test_competed_code_is_observed_no_interpretation_lead() -> None:
    cf = _cf(extent_competed_code="A", number_of_offers_received=5)
    assessment = derive_incumbent_leads(cf)
    bands = [lead.band for lead in assessment.leads]
    assert LeadBand.LEAD_SINGLE not in bands
    assert LeadBand.LEAD_CORROBORATED not in bands
    rendered = _render(assessment, cf)
    assert 'Extent of competition = "A" -- competed.' in rendered


def test_not_competed_family_without_low_offers_is_lead_single() -> None:
    cf = _cf(extent_competed_code="B", number_of_offers_received=5)
    assessment = derive_incumbent_leads(cf)
    single = [l for l in assessment.leads if l.band is LeadBand.LEAD_SINGLE]
    assert len(single) == 1
    assert "sole-source family" in single[0].text
    assert "code" in single[0].basis


def test_single_offer_on_competed_award_is_lead_single() -> None:
    cf = _cf(extent_competed_code="D", number_of_offers_received=1)
    assessment = derive_incumbent_leads(cf)
    single = [l for l in assessment.leads if l.band is LeadBand.LEAD_SINGLE]
    assert len(single) == 1
    assert "drew a single offer" in single[0].text


def test_offers_conflation_guard_not_competed_does_not_emit_competed_single_offer_lead() -> None:
    # A single/zero offer count on a NOT-competed award is entailed by the
    # designation -- it must never be rendered as the "competed but drew a
    # single offer" lead.
    cf = _cf(extent_competed_code="C", number_of_offers_received=1)
    assessment = derive_incumbent_leads(cf)
    rendered = _render(assessment, cf)
    assert "drew a single offer" not in rendered


def test_sole_source_offers_count_is_entailed_never_corroboration() -> None:
    # On a not-competed award the offers count carries no independent
    # information (the government solicits one vendor by definition), so it
    # must never upgrade the band -- including for degenerate counts.
    for offers in (0, 1, -5):
        cf = _cf(extent_competed_code="C", number_of_offers_received=offers)
        assessment = derive_incumbent_leads(cf)
        assert not [l for l in assessment.leads if l.band is LeadBand.LEAD_CORROBORATED]
        single = [l for l in assessment.leads if l.band is LeadBand.LEAD_SINGLE]
        assert len(single) == 1
        assert "consistent with, not independent of" in single[0].text
        # The interpretation's basis remains the code alone.
        assert "number of offers" not in single[0].basis


def test_sole_source_without_offers_reported_omits_the_entailment_note() -> None:
    # sole-source family but offers is None (not reported) -- the Lead-single
    # fires on the code alone and does not mention an offers count.
    cf = _cf(extent_competed_code="G", number_of_offers_received=None)
    assessment = derive_incumbent_leads(cf)
    assert not [l for l in assessment.leads if l.band is LeadBand.LEAD_CORROBORATED]
    single = [l for l in assessment.leads if l.band is LeadBand.LEAD_SINGLE]
    assert len(single) == 1
    assert "consistent with" not in single[0].text


def test_unrecognized_extent_code_is_no_guess() -> None:
    cf = _cf(extent_competed_code="Z", number_of_offers_received=2)
    assessment = derive_incumbent_leads(cf)
    rendered = _render(assessment, cf)
    assert "competition posture not classified here" in rendered
    assert not [l for l in assessment.leads if l.band in (LeadBand.LEAD_SINGLE, LeadBand.LEAD_CORROBORATED)]


def test_extent_code_not_reported_renders_honestly() -> None:
    cf = _cf(extent_competed_code=None, number_of_offers_received=None)
    assessment = derive_incumbent_leads(cf)
    rendered = _render(assessment, cf)
    assert "Extent of competition not reported." in rendered


# --- Business categories -------------------------------------------------------


def test_business_categories_observed_line_labels_registration_derived() -> None:
    cf = _cf(recipient_business_categories=("Small Business",))
    assessment = derive_incumbent_leads(cf)
    rendered = _render(assessment, cf)
    assert "registration-derived, self-reported via SAM registration" in rendered
    assert "Small Business" in rendered


def test_business_categories_absent_renders_not_reported() -> None:
    cf = _cf(recipient_business_categories=None)
    assessment = derive_incumbent_leads(cf)
    rendered = _render(assessment, cf)
    assert "Recipient business categories not reported" in rendered


# --- FSRS absence caveat (never "no teaming history") -------------------------


def test_subawards_none_renders_absence_caveat() -> None:
    cf = _cf()
    assessment = derive_incumbent_leads(cf, subawards=None)
    assert assessment.subawards_attached is False
    rendered = _render(assessment, cf)
    assert SUBAWARDS_ABSENCE_CAVEAT in rendered


def test_subawards_zero_records_renders_absence_caveat() -> None:
    cf = _cf()
    assessment = derive_incumbent_leads(cf, subawards=_sub())
    assert assessment.subawards_attached is True
    assert assessment.subawards_record_count == 0
    rendered = _render(assessment, cf)
    assert SUBAWARDS_ABSENCE_CAVEAT in rendered


def test_subawards_nonzero_does_not_render_absence_caveat() -> None:
    cf = _cf()
    sub = _sub(SubawardRecord("1", "Sub Co", 1000.0, "2025-01-01", "desc"))
    assessment = derive_incumbent_leads(cf, subawards=sub)
    rendered = _render(assessment, cf)
    assert SUBAWARDS_ABSENCE_CAVEAT not in rendered
    assert "1 subaward record(s) reported" in rendered


def test_subawards_truncated_note_renders() -> None:
    cf = _cf()
    sub = _sub(SubawardRecord("1", "Sub Co", 1000.0, "2025-01-01", "desc"), truncated=True)
    assessment = derive_incumbent_leads(cf, subawards=sub)
    assert assessment.subawards_truncated is True
    rendered = _render(assessment, cf)
    assert "more subaward records exist than were retrieved (first 100 shown)" in rendered


def test_subawards_render_caps_at_ten_and_says_more_exist() -> None:
    cf = _cf()
    records = tuple(
        SubawardRecord(str(i), f"Sub {i}", float(1000 - i), "2025-01-01", "desc") for i in range(15)
    )
    sub = _sub(*records)
    assessment = derive_incumbent_leads(cf, subawards=sub)
    rendered = _render(assessment, cf)
    subawardee_leads = [l for l in assessment.leads if l.text.startswith('Subawardee "Sub')]
    assert len(subawardee_leads) == 10
    assert "showing the top 10 by reported amount, 5 more not shown here" in rendered


def test_subawards_null_row_fields_render_not_reported() -> None:
    cf = _cf()
    sub = _sub(SubawardRecord(None, None, None, None, None))
    assessment = derive_incumbent_leads(cf, subawards=sub)
    rendered = _render(assessment, cf)
    assert 'Subawardee "Not reported" -- Not reported' in rendered


def test_deterministic_subaward_ordering_amount_desc_none_last_tiebreak() -> None:
    cf = _cf()
    records = (
        SubawardRecord("z", "Zeta Co", 100.0, "2025-01-01", "d"),
        SubawardRecord("a", "Alpha Co", 100.0, "2025-01-01", "d"),  # tie on amount -> name tiebreak
        SubawardRecord("b", "Beta Co", None, "2025-01-01", "d"),  # None-amount goes last
        SubawardRecord("c", "Charlie Co", 500.0, "2025-01-01", "d"),
    )
    sub = _sub(*records)
    assessment = derive_incumbent_leads(cf, subawards=sub)
    subawardee_leads = [l for l in assessment.leads if l.text.startswith("Subawardee")]
    names_in_order = [l.text.split('"')[1] for l in subawardee_leads]
    assert names_in_order == ["Charlie Co", "Alpha Co", "Zeta Co", "Beta Co"]

    # Re-deriving must produce byte-identical order (no dict/set nondeterminism).
    again = derive_incumbent_leads(cf, subawards=sub)
    assert _render(assessment, cf) == _render(again, cf)


# --- Directory cross-reference (Coincident band, D2 exact match only) --------


def test_directory_exact_match_is_coincident_with_analyst_confirm_text() -> None:
    cf = _cf()
    sub = _sub(SubawardRecord("1", "ExampleWorks Sub LLC", 5000.0, "2025-01-01", "d"))
    assessment = derive_incumbent_leads(
        cf, subawards=sub, directory_agency_names=["ExampleWorks Sub LLC"]
    )
    coincident = [l for l in assessment.leads if l.band is LeadBand.COINCIDENT]
    assert len(coincident) == 1
    assert assessment.directory_match_count == 1
    text = coincident[0].text
    assert "COINCIDENCE" in text
    assert "not a confirmed relationship, partnership, capacity, or willingness" in text
    assert "analyst's" in text


def test_directory_match_is_normalized_exact_not_fuzzy() -> None:
    cf = _cf()
    sub = _sub(SubawardRecord("1", "  ExampleWorks   Sub LLC  ", 5000.0, "2025-01-01", "d"))
    # Directory has the casefold/whitespace-collapsed equivalent -- still a match.
    assessment = derive_incumbent_leads(
        cf, subawards=sub, directory_agency_names=["exampleworks sub llc"]
    )
    assert assessment.directory_match_count == 1

    # But a near-miss (substring/fuzzy) must NOT match (D2 house rule).
    sub2 = _sub(SubawardRecord("1", "ExampleWorks Subcontracting LLC", 5000.0, "2025-01-01", "d"))
    assessment2 = derive_incumbent_leads(
        cf, subawards=sub2, directory_agency_names=["ExampleWorks Sub LLC"]
    )
    assert assessment2.directory_match_count == 0


def test_directory_attached_no_match_renders_honest_line() -> None:
    cf = _cf()
    sub = _sub(SubawardRecord("1", "Totally Different Co", 5000.0, "2025-01-01", "d"))
    assessment = derive_incumbent_leads(cf, subawards=sub, directory_agency_names=["Some NPA"])
    assert assessment.directory_attached is True
    assert assessment.directory_match_count == 0
    rendered = _render(assessment, cf)
    assert DIRECTORY_NO_MATCH_NOTE in rendered


def test_directory_not_provided_omits_match_and_no_match_lines() -> None:
    cf = _cf()
    sub = _sub(SubawardRecord("1", "Some Co", 5000.0, "2025-01-01", "d"))
    assessment = derive_incumbent_leads(cf, subawards=sub, directory_agency_names=None)
    assert assessment.directory_attached is False
    rendered = _render(assessment, cf)
    assert DIRECTORY_NO_MATCH_NOTE not in rendered
    assert "AbilityOne directory cross-reference" not in rendered


def test_directory_match_dedupes_repeated_subawardee_name() -> None:
    cf = _cf()
    sub = _sub(
        SubawardRecord("1", "Repeat Co", 100.0, "2025-01-01", "d"),
        SubawardRecord("2", "Repeat Co", 200.0, "2025-02-01", "d"),
    )
    assessment = derive_incumbent_leads(cf, subawards=sub, directory_agency_names=["Repeat Co"])
    assert assessment.directory_match_count == 1


# --- Why-Unknown standing line always present ---------------------------------


def test_why_unknown_line_always_present() -> None:
    cf = _cf()
    for subawards, directory in (
        (None, None),
        (_sub(), None),
        (_sub(SubawardRecord("1", "A", 1.0, "2025-01-01", "d")), ["A"]),
    ):
        assessment = derive_incumbent_leads(cf, subawards=subawards, directory_agency_names=directory)
        rendered = _render(assessment, cf)
        assert INCUMBENT_LEADS_WHY_UNKNOWN in rendered


# --- Citation enforcement (no-citation-no-render, structural) -----------------


def test_lead_rejects_empty_source_url() -> None:
    with pytest.raises(ValueError):
        Lead(LeadBand.OBSERVED, "some text", "", "2026-07-20T00:00:00+00:00")


def test_lead_rejects_empty_retrieved_at() -> None:
    with pytest.raises(ValueError):
        Lead(LeadBand.OBSERVED, "some text", "https://example.test", "")


def test_lead_rejects_empty_text() -> None:
    with pytest.raises(ValueError):
        Lead(LeadBand.OBSERVED, "", "https://example.test", "2026-07-20T00:00:00+00:00")


def test_non_observed_lead_requires_basis() -> None:
    with pytest.raises(ValueError):
        Lead(LeadBand.LEAD_SINGLE, "an interpretation", "https://example.test", "2026-07-20T00:00:00+00:00")


def test_every_lead_in_a_full_assessment_carries_a_source() -> None:
    cf = _cf(extent_competed_code="C", number_of_offers_received=0)
    sub = _sub(
        SubawardRecord("1", "ExampleWorks Sub LLC", 5000.0, "2025-01-01", "d"),
        SubawardRecord("2", None, None, None, None),
    )
    assessment = derive_incumbent_leads(
        cf, subawards=sub, directory_agency_names=["ExampleWorks Sub LLC"]
    )
    assert len(assessment.leads) > 0
    for lead in assessment.leads:
        assert lead.source_url.strip()
        assert lead.retrieved_at.strip()


# --- N1: no score/tier/rank/recommendation; no directive vocabulary ----------


def test_no_score_or_rank_anywhere() -> None:
    cf = _cf(extent_competed_code="C", number_of_offers_received=0)
    sub = _sub(SubawardRecord("1", "ExampleWorks Sub LLC", 5000.0, "2025-01-01", "d"))
    assessment = derive_incumbent_leads(
        cf, subawards=sub, directory_agency_names=["ExampleWorks Sub LLC"]
    )
    rendered = _render(assessment, cf).lower()
    assert "score" not in rendered
    assert "pwin" not in rendered
    assert "/100" not in rendered
    assert "bid/no-bid" not in rendered
    assert "tier" not in rendered
    assert "rank" not in rendered


def test_no_directive_vocabulary_anywhere() -> None:
    cf = _cf(extent_competed_code="C", number_of_offers_received=0)
    sub = _sub(SubawardRecord("1", "ExampleWorks Sub LLC", 5000.0, "2025-01-01", "d"))
    assessment = derive_incumbent_leads(
        cf, subawards=sub, directory_agency_names=["ExampleWorks Sub LLC"]
    )
    rendered = _render(assessment, cf).lower()
    for forbidden in ("pursue", "call ", "should bid", "recommend", "you should", "reach out to"):
        assert forbidden not in rendered


def test_pl_impact_no_computed_ratio() -> None:
    cf = _cf(total_obligation=100000.0)
    assessment = derive_incumbent_leads(cf)
    rendered = _render(assessment, cf)
    assert "PL-impact context" in rendered
    assert "no share is computed here" in rendered
    assert "%" not in rendered


# --- Markdown escaping of API-derived strings ----------------------------------


def test_hostile_subawardee_name_is_escaped() -> None:
    cf = _cf()
    sub = _sub(SubawardRecord("1", "[x](http://evil)", 100.0, "2025-01-01", "d"))
    assessment = derive_incumbent_leads(cf, subawards=sub)
    rendered = _render(assessment, cf)
    assert "](http://evil)" not in rendered
    assert "\\[x\\]\\(http://evil\\)" in rendered


def test_hostile_directory_matched_name_is_escaped() -> None:
    cf = _cf()
    sub = _sub(SubawardRecord("1", "[y](http://evil2)", 100.0, "2025-01-01", "d"))
    assessment = derive_incumbent_leads(cf, subawards=sub, directory_agency_names=["[y](http://evil2)"])
    rendered = _render(assessment, cf)
    assert "](http://evil2)" not in rendered


def test_long_description_is_clamped_before_escaping() -> None:
    # 400 markdown-hostile chars: the clamp must cut to 280 + "..." on the RAW
    # string and the survivors must all still be escaped (no bypass via the cut).
    hostile = "[" * 400
    cf = _cf()
    sub = _sub(SubawardRecord("1", "Sub Co", 100.0, "2025-01-01", hostile))
    assessment = derive_incumbent_leads(cf, subawards=sub)
    rendered = _render(assessment, cf)
    assert rendered.count(r"\[") == 280
    assert "[" not in rendered.replace(r"\[", "")
    assert "..." in rendered


def test_user_attested_footer_names_the_uploaded_directory() -> None:
    cf = _cf()
    sub = _sub(SubawardRecord("1", "ExampleWorks Sub LLC", 5000.0, "2025-01-01", "d"))
    assessment = derive_incumbent_leads(
        cf, subawards=sub, directory_agency_names=["ExampleWorks Sub LLC"]
    )
    rendered = _render(assessment, cf)
    assert "- Directory: analyst-uploaded (provenance unattested)" in rendered
    assert "Provenance assurance: USER_ATTESTED" in rendered
