"""Scheduled freshness honesty check for ReconRadar's dated facts.
Reads: the demo as-of date and owner-attested capture/source policy dates.
Turns red: strictly after any fact's 365-day review deadline.
Demo remediation: review/regenerate the demo and advance DATA_AS_OF_DATE.
Policy remediation: re-attest with the pilot NPA coordinator and bump effective_date.
Run: python scripts/check_freshness.py [--today YYYY-MM-DD].
Schedule note: GitHub may auto-disable cron after 60 inactive days; dispatch remains.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tens_hq.capture_window import DEFAULT_CAPTURE_WINDOW_POLICY  # noqa: E402
from tens_hq.case_store import (  # noqa: E402
    _DEFAULT_FRESHNESS_POLICY,
    SOURCE_FRESHNESS_POLICY,
)
from tens_hq.constants import DATA_AS_OF_DATE  # noqa: E402

MAX_FACT_AGE_DAYS = 365


@dataclass(frozen=True, slots=True)
class Fact:
    """One dated fact and the owner action required when it becomes stale."""

    name: str
    deadline: date
    remediation: str


def _deadline(effective_date: date) -> date:
    return effective_date + timedelta(days=MAX_FACT_AGE_DAYS)


def _policy_fact(name: str, effective_date: str) -> Fact:
    return Fact(
        name=name,
        deadline=_deadline(date.fromisoformat(effective_date)),
        remediation=(
            "Re-attest with the pilot NPA coordinator and bump effective_date."
        ),
    )


def fact_registry() -> tuple[Fact, ...]:
    """Return every annual-review fact watched by the scheduled lane."""

    facts = [
        Fact(
            name="DATA_AS_OF_DATE",
            deadline=_deadline(DATA_AS_OF_DATE),
            remediation=(
                "Review and regenerate the demo data, then advance DATA_AS_OF_DATE."
            ),
        ),
        _policy_fact(
            "DEFAULT_CAPTURE_WINDOW_POLICY",
            DEFAULT_CAPTURE_WINDOW_POLICY.effective_date,
        ),
        _policy_fact(
            "_DEFAULT_FRESHNESS_POLICY",
            _DEFAULT_FRESHNESS_POLICY.effective_date,
        ),
    ]
    facts.extend(
        _policy_fact(
            f"SOURCE_FRESHNESS_POLICY[{source_kind}]",
            policy.effective_date,
        )
        for source_kind, policy in sorted(SOURCE_FRESHNESS_POLICY.items())
    )
    return tuple(facts)


def stale_facts(today: date) -> list[str]:
    """Return formatted findings for facts whose deadline has passed."""

    facts = fact_registry()
    if not facts:
        return ["Fact registry is empty; no freshness evidence was checked."]
    return [
        (
            f"{fact.name} is stale after {fact.deadline.isoformat()}. "
            f"Remediation: {fact.remediation}"
        )
        for fact in facts
        if today > fact.deadline
    ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="Injected review date for deterministic rehearsal.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    today = args.today or date.today()
    findings = stale_facts(today)
    stale_names = {finding.split(" is stale", 1)[0] for finding in findings}

    for fact in fact_registry():
        status = "STALE" if fact.name in stale_names else "FRESH"
        print(f"{status}: {fact.name} (deadline {fact.deadline.isoformat()})")
    for finding in findings:
        print(f"ERROR: {finding}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
