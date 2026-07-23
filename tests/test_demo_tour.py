"""The guided tour must walk the seven-beat packet spine of docs/DEMO_SCRIPT.md.

These tests pin six packet beats followed by the governance close and lock every
widget label the tour copy quotes to the real ``bd_page.py`` source, the same
verbatim-label discipline the demo script itself was verified against.
"""

from __future__ import annotations

import re
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from conftest import counsel_gate_violations

from tens_hq import bd_page
from tens_hq.demo_tour import DEMO_TOUR
from tens_hq.pages import PAGE_RENDERERS


def test_demo_tour_has_seven_complete_beats_on_registered_pages():
    assert len(DEMO_TOUR) == 7
    assert all(beat.target_page in PAGE_RENDERERS for beat in DEMO_TOUR)
    assert all(beat.title and beat.highlight and beat.sentence for beat in DEMO_TOUR)


def test_demo_beats_are_immutable():
    with pytest.raises(FrozenInstanceError):
        DEMO_TOUR[0].title = "Changed"  # type: ignore[misc]


def test_tour_is_packet_first_with_governance_close():
    # The packet spine is six packet-page beats followed by the governance
    # close, with every target on the public two-page surface.
    assert tuple(beat.target_page for beat in DEMO_TOUR) == (
        ("BD Feasibility",) * 6 + ("Privacy & Governance",)
    )


def test_tour_opens_on_the_no_score_thesis():
    first = DEMO_TOUR[0].sentence.lower()
    assert "opportunity packet" in first
    assert "never renders a score, ranking, or bid/no-bid recommendation" in first


def test_every_quoted_widget_label_exists_verbatim_in_bd_page_source():
    # The tour copy quotes widget labels in straight single quotes. Each one
    # must exist verbatim in bd_page.py, so a renamed button breaks the tour
    # copy loudly instead of silently drifting from the UI.
    source = Path(bd_page.__file__).read_text(encoding="utf-8")
    quoted = [
        label
        for beat in DEMO_TOUR
        for label in re.findall(r"'([^']+)'", beat.sentence)
    ]
    assert quoted, "the tour is expected to quote real widget labels"
    for label in quoted:
        assert label in source, f"tour quotes a label not found in bd_page.py: {label!r}"
    # The bundled-SYNTHETIC checkbox label is used by TWO widgets (the
    # handoff intake and the R2b upload). Pin that count so renaming only
    # one of them -- which would silently orphan the tour copy -- fails
    # here instead of slipping past the substring check above.
    dup = "Use the bundled SYNTHETIC example instead of an upload"
    assert source.count(dup) == 2


def test_tour_copy_contains_no_counsel_gated_c3_c4_content():
    # DEMO_SCRIPT: "C3/C4 stays out of the demo" — including the operator's
    # scripted mouth. Shared term list with the packet/export/R2a guards.
    text = " ".join(
        f"{beat.title} {beat.highlight} {beat.sentence}" for beat in DEMO_TOUR
    )
    assert counsel_gate_violations(text) == []


def test_tour_copy_never_overclaims_verification():
    # The demo-script verify round killed a say-line claiming the packet
    # "re-verifies everything live"; the tour must never resurrect that
    # class of overclaim.
    text = " ".join(f"{beat.title} {beat.sentence}" for beat in DEMO_TOUR).lower()
    assert "re-verif" not in text
    assert "verified live" not in text
    assert "automatically verif" not in text
