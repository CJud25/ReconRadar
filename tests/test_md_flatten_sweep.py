"""Runtime and import-identity sweep for the shared Markdown helper."""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path
from types import ModuleType

import pytest

import tens_hq
from tens_hq import _markdown

_SRC_ROOT = Path(tens_hq.__file__).resolve().parent
_MARKDOWN_PATH = _SRC_ROOT / "_markdown.py"
_MODULE_PATHS = sorted(
    path
    for path in _SRC_ROOT.rglob("*.py")
    if "__pycache__" not in path.parts
)
_LOCAL_MD_DEFINITION = re.compile(r"\bdef _md\(")


def _uses_md(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_md"
        for node in ast.walk(tree)
    )


_MD_CONSUMER_PATHS = sorted(
    path for path in _MODULE_PATHS if path != _MARKDOWN_PATH and _uses_md(path)
)


def _import_module(path: Path) -> ModuleType:
    relative = path.relative_to(_SRC_ROOT).with_suffix("")
    dotted = ".".join(("tens_hq", *relative.parts))
    return importlib.import_module(dotted)


def test_md_flatten_sweep_covers_every_md_consumer() -> None:
    names = {path.name for path in _MD_CONSUMER_PATHS}
    for required in (
        "bd_page.py",
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
    assert len(_MD_CONSUMER_PATHS) >= 9


def test_no_local_md_definitions_outside_shared_module() -> None:
    local_definitions = [
        path
        for path in _MODULE_PATHS
        if path != _MARKDOWN_PATH
        and _LOCAL_MD_DEFINITION.search(path.read_text(encoding="utf-8"))
    ]
    assert local_definitions == []


@pytest.mark.parametrize(
    "module_path",
    _MD_CONSUMER_PATHS,
    ids=[path.stem for path in _MD_CONSUMER_PATHS],
)
def test_md_consumers_import_the_shared_function(module_path: Path) -> None:
    module = _import_module(module_path)
    assert module._md is _markdown._md


def test_md_flattens_line_boundaries_before_escaping() -> None:
    assert _markdown._md("alpha\nbeta\r\ngamma\u2028delta *[x]") == (
        "alpha beta gamma delta \\*\\[x\\]"
    )
    assert _markdown._md(None) == ""


def test_reported_preserves_default_and_export_empty_labels() -> None:
    assert _markdown._reported(None) == "Not reported"
    assert _markdown._reported(" \t ") == "Not reported"
    assert _markdown._reported(None, empty="Not supplied") == "Not supplied"
    assert _markdown._reported("alpha\n*[x]") == "alpha \\*\\[x\\]"
