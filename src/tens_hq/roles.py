"""Packet-page visibility and feature gating for ReconRadar.

The public app is always the two-page packet surface. Pilot mode narrows the
presentation by hiding guided-tour and planning controls; it does not grant or
remove page access. The local, single-user case ledger is opt-in because it is
not an identity or multi-tenant boundary.
"""

from __future__ import annotations

import os

PILOT_MODE_ENV = "TENS_HQ_PILOT_MODE"
CASE_LEDGER_ENV = "TENS_HQ_ENABLE_CASE_LEDGER"

ALL_PAGES = ("BD Feasibility", "Privacy & Governance")
PILOT_PAGES = ALL_PAGES


def pilot_mode_enabled() -> bool:
    """Return whether pilot presentation mode is enabled."""

    value = os.environ.get(PILOT_MODE_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def case_ledger_enabled() -> bool:
    """Return whether the local, single-user case ledger is enabled."""

    value = os.environ.get(CASE_LEDGER_ENV, "").strip().lower()
    return value in {"1", "true", "yes"}


def allowed_pages() -> tuple[str, ...]:
    """Return the complete public packet surface in display order."""

    return PILOT_PAGES if pilot_mode_enabled() else ALL_PAGES
