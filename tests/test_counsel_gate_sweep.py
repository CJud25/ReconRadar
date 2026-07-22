"""Branch-independent counsel-gate net: sweep the SOURCE TEXT of every
src/tens_hq module for C3/C4 vocabulary.

The render-level guards (test_r2a_map.py, test_packet_export.py,
test_demo_tour.py) check real composed surfaces but exercise one branch of
each section; the adversarial verify proved constants on unexercised
branches (the UNKNOWN gate copy, absence caveats, CANNOT_COMPUTE reasons)
escape them. This sweep is the wholesale net: counsel-gated vocabulary may
not appear ANYWHERE in a packet-side module's source -- string constant,
branch copy, comment, or docstring alike. Meta-discussion belongs in
ADR-020 / the counsel packet, which are docs, not shipped modules.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import counsel_gate_violations
import tens_hq

_SRC_ROOT = Path(tens_hq.__file__).resolve().parent
_MODULE_FILES = sorted(
    path for path in _SRC_ROOT.rglob("*.py") if "__pycache__" not in path.parts
)


def test_sweep_covers_the_whole_package() -> None:
    names = {path.name for path in _MODULE_FILES}
    # Spot-pin the load-bearing packet modules so a future layout change
    # cannot silently shrink the sweep to nothing.
    for required in (
        "opportunity_packet.py",
        "eligibility_gate.py",
        "capture_window.py",
        "incumbent_leads.py",
        "staffing_whatif.py",
        "pl_match.py",
        "pl_activity.py",
        "radar_handoff.py",
        "r2a_map.py",
        "packet_export.py",
        "bd_page.py",
        "demo_tour.py",
    ):
        assert required in names
    assert len(_MODULE_FILES) >= 20


@pytest.mark.parametrize(
    "module_path", _MODULE_FILES, ids=[p.stem for p in _MODULE_FILES]
)
def test_no_counsel_gated_vocabulary_in_module_source(module_path: Path) -> None:
    violations = counsel_gate_violations(module_path.read_text(encoding="utf-8"))
    assert violations == [], (
        f"{module_path.name} carries counsel-gated C3/C4 vocabulary "
        f"{violations}; that content is with counsel (ADR-020) and may not "
        "appear in any packet-side module, comments included."
    )
