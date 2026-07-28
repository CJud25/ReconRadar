"""Runtime sweep for every packet-side ``_md`` chokepoint."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import pytest

import tens_hq

_SRC_ROOT = Path(tens_hq.__file__).resolve().parent
_MD_MODULE_PATHS = sorted(
    path
    for path in _SRC_ROOT.rglob("*.py")
    if "__pycache__" not in path.parts
    and "def _md(value: object)" in path.read_text(encoding="utf-8")
)


def _import_module(path: Path) -> ModuleType:
    relative = path.relative_to(_SRC_ROOT).with_suffix("")
    dotted = ".".join(("tens_hq", *relative.parts))
    return importlib.import_module(dotted)


def test_md_flatten_sweep_covers_every_md_chokepoint() -> None:
    names = {path.name for path in _MD_MODULE_PATHS}
    for required in (
        "opportunity_packet.py",
        "eligibility_gate.py",
        "pl_match.py",
        "pl_activity.py",
        "incumbent_leads.py",
        "staffing_whatif.py",
        "packet_export.py",
        "radar_handoff.py",
    ):
        assert required in names
    assert len(_MD_MODULE_PATHS) >= 8


@pytest.mark.parametrize(
    "module_path", _MD_MODULE_PATHS, ids=[path.stem for path in _MD_MODULE_PATHS]
)
def test_md_flattens_line_boundaries_before_escaping(module_path: Path) -> None:
    module = _import_module(module_path)

    assert module._md("alpha\nbeta\r\ngamma\u2028delta *[x]") == (
        "alpha beta gamma delta \\*\\[x\\]"
    )
    assert module._md(None) == ""
