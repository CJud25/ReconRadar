from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tens_hq import bd_page as bd_page_module
from tens_hq.case_store import CaseRepository
from tens_hq.connectors import AwardCandidate, ContractFactsRecord, ContractFactsResolution, GeographyRecord

# The deterministic synthetic generator is CPU-heavy on this stack (tens of
# seconds on Python 3.14 + pandas 3.0). app.py wraps it in load_demo_data via
# @st.cache_data, whose in-memory cache is a process-global keyed by the
# function's module/qualname/source -- and every AppTest.from_file run of app.py
# execs it under module "__main__", so they all share one cache entry. The
# _warm_demo_data_cache fixture below pays that cold cost ONCE up front, so each
# test's own .run() hits a warm cache. APP_TEST_TIMEOUT stays a generous ceiling
# on a *warm* render (well under it in practice), not a cold-generation budget.
APP_TEST_TIMEOUT = 120

# Generous ceiling for the single cold generation paid inside the pre-warm
# fixture; decoupled from the per-test timeout so a slow cold run cannot make
# the timed tests flaky.
WARM_TIMEOUT = 600


def _app_contract_facts(**overrides: object) -> ContractFactsRecord:
    base = dict(
        piid="APP-POP-TEST",
        generated_unique_award_id="CONT_AWD_APP_POP_TEST",
        award_type_code="D",
        award_type_description="DEFINITIVE CONTRACT",
        category="contract",
        date_signed="2024-06-01",
        total_obligation=100000.0,
        base_and_all_options=250000.0,
        period_start_date="2024-06-01",
        period_end_date="2025-05-31",
        period_potential_end_date="2028-05-31 00:00:00",
        toptier_agency_name="Department of Defense",
        subagency_name="Defense Logistics Agency",
        recipient_name="EXAMPLEWORKS SERVICES LLC",
        recipient_uei="EXMP1234ABC7",
        recipient_business_categories=("Small Business",),
        set_aside_code="SBA",
        set_aside_description="SMALL BUSINESS SET ASIDE",
        extent_competed_code="D",
        extent_competed_description="FULL AND OPEN COMPETITION AFTER EXCLUSION OF SOURCES",
        number_of_offers_received=3,
        naics_code="541512",
        naics_description="COMPUTER SYSTEMS DESIGN SERVICES",
        psc_code="DA01",
        psc_description="IT AND TELECOM",
        description="REPORTED AWARD DESCRIPTION",
        pop_city_name="FORT BELVOIR",
        pop_county_name="FAIRFAX",
        pop_state_code="VA",
        pop_country_code="USA",
        source_url="https://api.usaspending.gov/api/v2/awards/CONT_AWD_APP_POP_TEST/",
        retrieved_at="2026-07-22T12:00:00+00:00",
    )
    base.update(overrides)
    return ContractFactsRecord(**base)  # type: ignore[arg-type]


@pytest.fixture(scope="session", autouse=True)
def _warm_demo_data_cache():
    """Pre-warm the load_demo_data @st.cache_data cache once before any timed run.

    The first AppTest run of app.py in a process pays the full synthetic-data
    generation cost; without this, the earliest test's own .run() would race its
    timeout against a cold ~130-250s generation and flake. Running one throwaway
    AppTest here (with a long WARM_TIMEOUT) fills the shared cache, so the tests'
    own .run() calls stay fast and their timeouts remain meaningful assertions
    about render behavior rather than generation time.
    """

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    warm = AppTest.from_file(str(app_path), default_timeout=WARM_TIMEOUT)
    warm.run()
    assert not warm.exception


def test_packet_pages_render_without_streamlit_exception():
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    assert not app.exception, "BD Feasibility"
    assert app.radio[0].options == ["BD Feasibility", "Privacy & Governance"]
    assert not any(widget.key == "role" for widget in app.selectbox)

    app.radio[0].set_value("Privacy & Governance").run()
    assert not app.exception, "Privacy & Governance"
    # §5.10: the dead "Planning controls" (Scenario selectbox, Planning
    # target slider) never changed anything on the Governance page and are
    # removed -- in normal (non-pilot) mode, not just pilot mode.
    assert not any(widget.label == "Scenario" for widget in app.selectbox)
    assert not any(widget.label == "Planning target" for widget in app.slider)


def test_governance_page_describes_only_shipped_capabilities():
    # §5.1 / ADR-024: the Decision-boundaries block used to name capabilities
    # that were deleted with ADR-016 (site views, source scores, organization
    # scenarios, small-sample shrinkage, the start-stage gate) -- a
    # self-contradiction two lines from the page's own no-score thesis. Assert
    # the forbidden phrases are gone and the on-thesis bullet survives.
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("Privacy & Governance").run()
    assert not app.exception

    rendered = "\n".join(block.value for block in app.markdown).lower()
    for forbidden in (
        "site views",
        "source scores",
        "organization scenarios",
        "small-sample shrinkage",
        "start-stage gate",
        "summed hours",
    ):
        assert forbidden not in rendered, forbidden

    assert "never a feasibility score" in rendered
    assert "bid/no-bid" in rendered


def test_bd_page_lands_on_opportunity_packet_first():
    # §15-#2 / §12.2 / §5.2 (Finding drift #3): the headline product used to
    # sit behind an empty Cases landing tab. Reordering st.tabs so the packet
    # is first makes it the surface Streamlit activates on first paint.
    # `st.tabs` renders every tab body regardless of order in AppTest, so the
    # render-present checks below are sanity only -- the two order assertions
    # are the actual proof.
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    # Primary (behavioral order): there is exactly one st.tabs call in
    # src/tens_hq, so app.tabs is that single group in declaration order.
    assert app.tabs[0].label == "Opportunity Packet"

    # Belt-and-suspenders (source-level, version-independent): pin the
    # reorder directly against the st.tabs([...]) list literal.
    source = Path(bd_page_module.__file__).read_text(encoding="utf-8")
    match = re.search(r"st\.tabs\(\s*\[\s*\"([^\"]+)\"", source)
    assert match is not None, "could not locate the st.tabs([...]) call in bd_page.py"
    assert match.group(1) == "Opportunity Packet"

    # Secondary (content still renders): packet subheader, R2a heading, and
    # the no-score framing caption are all present somewhere on the page.
    subheaders = "\n".join(block.value for block in app.subheader)
    assert "Opportunity Packet" in subheaders
    packet_markdown = "\n".join(block.value for block in app.markdown)
    assert "## R2a determination-support map" in packet_markdown
    captions = "\n".join(block.value for block in app.caption)
    assert "never renders a score, ranking, or bid/no-bid recommendation" in captions


def test_guided_demo_navigation_is_callback_safe_and_resumes_from_query_params():
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()

    assert app.radio[0].key == "nav"
    next(button for button in app.button if button.key == "tour_next").click().run()
    assert not app.exception
    # Beat 1 of the packet-spine tour stays on the packet page.
    assert app.radio[0].value == "BD Feasibility"
    assert app.session_state["tour_step"] == 1
    assert app.query_params["nav"] == ["BD Feasibility"]
    assert app.query_params["tour"] == ["1"]

    resumed = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    resumed.query_params["nav"] = "Privacy & Governance"
    resumed.query_params["tour"] = "4"
    resumed.run()
    assert not resumed.exception
    assert resumed.radio[0].value == "Privacy & Governance"
    assert resumed.session_state["tour_step"] == 4


def test_opportunity_packet_r2b_cross_reference_renders_with_bundled_sample():
    # Drive the wired R2b flow through the real widgets (offline): the button
    # handler's parse -> match -> session-state -> render path is otherwise only
    # unit-covered. Uses the bundled synthetic sample, so it opens no socket.
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    def _ti(key):
        return next(widget for widget in app.text_input if widget.key == key)

    _ti("op_packet_worksite_city").set_value("Denver")
    _ti("op_packet_state").set_value("CO")
    _ti("op_packet_service_type").set_value("Custodial")
    next(box for box in app.checkbox if box.key == "op_packet_pl_use_sample").set_value(True)
    app.run()
    assert not app.exception

    next(button for button in app.button if button.key == "op_packet_pl_run").click().run()
    assert not app.exception

    packet = "\n".join(block.value for block in app.markdown)
    assert "Procurement List cross-reference (R2b)" in packet
    # The bundled example is labeled synthetic in the OUTPUT, and the Denver
    # Custodial line renders as a character-equal string fact (not a verdict).
    assert "EXAMPLE DATA" in packet
    assert "character-equal" in packet
    # No score is manufactured even on the populated render path.
    assert "pwin" not in packet.lower()
    # A success toast confirms the offline parse -> match path ran end to end.
    assert any("Cross-referenced" in getattr(msg, "value", "") for msg in app.success)


def test_opportunity_packet_live_facts_button_is_wired():
    # The USAspending live-pull control renders offline and is wired; do NOT click
    # it (a live pull would hit the autouse socket guard). This proves the tab
    # renders exception-free and the control exists.
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception
    assert any(button.key == "op_packet_facts_pull" for button in app.button)


def test_live_facts_pull_prefills_empty_domestic_place_inputs(monkeypatch) -> None:
    """A resolved USA award fills all empty place widgets and flags confirmation."""

    record = _app_contract_facts()

    def fake_pull(piid: str, **_kwargs: object) -> ContractFactsResolution:
        return ContractFactsResolution(piid=piid, record=record)

    monkeypatch.setattr("tens_hq.bd_page.pull_contract_facts", fake_pull)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    def _ti(key):
        return next(widget for widget in app.text_input if widget.key == key)

    _ti("op_packet_piid").set_value(record.piid)
    app.run()
    next(
        button for button in app.button if button.key == "op_packet_facts_pull"
    ).click().run()
    assert not app.exception
    assert _ti("op_packet_county").value == "FAIRFAX"
    assert _ti("op_packet_state").value == "VA"
    assert _ti("op_packet_worksite_city").value == "FORT BELVOIR"
    expected = (
        "Attached live USAspending contract facts. Prefilled empty place inputs "
        "from the award's cited place of performance — confirm them."
    )
    assert any(getattr(msg, "value", "") == expected for msg in app.success)


def test_live_facts_pull_preserves_analyst_county(monkeypatch) -> None:
    """A nonblank analyst county is never overwritten while other blanks may prefill."""

    record = _app_contract_facts()

    def fake_pull(piid: str, **_kwargs: object) -> ContractFactsResolution:
        return ContractFactsResolution(piid=piid, record=record)

    monkeypatch.setattr("tens_hq.bd_page.pull_contract_facts", fake_pull)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    def _ti(key):
        return next(widget for widget in app.text_input if widget.key == key)

    _ti("op_packet_piid").set_value(record.piid)
    _ti("op_packet_county").set_value("ANALYST COUNTY")
    app.run()
    next(
        button for button in app.button if button.key == "op_packet_facts_pull"
    ).click().run()
    assert not app.exception
    assert _ti("op_packet_county").value == "ANALYST COUNTY"
    assert _ti("op_packet_state").value == "VA"
    assert _ti("op_packet_worksite_city").value == "FORT BELVOIR"


def test_live_facts_pull_skips_all_prefill_for_non_usa_award(monkeypatch) -> None:
    """An explicitly non-USA award leaves every place input and success text unchanged."""

    record = _app_contract_facts(
        pop_city_name="OTTAWA",
        pop_county_name="OTTAWA",
        pop_state_code="ON",
        pop_country_code="CAN",
    )

    def fake_pull(piid: str, **_kwargs: object) -> ContractFactsResolution:
        return ContractFactsResolution(piid=piid, record=record)

    monkeypatch.setattr("tens_hq.bd_page.pull_contract_facts", fake_pull)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    def _ti(key):
        return next(widget for widget in app.text_input if widget.key == key)

    _ti("op_packet_piid").set_value(record.piid)
    app.run()
    next(
        button for button in app.button if button.key == "op_packet_facts_pull"
    ).click().run()
    assert not app.exception
    assert _ti("op_packet_county").value == ""
    assert _ti("op_packet_state").value == ""
    assert _ti("op_packet_worksite_city").value == ""
    success_values = [getattr(msg, "value", "") for msg in app.success]
    assert "Attached live USAspending contract facts." in success_values
    assert not any("Prefilled empty place inputs" in value for value in success_values)


def _award_candidate(generated_internal_id: str, recipient_name: str) -> AwardCandidate:
    return AwardCandidate(
        award_id="APP-POP-TEST",
        generated_internal_id=generated_internal_id,
        recipient_name=recipient_name,
        subagency_name="Defense Logistics Agency",
        award_amount=1000.0,
        start_date="2020-01-01",
        contract_award_type="DELIVERY ORDER",
        naics_code="541519",
        psc_code="DA01",
    )


def test_disambiguation_pick_also_prefills_place_inputs(monkeypatch) -> None:
    """The 'Use this award' path applies the same prefill + honest suffix as the
    direct pull -- the two handlers must never diverge silently."""

    record = _app_contract_facts()
    candidates = (
        _award_candidate("CONT_AWD_ONE", "ONE CO"),
        _award_candidate("CONT_AWD_TWO", "TWO CO"),
    )

    def fake_pull(
        piid: str, generated_internal_id: str | None = None, **_kwargs: object
    ) -> ContractFactsResolution:
        if generated_internal_id is None:
            return ContractFactsResolution(piid=piid, candidates=candidates)
        return ContractFactsResolution(piid=piid, record=record)

    monkeypatch.setattr("tens_hq.bd_page.pull_contract_facts", fake_pull)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    def _ti(key):
        return next(widget for widget in app.text_input if widget.key == key)

    _ti("op_packet_piid").set_value(record.piid)
    app.run()
    next(
        button for button in app.button if button.key == "op_packet_facts_pull"
    ).click().run()
    assert not app.exception
    picker = next(
        widget for widget in app.selectbox if widget.key == "op_packet_facts_pick"
    )
    picker.set_value("CONT_AWD_TWO")
    app.run()
    next(
        button for button in app.button if button.key == "op_packet_facts_pick_go"
    ).click().run()
    assert not app.exception
    assert _ti("op_packet_county").value == "FAIRFAX"
    assert _ti("op_packet_state").value == "VA"
    assert _ti("op_packet_worksite_city").value == "FORT BELVOIR"
    expected = (
        "Attached the selected award's live contract facts. Prefilled empty place "
        "inputs from the award's cited place of performance — confirm them."
    )
    assert any(getattr(msg, "value", "") == expected for msg in app.success)


def test_whitespace_place_component_never_claims_a_prefill(monkeypatch) -> None:
    """A whitespace-only upstream component is judged blank exactly like the
    target widget: nothing is written and the success suffix never appears."""

    record = _app_contract_facts(
        pop_city_name=" ",
        pop_county_name=None,
        pop_state_code=None,
        pop_country_code="USA",
    )

    def fake_pull(piid: str, **_kwargs: object) -> ContractFactsResolution:
        return ContractFactsResolution(piid=piid, record=record)

    monkeypatch.setattr("tens_hq.bd_page.pull_contract_facts", fake_pull)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    def _ti(key):
        return next(widget for widget in app.text_input if widget.key == key)

    _ti("op_packet_piid").set_value(record.piid)
    app.run()
    next(
        button for button in app.button if button.key == "op_packet_facts_pull"
    ).click().run()
    assert not app.exception
    assert _ti("op_packet_worksite_city").value == ""
    success_values = [getattr(msg, "value", "") for msg in app.success]
    assert "Attached live USAspending contract facts." in success_values
    assert not any("Prefilled empty place inputs" in value for value in success_values)


def test_inline_md_flattens_and_escapes_toast_interpolations() -> None:
    """Upstream-fed values interpolated into Markdown-rendered toasts cannot
    forge structure: line boundaries flatten to spaces and link/code/emphasis
    syntax is escaped (the packet renderers' vendored _md discipline)."""

    from tens_hq.bd_page import _inline_md

    hostile = "FORT BELVOIR\n## CLEARED\r\n[x](javascript:alert(1))`code`*em*"
    flat = _inline_md(hostile)
    assert "\n" not in flat and "\r" not in flat
    assert "\\[" in flat and "\\(" in flat and "\\`" in flat and "\\*" in flat


def test_opportunity_packet_subawards_and_directory_controls_are_wired_offline():
    # A5: the subawards live-pull button and the directory upload control both
    # render offline and are wired; do NOT click the pull button (a live pull
    # would hit the autouse socket guard). No contract facts are attached in
    # this test, so the subawards button must render DISABLED (no resolved
    # award to key a pull to) rather than crash.
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    subawards_button = next(button for button in app.button if button.key == "op_packet_subawards_pull")
    assert subawards_button.disabled is True
    # The pinned streamlit (1.46.1) has no AppTest.file_uploader property and its
    # generic get() returns key-less UnknownElements, so assert the directory
    # uploader version-safely: both packet uploaders rendered (R2b PL + the A5
    # directory), and the directory control's distinctive caption is present.
    assert len(app.get("file_uploader")) >= 2
    assert any(
        "cross-reference reported subawardee names" in caption.value
        for caption in app.caption
    )

    packet = "\n".join(block.value for block in app.markdown)
    assert "## Incumbent & teaming leads" not in packet


def test_opportunity_packet_federal_register_pull_controls_are_wired_offline():
    # A4: the Federal Register PL-activity search-term input and pull button
    # both render offline and are wired; do NOT click the pull button (a live
    # pull would hit the autouse socket guard). Mirrors the wired-button
    # house precedent (test_opportunity_packet_live_facts_button_is_wired /
    # the subawards sibling above) -- no session-state injection, no click on
    # a network button. The section-body render itself is owned by T2's
    # builder unit tests (test_pl_activity.py / test_opportunity_packet.py).
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    assert any(widget.key == "op_packet_fr_term" for widget in app.text_input)
    fr_button = next(button for button in app.button if button.key == "op_packet_fr_pull")
    assert fr_button.disabled is False

    packet = "\n".join(block.value for block in app.markdown)
    assert "## Procurement List activity (Federal Register)" not in packet

    assert any(
        "four independent analyst-initiated live requests in total" in caption.value
        for caption in app.caption
    )
    assert any(
        "fourth of this packet page's four independent analyst-initiated live requests"
        in caption.value
        for caption in app.caption
    )


def test_opportunity_packet_export_button_renders_offline_with_nothing_attached():
    # A7: the assembled cited export (Section ledger + Source manifest) must
    # compose exception-free even on the all-absent render -- no contract
    # facts, subawards, directory, geography, or PL cross-reference attached.
    # Do NOT click any live-pull button (the autouse socket guard would trip);
    # this only proves the export composition path is wired offline.
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    # Probed empirically in BOTH pinned interpreters (streamlit 1.46.1 via
    # .venv, and the local 1.58.0): AppTest has no .download_button property
    # in either version, and app.get("download_button") returns a key-less
    # UnknownElement (proto carries no data/file_name) whose .key is always
    # None but whose .label IS the button's visible label in both versions.
    # Fall back from .key to .label accordingly.
    download_buttons = app.get("download_button")
    assert any(
        getattr(button, "key", None) == "op_packet_export"
        or getattr(button, "label", None) == "Export Opportunity Packet (Markdown)"
        for button in download_buttons
    )

    # The D1 caption naming the export's extra appendices is present.
    assert any(
        "Section ledger" in caption.value and "Source manifest" in caption.value
        for caption in app.caption
    )


def test_opportunity_packet_radar_handoff_sample_prefills_and_renders_origin():
    # A2: drive the wired handoff-intake flow through the real widgets
    # (offline): parse -> session-state -> prefill -> render is otherwise
    # only unit-covered. Uses the bundled SYNTHETIC sample, so it opens no
    # socket (file_uploader is unreachable under the pinned streamlit
    # 1.46.1 AppTest, so the checkbox+button path is the only reachable one,
    # mirroring the R2b sample-checkbox precedent above).
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    def _ti(key):
        return next(widget for widget in app.text_input if widget.key == key)

    next(box for box in app.checkbox if box.key == "op_packet_handoff_use_sample").set_value(True)
    app.run()
    assert not app.exception

    next(button for button in app.button if button.key == "op_packet_handoff_use").click().run()
    assert not app.exception

    # The four retrieval inputs are prefilled from the bundled sample
    # (SYNTH-A2-0001 / Denver, CO) -- and nothing else (§1.2).
    assert _ti("op_packet_piid").value == "SYNTH-A2-0001"
    assert _ti("op_packet_county").value == "Denver"
    assert _ti("op_packet_state").value == "CO"
    assert _ti("op_packet_worksite_city").value == "Denver"
    # The analyst set-aside input must NEVER be prefilled from a handoff claim.
    assert _ti("op_packet_set_aside").value == ""

    packet = "\n".join(block.value for block in app.markdown)
    # The full section header (not just the always-present intake caption
    # above, which shares the "Origin — Radar handoff" words).
    assert "## Origin — Radar handoff (context, not evidence)" in packet
    assert "SYNTHETIC example handoff" in packet
    assert "not reported in snapshot (null)" in packet
    assert any("Attached the Radar handoff" in getattr(msg, "value", "") for msg in app.success)


def test_opportunity_packet_radar_handoff_drops_out_on_piid_retarget():
    # D9: once the analyst edits the PIID away from the handoff's claimed
    # PIID, the Origin section must drop out -- it no longer describes this
    # packet.
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()

    next(box for box in app.checkbox if box.key == "op_packet_handoff_use_sample").set_value(True)
    app.run()
    next(button for button in app.button if button.key == "op_packet_handoff_use").click().run()
    assert not app.exception

    packet_before = "\n".join(block.value for block in app.markdown)
    # The full section header (not just the always-present intake caption
    # above, which shares the "Origin — Radar handoff" words).
    assert "## Origin — Radar handoff (context, not evidence)" in packet_before

    next(widget for widget in app.text_input if widget.key == "op_packet_piid").set_value(
        "SOME-OTHER-PIID"
    ).run()
    assert not app.exception
    packet_after = "\n".join(block.value for block in app.markdown)
    # The always-present intake caption still says "Origin — Radar handoff
    # intake" -- only the packet's own section header must be gone.
    assert "## Origin — Radar handoff (context, not evidence)" not in packet_after


def test_opportunity_packet_offline_synthetic_example_facts_populate_the_flagship_moment():
    # ADR-025 / §15-#3: following the guided demo offline (handoff sample ->
    # Pull contract facts (live)) must reach a populated, clearly-SYNTHETIC
    # Contract Facts + Eligibility Gate + Capture Window render with no red
    # error, using only the bundled synthetic PIID -- no socket opened (the
    # socket guard would fail this test if the offline branch fell through
    # to a real network call).
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    def _ti(key):
        return next(widget for widget in app.text_input if widget.key == key)

    next(box for box in app.checkbox if box.key == "op_packet_handoff_use_sample").set_value(True)
    app.run()
    next(button for button in app.button if button.key == "op_packet_handoff_use").click().run()
    assert not app.exception
    assert _ti("op_packet_piid").value == "SYNTH-A2-0001"

    next(button for button in app.button if button.key == "op_packet_facts_pull").click().run()
    assert not app.exception

    assert any(
        "Loaded the bundled SYNTHETIC example contract facts" in getattr(msg, "value", "")
        for msg in app.success
    )

    packet = "\n".join(block.value for block in app.markdown)
    assert "## Contract Facts (SYNTHETIC example — offline, not a live retrieval)" in packet
    assert "## Contract Facts (live — USAspending, cited)" not in packet
    # Obligated and ceiling both appear, as distinct lines/values.
    assert "$180,000.00" in packet
    assert "$420,000.00" in packet
    # The gate and capture window both render off the attached synthetic facts.
    assert "## Eligibility gate (can the NPA prime?)" in packet
    assert "## Capture window (estimated solicitation + R2a start-by band)" in packet


def test_opportunity_packet_staffing_whatif_absent_without_baseline():
    # A6: the section stays absent until a baseline value is entered -- the
    # packet stays usable without it.
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    packet = "\n".join(block.value for block in app.markdown)
    assert "## Staffing what-if" not in packet
    assert any(
        "labeled planning indicator" in caption.value for caption in app.caption
    )


def test_opportunity_packet_staffing_whatif_hours_mode_computed_render():
    # A6: driving the real HOURS-mode number_input widgets (offline, no
    # network) reproduces staffing_whatif's own hand-computed test vector --
    # baseline 750/1000 = 75.0%, scenario adds 100/200 -> combined 850/1200
    # = 70.8%, delta -4.2 pp.
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    def _ni(key):
        return next(widget for widget in app.number_input if widget.key == key)

    _ni("op_packet_whatif_baseline_qh").set_value(750.0)
    _ni("op_packet_whatif_baseline_th").set_value(1000.0)
    _ni("op_packet_whatif_scenario_th").set_value(200.0)
    _ni("op_packet_whatif_count_hours").set_value(100.0)
    app.run()
    assert not app.exception

    packet = "\n".join(block.value for block in app.markdown)
    assert "## Staffing what-if" in packet
    assert "75.0%" in packet
    assert "70.8%" in packet
    assert "-4.2 pp" in packet
    assert "planning indicator" in packet.lower()
    assert "(a)(2)" in packet


def test_opportunity_packet_staffing_whatif_fte_mode_partial_entry_cannot_compute():
    # A6: the FTE-mode checkbox toggles entry mode; a PARTIAL baseline (code
    # 01 entered, code 02 left blank) fails closed to the honest
    # "cannot compute" render rather than a fabricated number, and the
    # mode-aware FTE approximation caveat is present (audit MAJOR).
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    next(box for box in app.checkbox if box.key == "op_packet_whatif_fte_mode").set_value(
        True
    )
    app.run()
    assert not app.exception

    def _ni(key):
        return next(widget for widget in app.number_input if widget.key == key)

    _ni("op_packet_whatif_baseline_01").set_value(70.0)
    app.run()
    assert not app.exception

    packet = "\n".join(block.value for block in app.markdown)
    assert "## Staffing what-if" in packet
    assert "cannot compute" in packet.lower()
    assert "approximation" in packet.lower()
    assert "cannot perform the supervisory/indirect exclusion" in packet.lower()


def test_opportunity_packet_r2a_map_always_renders_last():
    # R2a (ADR-022): the determination-support map renders UNCONDITIONALLY,
    # even on a completely blank packet, as the packet's final section.
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    packet = "\n".join(block.value for block in app.markdown)
    assert "## R2a determination-support map" in packet
    assert "no packet evidence speaks to this criterion yet" in packet.lower()
    assert "sourceamerica" in packet.lower()
    # It is the LAST "## " section: no other top-level packet header follows it.
    after_r2a = packet[packet.index("## R2a determination-support map") + 2 :]
    assert "\n## " not in after_r2a


def test_opportunity_packet_r2a_map_wires_staffing_into_a2():
    # R2a (ADR-022): once a HOURS-mode staffing baseline is entered through
    # the real widgets, the (a)(2) row cites it instead of the honest
    # absence line.
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    def _ni(key):
        return next(widget for widget in app.number_input if widget.key == key)

    _ni("op_packet_whatif_baseline_qh").set_value(750.0)
    _ni("op_packet_whatif_baseline_th").set_value(1000.0)
    _ni("op_packet_whatif_scenario_th").set_value(200.0)
    _ni("op_packet_whatif_count_hours").set_value(100.0)
    app.run()
    assert not app.exception

    packet = "\n".join(block.value for block in app.markdown)
    r2a_section = packet[packet.index("## R2a determination-support map") :]
    a2_section = r2a_section[
        r2a_section.index("(a)(2)") : r2a_section.index("(a)(3)")
    ].lower()
    assert "staffing what-if" in a2_section
    assert "no packet evidence speaks to this criterion yet" not in a2_section


def test_pilot_mode_boots_with_packet_surface_only(monkeypatch):
    # The public app is always the governed packet surface. Pilot mode narrows
    # its presentation by hiding the guided tour and planning controls.
    monkeypatch.setenv("TENS_HQ_PILOT_MODE", "1")
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.query_params["nav"] = "not-a-page"
    app.run()
    assert not app.exception
    assert app.radio[0].options == ["BD Feasibility", "Privacy & Governance"]
    assert app.radio[0].value == "BD Feasibility"
    # No planning-scenario selector; the BD page's own form widgets (e.g. the
    # case form's team selectbox) remain.
    assert not any(widget.label == "Scenario" for widget in app.selectbox)
    assert not any(button.key == "tour_next" for button in app.button)


def test_scan_tab_offline_nib_npa_sample_checkbox_is_wired() -> None:
    # ADR-026 / §15-#6 / §5.4: the tracker's NIB/NPA lane must be demonstrable
    # offline. The Scan form only renders once a case exists (_case_select
    # returns None otherwise), so a case is seeded directly against the
    # session-scoped isolated ledger before the AppTest boots. This proves the
    # checkbox is wired without depending on -- or asserting -- an empty
    # ledger (a prior test in this session may already have seeded cases).
    repository = CaseRepository(os.environ["TENS_HQ_DB_PATH"])
    try:
        repository.create_case("Denver NIB/NPA offline check", "Denver", "CO")
    finally:
        repository.close()

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    checkbox = next(box for box in app.checkbox if box.key == "scan_use_sample_nib_npa")
    assert checkbox.label == "Use the bundled SYNTHETIC NIB/NPA example instead of an upload"
    assert checkbox.value is False


def test_acs_year_change_detaches_stale_geography(monkeypatch) -> None:
    # §8 confirmed bug / §12.4 partial: README.md's "editing an input detaches
    # any stale result built on it" invariant did not hold for the ACS vintage
    # year -- the reuse guard matched on county+state only. Pull at 2022, then
    # change the year to 2019 without re-pulling; the packet must fall back to
    # the honest "Not yet retrieved" placeholder rather than keep showing the
    # stale 2022 figure. Offline (no socket): pull_geography_context is
    # monkeypatched, so the autouse socket guard would fail this test if the
    # code path ever fell through to a real network call.
    def fake_pull(county: str, state: str, *, year: int, **_kwargs: object) -> GeographyRecord:
        return GeographyRecord(
            county_name=f"{county.title()} County",
            state_code=state,
            state_fips="08",
            county_fips="031",
            total_population=100000,
            with_disability=12000,
            disability_percent=12.0,
            acs_survey="ACS 5-Year",
            acs_vintage_year=year,
            source_url=f"https://api.census.gov/data/{year}/acs/acs5",
            retrieved_at="2026-07-23T00:00:00Z",
        )

    monkeypatch.setattr("tens_hq.bd_page.pull_geography_context", fake_pull)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    def _ti(key):
        return next(widget for widget in app.text_input if widget.key == key)

    def _ni(key):
        return next(widget for widget in app.number_input if widget.key == key)

    _ti("op_packet_county").set_value("Denver")
    _ti("op_packet_state").set_value("CO")
    _ni("op_packet_year").set_value(2022)
    app.run()
    next(button for button in app.button if button.key == "op_packet_pull").click().run()
    assert not app.exception

    packet = "\n".join(block.value for block in app.markdown)
    assert "vintage 2022" in packet

    _ni("op_packet_year").set_value(2019)
    app.run()
    assert not app.exception

    packet = "\n".join(block.value for block in app.markdown)
    assert "vintage 2022" not in packet
    assert "Not yet retrieved." in packet


def test_unexpected_contract_facts_error_is_logged_and_not_blamed_on_the_source(
    monkeypatch, caplog
) -> None:
    # §15-#9 / §5.7: an unexpected internal error (anything other than the
    # already-handled ConnectorError) must be logged server-side and must
    # NOT tell the operator "the public source may be unavailable" -- that
    # phrase mislabels a code bug as a network outage. Offline: the raised
    # ValueError never reaches the network, so the autouse socket guard is
    # not exercised either way.
    def fake_pull(piid: str, **_kwargs: object):
        raise ValueError("boom")

    monkeypatch.setattr("tens_hq.bd_page.pull_contract_facts", fake_pull)
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=APP_TEST_TIMEOUT)
    app.run()
    app.radio[0].set_value("BD Feasibility").run()
    assert not app.exception

    next(widget for widget in app.text_input if widget.key == "op_packet_piid").set_value(
        "47QRAA24D0012"
    )
    app.run()
    with caplog.at_level(logging.ERROR, logger="tens_hq.bd_page"):
        next(button for button in app.button if button.key == "op_packet_facts_pull").click().run()
    assert not app.exception

    error_text = "\n".join(msg.value for msg in app.error)
    assert "source may be unavailable" not in error_text
    assert "logged" in error_text.lower()
    assert any(
        "contract-facts pull failed unexpectedly" in record.message for record in caplog.records
    )
