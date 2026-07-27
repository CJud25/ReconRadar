"""Deterministic tests for the scheduled dated-fact checker."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_freshness  # noqa: E402


def test_registry_covers_the_expected_facts() -> None:
    registry = {fact.name: fact for fact in check_freshness.fact_registry()}

    assert set(registry) == {
        "DATA_AS_OF_DATE",
        "DEFAULT_CAPTURE_WINDOW_POLICY",
        "_DEFAULT_FRESHNESS_POLICY",
        "SOURCE_FRESHNESS_POLICY[ABILITYONE_SERVICES]",
        "SOURCE_FRESHNESS_POLICY[NIB_NPA]",
        "SOURCE_FRESHNESS_POLICY[SOURCEAMERICA_NPA]",
    }
    assert registry["DATA_AS_OF_DATE"].deadline == date(2027, 6, 30)
    assert registry["DEFAULT_CAPTURE_WINDOW_POLICY"].deadline == date(2027, 7, 21)
    assert registry["_DEFAULT_FRESHNESS_POLICY"].deadline == date(2027, 7, 18)
    assert all(
        registry[name].deadline == date(2027, 7, 18)
        for name in registry
        if name.startswith("SOURCE_FRESHNESS_POLICY[")
    )


def test_all_fresh_on_2026_07_27() -> None:
    assert check_freshness.stale_facts(date(2026, 7, 27)) == []


def test_data_as_of_stale_after_365_days() -> None:
    findings = check_freshness.stale_facts(date(2027, 7, 1))

    assert len(findings) == 1
    assert findings[0].startswith("DATA_AS_OF_DATE is stale")
    assert "2027-06-30" in findings[0]


def test_attestation_stale_after_365_days() -> None:
    findings = check_freshness.stale_facts(date(2027, 7, 19))

    assert any("_DEFAULT_FRESHNESS_POLICY is stale" in item for item in findings)
    assert any("SOURCE_FRESHNESS_POLICY[NIB_NPA] is stale" in item for item in findings)
    assert not any("DEFAULT_CAPTURE_WINDOW_POLICY is stale" in item for item in findings)


def test_deadline_day_is_fresh() -> None:
    findings = check_freshness.stale_facts(date(2027, 6, 30))

    assert not any("DATA_AS_OF_DATE is stale" in item for item in findings)
