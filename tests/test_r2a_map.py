"""Offline unit tests for the R2a determination-support map (ADR-022).

Covers: the fixed four-criteria order, the honest per-criterion absence
line, the (a)(1) inline geography-disclaimer routing rail (audit MAJOR --
byte-identical to opportunity_packet.GEOGRAPHY_CONTEXT_DISCLAIMER), the
(a)(3) capability-list framing routing rail (audit MINOR), (a)(2) staffing
wiring (including the CANNOT_COMPUTE partial-entry branch), (a)(4)
incumbent-leads wiring, the fixed epilogue lines, the Capture Window
epilogue's conditional citation, the never-a-determination / no-marker
invariants, and the counsel-gated C3/C4 absence guard.
"""

from __future__ import annotations

from datetime import date

import pytest

from conftest import counsel_gate_violations
from tens_hq.capture_window import CaptureWindowPolicy, assess_capture_window
from tens_hq.connectors import ContractFactsRecord, GeographyRecord
from tens_hq.incumbent_leads import derive_incumbent_leads
from tens_hq.opportunity_packet import GEOGRAPHY_CONTEXT_DISCLAIMER
from tens_hq.r2a_map import (
    R2A_EPILOGUE_ALLOCATION,
    R2A_EPILOGUE_FMP,
    R2A_EPILOGUE_NEXT_ACTION,
    R2A_EPILOGUE_ORIGINATION,
    R2A_EPILOGUE_PRESENTS_NOT_DETERMINES,
    R2A_NO_EVIDENCE_LINE,
    derive_r2a_map,
    r2a_map_lines,
)
from tens_hq.staffing_whatif import StaffingWhatIfInput, WhatIfMode, assess_staffing_whatif

_POLICY = CaptureWindowPolicy(
    proc_lead_min_months=6,
    proc_lead_max_months=12,
    pl_addition_lead_min_months=9,
    pl_addition_lead_max_months=12,
    effective_date="2026-07-21",
)


def _render(**kwargs) -> str:
    return "\n".join(r2a_map_lines(derive_r2a_map(**kwargs)))


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


def _leads():
    return derive_incumbent_leads(_cf())


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


def _capture_window_estimated():
    return assess_capture_window("2028-05-31 00:00:00", date(2026, 7, 19), policy=_POLICY)


def _capture_window_unknown():
    return assess_capture_window(None, date(2026, 7, 19), policy=_POLICY)


# --- Fixed four-criteria order ------------------------------------------------


def test_four_rows_in_fixed_order() -> None:
    r2a_map = derive_r2a_map()
    criteria = [row.criterion for row in r2a_map.rows]
    assert criteria == ["(a)(1)", "(a)(2)", "(a)(3)", "(a)(4)"]


def test_render_order_matches_criteria_order() -> None:
    rendered = _render()
    idx1 = rendered.index("(a)(1)")
    idx2 = rendered.index("(a)(2)")
    idx3 = rendered.index("(a)(3)")
    idx4 = rendered.index("(a)(4)")
    assert idx1 < idx2 < idx3 < idx4


# --- Honest absence: (a)(1), (a)(2), (a)(4) can be empty; (a)(3) never is ----


def test_all_absent_a1_a2_a4_are_honest_no_evidence() -> None:
    r2a_map = derive_r2a_map()
    by_criterion = {row.criterion: row for row in r2a_map.rows}
    assert by_criterion["(a)(1)"].evidence_lines == (R2A_NO_EVIDENCE_LINE,)
    assert by_criterion["(a)(2)"].evidence_lines == (R2A_NO_EVIDENCE_LINE,)
    assert by_criterion["(a)(4)"].evidence_lines == (R2A_NO_EVIDENCE_LINE,)


def test_a3_capability_list_never_empty() -> None:
    r2a_map = derive_r2a_map()
    a3 = next(row for row in r2a_map.rows if row.criterion == "(a)(3)")
    assert a3.evidence_lines != (R2A_NO_EVIDENCE_LINE,)
    assert len(a3.evidence_lines) == 1
    assert "Administrative" in a3.evidence_lines[0]


# --- (a)(1) routing rail: inline geography disclaimer (audit MAJOR) --------


def test_a1_no_evidence_without_geography() -> None:
    r2a_map = derive_r2a_map(geography=None)
    a1 = next(row for row in r2a_map.rows if row.criterion == "(a)(1)")
    assert a1.evidence_lines == (R2A_NO_EVIDENCE_LINE,)


def test_a1_reproduces_geography_disclaimer_inline_byte_identical() -> None:
    # The routing rail requires REPRODUCING the standing disclaimer inline,
    # not merely citing the section -- lock it byte-identical to the real
    # constant so the local copy can never silently drift.
    r2a_map = derive_r2a_map(geography=_geo())
    a1 = next(row for row in r2a_map.rows if row.criterion == "(a)(1)")
    assert len(a1.evidence_lines) == 1
    assert GEOGRAPHY_CONTEXT_DISCLAIMER in a1.evidence_lines[0]
    assert "employment-potential evidence beyond context is analyst work" in (
        a1.evidence_lines[0].lower()
    )


def test_a1_disclaimer_not_a_supply_claim_language_present() -> None:
    rendered = _render(geography=_geo())
    assert "not a candidate-supply" in rendered.lower()
    assert "not evidence of available workers" in rendered.lower()


# --- (a)(2) routing: staffing wired, including CANNOT_COMPUTE branch -------


def test_a2_no_evidence_without_staffing() -> None:
    r2a_map = derive_r2a_map(staffing=None)
    a2 = next(row for row in r2a_map.rows if row.criterion == "(a)(2)")
    assert a2.evidence_lines == (R2A_NO_EVIDENCE_LINE,)


def test_a2_cites_computed_staffing() -> None:
    r2a_map = derive_r2a_map(staffing=_staffing_computed())
    a2 = next(row for row in r2a_map.rows if row.criterion == "(a)(2)")
    assert len(a2.evidence_lines) == 1
    assert "staffing what-if" in a2.evidence_lines[0].lower()
    assert "planning indicator" in a2.evidence_lines[0].lower()
    # No fabricated ratio value is restated here -- the map cites the
    # section, it does not re-derive or repeat the number.
    assert "%" not in a2.evidence_lines[0]


def test_a2_cannot_compute_staffing_is_not_the_flat_no_evidence_line() -> None:
    # A started-but-invalid entry is NOT "no packet evidence" -- it gets its
    # own honest, distinct line.
    r2a_map = derive_r2a_map(staffing=_staffing_cannot_compute())
    a2 = next(row for row in r2a_map.rows if row.criterion == "(a)(2)")
    assert a2.evidence_lines != (R2A_NO_EVIDENCE_LINE,)
    assert "could not be computed" in a2.evidence_lines[0].lower()


# --- (a)(4) routing: incumbent leads --------------------------------------


def test_a4_no_evidence_without_incumbent_leads() -> None:
    r2a_map = derive_r2a_map(incumbent_leads=None)
    a4 = next(row for row in r2a_map.rows if row.criterion == "(a)(4)")
    assert a4.evidence_lines == (R2A_NO_EVIDENCE_LINE,)


def test_a4_cites_incumbent_leads() -> None:
    r2a_map = derive_r2a_map(incumbent_leads=_leads())
    a4 = next(row for row in r2a_map.rows if row.criterion == "(a)(4)")
    assert len(a4.evidence_lines) == 1
    assert "incumbent & teaming leads" in a4.evidence_lines[0].lower()
    assert "pl-impact" in a4.evidence_lines[0].lower()
    assert "no computed share" in a4.evidence_lines[0].lower()


# --- Fixed epilogue: always present, regardless of inputs ------------------


def test_epilogue_lines_always_present_on_empty_render() -> None:
    rendered = _render()
    assert R2A_EPILOGUE_FMP in rendered
    assert R2A_EPILOGUE_PRESENTS_NOT_DETERMINES in rendered
    assert R2A_EPILOGUE_ALLOCATION in rendered
    assert R2A_EPILOGUE_ORIGINATION in rendered
    assert R2A_EPILOGUE_NEXT_ACTION in rendered


def test_epilogue_names_sourceamerica_and_cites_correct_statutes() -> None:
    rendered = _render()
    assert "sourceamerica" in rendered.lower()
    assert "41 u.s.c. 8503" in rendered.lower()
    assert "41 cfr 51-2.7" in rendered.lower()
    assert "41 cfr 51-2.4(a)" in rendered.lower()


def test_epilogue_allocation_does_not_promise_outcome() -> None:
    rendered = _render().lower()
    assert "does not itself promise allocation" in rendered
    assert "if added it's yours" not in rendered
    assert "guaranteed" not in rendered


# --- Capture Window epilogue: conditional citation --------------------------


def test_capture_window_epilogue_absent_band_states_unavailable() -> None:
    rendered = _render(capture_window=None)
    assert "no live capture window band is available" in rendered.lower()


def test_capture_window_epilogue_unknown_band_states_unavailable() -> None:
    rendered = _render(capture_window=_capture_window_unknown())
    assert "no live capture window band is available" in rendered.lower()


def test_capture_window_epilogue_estimated_band_cites_above() -> None:
    rendered = _render(capture_window=_capture_window_estimated())
    assert "already reflected in the capture window section" in rendered.lower()
    assert "9" in rendered and "12" in rendered  # the 9-12 month band cited


# --- Never a determination / no markers -------------------------------------


def test_no_met_unmet_marker_score_or_color() -> None:
    # Scoped past the standing presents-not-determines framing bullet
    # (which legitimately discusses assessment/rating in the negative,
    # exactly like PACKET_FRAMING's "no numeric rating... no ranking"
    # elsewhere in this codebase) so the guard checks the actual criterion
    # rows and epilogue, not the header.
    full = _render(
        geography=_geo(),
        staffing=_staffing_computed(),
        incumbent_leads=_leads(),
        capture_window=_capture_window_estimated(),
    )
    rendered = full[full.index("### (a)(1)") :].lower()
    for forbidden in (
        "score", "pwin", "/100", "bid/no-bid", "pursue", "call ",
        "met✅", "unmet", "✔", "❌", "green", "red", "yellow",
    ):
        assert forbidden not in rendered


def test_presents_not_determines_framing_present() -> None:
    rendered = _render().lower()
    assert "routes existing packet evidence" in rendered
    assert "does not assess, rate, or determine" in rendered
    assert "the commission determines suitability" in rendered


# --- Counsel-gated C3/C4 absence guard ------------------------------------
#
# Scope honesty (adversarial-verify finding): the map renders only fixed
# module constants keyed on evidence presence -- no input free-text reaches
# the render -- so what this guard truly locks is that the CONSTANTS never
# grow C3/C4 content (a future edit adding SB-goal-credit or LoS-cap copy
# fails here). It is not an input-injection guard; no input could inject.


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"geography": _geo()},
        {"staffing": _staffing_computed()},
        {"incumbent_leads": _leads()},
        {"capture_window": _capture_window_estimated()},
        {
            "geography": _geo(),
            "staffing": _staffing_computed(),
            "incumbent_leads": _leads(),
            "capture_window": _capture_window_estimated(),
        },
    ],
)
def test_no_counsel_gated_c3_c4_content_in_any_render(kwargs) -> None:
    # The term list and orthography-proof matcher are shared
    # (tests/conftest.py) with the whole-packet/export guard, the tour-copy
    # guard, and the source sweep, so a widened list widens every guard.
    assert counsel_gate_violations(_render(**kwargs)) == []


# --- No PSC-to-capability mapping table (capability list is prose only) ----


def test_capability_row_is_prose_not_a_table() -> None:
    r2a_map = derive_r2a_map()
    a3 = next(row for row in r2a_map.rows if row.criterion == "(a)(3)")
    assert "|" not in a3.evidence_lines[0]


# --- Everything-attached: all four criteria carry real evidence ------------


def test_everything_attached_all_four_criteria_have_non_empty_evidence() -> None:
    r2a_map = derive_r2a_map(
        geography=_geo(),
        staffing=_staffing_computed(),
        incumbent_leads=_leads(),
        capture_window=_capture_window_estimated(),
    )
    for row in r2a_map.rows:
        assert row.evidence_lines != (R2A_NO_EVIDENCE_LINE,)
        assert all(line.strip() for line in row.evidence_lines)
