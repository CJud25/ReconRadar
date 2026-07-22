"""Packet-page visibility and pilot-presentation mode for ReconRadar.

The public app is always the two-page packet surface. Pilot mode narrows the
presentation by hiding guided-tour and planning controls; it does not grant or
remove page access.
"""

from __future__ import annotations

import os


PILOT_MODE_ENV = "TENS_HQ_PILOT_MODE"

ALL_PAGES = ("BD Feasibility", "Privacy & Governance")
PILOT_PAGES = ALL_PAGES


def pilot_mode_enabled() -> bool:
    """Return whether pilot presentation mode is enabled."""

    value = os.environ.get(PILOT_MODE_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def allowed_pages() -> tuple[str, ...]:
    """Return the complete public packet surface in display order."""

    return PILOT_PAGES if pilot_mode_enabled() else ALL_PAGES
