"""Offline unit tests for the N6 set-aside eligibility gate."""

from __future__ import annotations

from tens_hq.eligibility_gate import (
    EligibilityState,
    assess_eligibility,
    eligibility_gate_lines,
)


def _render(raw_set_aside: str | None) -> str:
    return "\n".join(eligibility_gate_lines(assess_eligibility(raw_set_aside)))


def test_blank_values_are_unknown_and_never_default_permissive() -> None:
    for raw in (None, "", "   "):
        gate = assess_eligibility(raw)
        rendered = "\n".join(eligibility_gate_lines(gate))

        assert gate.raw_set_aside == raw
        assert gate.state is EligibilityState.UNKNOWN
        assert gate.set_aside_label is None
        assert gate.set_aside_family is None
        assert gate.recognized is False
        assert "blank \u2260 unrestricted" in rendered
        assert "Verify against SAM.gov / USAspending" in rendered
        assert "green" not in rendered.casefold()


def test_none_code_is_unrestricted_but_not_a_pursuit_recommendation() -> None:
    for raw in ("NONE", " none "):
        gate = assess_eligibility(raw)
        rendered = "\n".join(eligibility_gate_lines(gate))
        rendered_casefold = rendered.casefold()

        assert gate.raw_set_aside == raw
        assert gate.state is EligibilityState.UNRESTRICTED
        assert gate.set_aside_label == "No set-aside (set-aside = NONE)"
        assert gate.set_aside_family is None
        assert gate.recognized is True
        assert "eligibility-open" in rendered_casefold
        assert "amber" in rendered_casefold
        assert "NOT a pursuit recommendation" in rendered
        assert "not" in rendered_casefold
        assert "competable" in rendered_casefold or "full-and-open" in rendered_casefold
        assert "separate" in rendered_casefold
        assert "green" not in rendered_casefold


def test_all_three_states_never_render_green_or_pursuit_language() -> None:
    # Cover every distinct render branch, including all three SET_ASIDE_BARRED
    # sub-renders (small_business / buy_indian / unverified) and the partial-note
    # path, so a future edit to any barred rationale string stays guarded.
    cases = {
        None: EligibilityState.UNKNOWN,
        "NONE": EligibilityState.UNRESTRICTED,
        "8A": EligibilityState.SET_ASIDE_BARRED,  # small_business rationale
        "iee": EligibilityState.SET_ASIDE_BARRED,  # buy_indian rationale
        "sbp": EligibilityState.SET_ASIDE_BARRED,  # small_business + partial note
        "ZZZ": EligibilityState.SET_ASIDE_BARRED,  # unverified rationale
    }
    forbidden = ("green", "\u2705", "proceed", " go ", "pursue this")

    for raw, expected_state in cases.items():
        gate = assess_eligibility(raw)
        rendered = "\n".join(eligibility_gate_lines(gate)).casefold()

        assert gate.state is expected_state
        for token in forbidden:
            assert token not in rendered


def test_partial_set_aside_notes_the_unrestricted_remainder() -> None:
    gate = assess_eligibility("SBP")
    rendered = "\n".join(eligibility_gate_lines(gate))
    assert gate.state is EligibilityState.SET_ASIDE_BARRED
    assert gate.set_aside_label == "Partial Small Business"
    # A partial set-aside must not read as closing the whole opportunity: the
    # unrestricted remainder is named as a separate, unassessed question.
    assert "PARTIAL set-aside" in rendered
    assert "unrestricted remainder" in rendered
    # A non-partial small-business code does NOT get the partial note.
    full = "\n".join(eligibility_gate_lines(assess_eligibility("8A")))
    assert "PARTIAL set-aside" not in full


def test_recognized_set_aside_codes_are_barred_with_friendly_labels() -> None:
    cases = {
        "8A": "8(a) set-aside",
        "HZC": "HUBZone",
        "SDVOSBC": "SDVOSB",
    }
    for raw, label in cases.items():
        gate = assess_eligibility(raw)
        rendered = "\n".join(eligibility_gate_lines(gate))

        assert gate.state is EligibilityState.SET_ASIDE_BARRED
        assert gate.set_aside_label == label
        assert gate.set_aside_family == "small_business"
        assert gate.recognized is True
        assert f'"{raw}"' in rendered
        assert label in rendered
        assert "13 CFR 121.105" in rendered
        assert "R1-teaming" in rendered
        assert "not assessed here" in rendered


def test_buy_indian_code_is_barred_without_small_business_certainty() -> None:
    gate = assess_eligibility("iee")
    rendered = "\n".join(eligibility_gate_lines(gate))

    assert gate.state is EligibilityState.SET_ASIDE_BARRED
    assert gate.set_aside_label == "Indian Economic Enterprise"
    assert gate.set_aside_family == "buy_indian"
    assert gate.recognized is True
    assert "Buy-Indian" in rendered
    assert "Indian Economic Enterprise" in rendered
    assert "small business concern" not in rendered.casefold()
    assert "121.105" not in rendered


def test_code_lookup_is_trimmed_and_case_insensitive_but_raw_is_verbatim() -> None:
    gate = assess_eligibility(" hzc ")
    rendered = "\n".join(eligibility_gate_lines(gate))

    assert gate.raw_set_aside == " hzc "
    assert gate.state is EligibilityState.SET_ASIDE_BARRED
    assert gate.set_aside_label == "HUBZone"
    assert '" hzc "' in rendered


def test_unrecognized_nonempty_code_is_barred_without_a_guessed_meaning() -> None:
    gate = assess_eligibility("ZZZ")
    rendered = "\n".join(eligibility_gate_lines(gate))

    assert gate.state is EligibilityState.SET_ASIDE_BARRED
    assert gate.set_aside_label is None
    assert gate.set_aside_family is None
    assert gate.recognized is False
    assert '"ZZZ"' in rendered
    assert "unrecognized set-aside code \u2014 treated as a set-aside" in rendered
    assert "not confirmed" in rendered.casefold()
    assert "verify" in rendered.casefold()
    assert "this work is set aside for small-business" not in rendered.casefold()
    assert "121.105" not in rendered


def test_render_is_caveat_first_and_presents_without_determining() -> None:
    rendered = _render("8A")
    rendered_casefold = rendered.casefold()

    assert "presents the cited set-aside status plus a structural rule" in rendered
    assert "does not determine eligibility" in rendered
    assert "The human decides" in rendered
    assert "R1-teaming" in rendered
    assert "not assessed here" in rendered
    assert "pursue" not in rendered_casefold
    assert "recommended route" not in rendered_casefold
    assert "next step" not in rendered_casefold
    assert rendered.index("13 CFR 121.105") < rendered.index("Raw set-aside")


def test_render_contains_no_numeric_rating_or_bid_decision_language() -> None:
    for raw in (None, "NONE", "8A", "ZZZ"):
        rendered = _render(raw).casefold()
        assert "score" not in rendered
        assert "pwin" not in rendered
        assert "/100" not in rendered
        assert "bid/no-bid" not in rendered


def test_render_escapes_markdown_in_untrusted_raw_value() -> None:
    rendered = _render("[x](http://evil)")

    assert "](http://evil)" not in rendered
    assert "\\[x\\]\\(http://evil\\)" in rendered


def test_md_flattens_newlines_in_untrusted_values() -> None:
    rendered = _render("NONE\n# forged heading")

    assert "\n# forged heading" not in rendered
    assert "NONE # forged heading" in rendered
