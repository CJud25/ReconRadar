from __future__ import annotations

from tens_hq.pages import PAGE_RENDERERS


def test_all_required_pages_are_registered():
    assert list(PAGE_RENDERERS) == [
        "BD Feasibility",
        "Privacy & Governance",
    ]
