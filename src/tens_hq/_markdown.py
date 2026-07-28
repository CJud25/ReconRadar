"""Shared single-line Markdown escaping for packet and UI renderers."""

from __future__ import annotations

_MD_ESCAPE = {ch: "\\" + ch for ch in "\\`*[]()<>"}


def _md(value: object) -> str:
    """Flatten line boundaries and escape the packet's Markdown metacharacters."""

    if value is None:
        return ""
    flat = " ".join(str(value).splitlines())
    return "".join(_MD_ESCAPE.get(ch, ch) for ch in flat)


def _reported(value: object, empty: str = "Not reported") -> str:
    """Render a supplied value safely, or return the caller's empty label."""

    if value is None or not str(value).strip():
        return empty
    return _md(value)
