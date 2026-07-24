"""EDGE gate-decision-log boundary tests (ADR-027).

EDGE ("Evidence-Driven Gate Evaluation") is docs + a template + a worked
example corpus only -- there is no ``src/tens_hq`` EDGE module in this
slice. These tests guard the two claims that make EDGE trustworthy:

1. EDGE's arrival leaks no score/ranking-claim back into the fully
   populated Opportunity Packet (N1 still holds, extended from the
   existing minimal-packet no-score test to the everything-attached case).
2. EDGE is genuinely external to the packet -- no packet-side module in
   ``src/tens_hq`` references the decision-log vocabulary (no contamination,
   branch-independent, mirroring ``test_counsel_gate_sweep.py``).
3. The committed worked example corpus (``docs/edge/gate_decisions.example.jsonl``)
   is schema-valid against ``edge/v1`` and its decision-time record carries
   no outcome fields (the immutability boundary).

Both file-reading tests root off the installed package
(``Path(tens_hq.__file__).resolve()``), exactly as ``test_counsel_gate_sweep.py``
does, so they are CWD-independent and pass under CI. This holds because
``pyproject.toml`` pins ``pythonpath = ["src"]``, so ``tens_hq`` always
resolves under ``src/tens_hq``.
"""

from __future__ import annotations

import json
from pathlib import Path

from test_packet_export import _packet_body

import tens_hq

# --- Test 1 fixtures/constants --------------------------------------------

# N1: the same four tokens the existing minimal-packet guard uses
# (tests/test_opportunity_packet.py:134-137, test_packet_contains_no_score).
# Deliberately NOT "ranking": PACKET_FRAMING (opportunity_packet.py:97-100)
# renders the honest negation "...no ranking, and no pursue-or-decline
# recommendation" into every packet body (opportunity_packet.py:341) and
# export header (packet_export.py:696), so "ranking" is always present as
# an honest negation and would false-fail on every packet -- exactly why
# the existing no-score test omits it too.
_NO_SCORE_TOKENS = ("score", "pwin", "/100", "bid/no-bid")


def test_packet_renders_no_score_with_every_section_populated() -> None:
    """N1 holds even with every packet section populated (EDGE leaked nothing back)."""

    packet = _packet_body(everything=True).lower()
    for token in _NO_SCORE_TOKENS:
        assert token not in packet, (
            f"forbidden token {token!r} found in a fully-populated packet body -- "
            "EDGE must never leak a score/ranking/bid-no-bid claim back into the packet"
        )


# --- Test 2: no packet-side module references EDGE -------------------------

_SRC_ROOT = Path(tens_hq.__file__).resolve().parent
_MODULE_FILES = sorted(
    path for path in _SRC_ROOT.rglob("*.py") if "__pycache__" not in path.parts
)

# EDGE decision-log vocabulary. There is no src/tens_hq EDGE module this
# slice -- finding any of these tokens in packet-side source would mean
# someone wired a decision-log reader/writer into the packet code.
_EDGE_TOKENS = (
    "gate_decisions",
    "gate-decision-log",
    "edge/v1",
    "p_win",
    "calibration",
    "reliability curve",
    "brier",
)


def test_packet_side_modules_do_not_reference_edge() -> None:
    # Spot-pin the load-bearing packet modules so a future layout change
    # cannot silently empty the sweep (mirrors test_counsel_gate_sweep.py's
    # test_sweep_covers_the_whole_package).
    names = {path.name for path in _MODULE_FILES}
    assert "opportunity_packet.py" in names
    assert "packet_export.py" in names
    assert len(_MODULE_FILES) >= 20

    violations: list[str] = []
    for module_path in _MODULE_FILES:
        text = module_path.read_text(encoding="utf-8").lower()
        for token in _EDGE_TOKENS:
            if token in text:
                violations.append(f"{module_path.name}: {token!r}")
    assert violations == [], (
        "EDGE decision-log vocabulary found in packet-side source -- EDGE must "
        f"stay external to the packet (no contamination): {violations}"
    )


# --- Test 3: the worked example corpus is schema-valid ---------------------

# Repo root, derived from the package location, never guessed from CWD
# (Path(tens_hq.__file__).resolve() -> src/tens_hq/__init__.py; parents[2]
# walks package file -> src/tens_hq -> src -> repo root).
_REPO_ROOT = Path(tens_hq.__file__).resolve().parents[2]
_EXAMPLE_CORPUS_PATH = _REPO_ROOT / "docs" / "edge" / "gate_decisions.example.jsonl"

# Controlled vocabularies, defined here (not re-imported from the docs) so
# the schema and the template can't silently drift out from under this test.
_PACKET_SECTIONS = frozenset(
    {
        "origin_radar_handoff",
        "eligibility_gate",
        "contract_facts",
        "capture_window",
        "incumbent_teaming_leads",
        "staffing_whatif",
        "geography_acs",
        "pl_crossref_r2b",
        "pl_activity_fedreg",
        "r2a_map",
    }
)
_NON_PACKET_SECTIONS = frozenset(
    {
        "customer_relationship",
        "past_performance_fit",
        "bnp_capacity",
        "competitive_landscape",
    }
)
_ALL_FACTOR_SECTIONS = _PACKET_SECTIONS | _NON_PACKET_SECTIONS

_CALL_VALUES = frozenset({"pursue", "pass", "watch"})
_BASIS_VALUES = frozenset({"gut", "some_evidence", "strong_evidence"})
_OUTCOME_VALUES = frozenset(
    {
        "won",
        "lost",
        "cancelled_no_award",
        "no_bid_confirmed",
        "not_pursued",
        "still_open",
        "unknown",
    }
)

_REQUIRED_DECISION_FIELDS = (
    "record_type",
    "schema_version",
    "decision_id",
    "logged_at",
    "piid",
    "packet_export_filename",
    "call",
    "confidence",
    "factors",
    "rationale",
)

_REQUIRED_OUTCOME_FIELDS = (
    "record_type",
    "schema_version",
    "outcome_id",
    "decision_id",
    "logged_at",
    "outcome",
    "outcome_basis",
)

# The immutability boundary (§2.1/§2.3 of GATE_DECISION_LOG.md): a
# decision-time record must not carry any outcome-record field.
_OUTCOME_ONLY_FIELDS = ("outcome", "outcome_date", "outcome_basis")


def _load_example_lines() -> list[dict]:
    text = _EXAMPLE_CORPUS_PATH.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_example_corpus_is_schema_valid() -> None:
    records = _load_example_lines()
    assert records, "the worked example corpus must not be empty"

    decision_ids = {
        record["decision_id"] for record in records if record.get("record_type") == "decision"
    }

    for record in records:
        assert record["record_type"] in {"decision", "outcome"}
        assert record["schema_version"] == "edge/v1"

        if record["record_type"] == "decision":
            for field in _REQUIRED_DECISION_FIELDS:
                assert field in record, f"decision record missing required field {field!r}"

            assert record["call"] in _CALL_VALUES

            confidence = record["confidence"]
            p_win = confidence["p_win"]
            assert isinstance(p_win, (int, float))
            assert 0.0 <= p_win <= 1.0
            assert confidence["basis"] in _BASIS_VALUES

            factors = record["factors"]
            assert isinstance(factors, list)
            assert len(factors) >= 1
            for factor in factors:
                assert factor["section"] in _ALL_FACTOR_SECTIONS

            # supersedes_decision_id is optional; tolerate absence, a
            # string, or an explicit null.
            if "supersedes_decision_id" in record:
                assert record["supersedes_decision_id"] is None or isinstance(
                    record["supersedes_decision_id"], str
                )

            # The immutability boundary: a decision-time record carries no
            # outcome fields.
            for field in _OUTCOME_ONLY_FIELDS:
                assert field not in record, (
                    f"decision record {record.get('decision_id')!r} carries "
                    f"outcome-only field {field!r} -- decision records must "
                    "never be edited after the fact"
                )

        else:  # outcome
            for field in _REQUIRED_OUTCOME_FIELDS:
                assert field in record, f"outcome record missing required field {field!r}"
            assert record["outcome"] in _OUTCOME_VALUES
            assert record["decision_id"] in decision_ids, (
                f"outcome record {record.get('outcome_id')!r} references "
                f"decision_id {record.get('decision_id')!r}, which has no "
                "matching decision record in the corpus"
            )
