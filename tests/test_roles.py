from __future__ import annotations

from tens_hq import roles


PACKET_PAGES = ("BD Feasibility", "Privacy & Governance")


def test_public_app_exposes_exactly_the_packet_pages():
    assert roles.ALL_PAGES == PACKET_PAGES
    assert roles.PILOT_PAGES == PACKET_PAGES
    assert roles.allowed_pages() == PACKET_PAGES


def test_role_concept_is_not_part_of_the_public_app():
    for removed_name in ("ROLES", "ROLE_PAGES", "DEFAULT_ROLE", "current_role"):
        assert not hasattr(roles, removed_name)


def test_pilot_mode_off_by_default(monkeypatch):
    monkeypatch.delenv("TENS_HQ_PILOT_MODE", raising=False)
    assert roles.pilot_mode_enabled() is False
    assert roles.allowed_pages() == PACKET_PAGES


def test_pilot_mode_truthy_values(monkeypatch):
    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("TENS_HQ_PILOT_MODE", value)
        assert roles.pilot_mode_enabled() is True
        assert roles.allowed_pages() == PACKET_PAGES
    for value in ("", "0", "false", "off", "no"):
        monkeypatch.setenv("TENS_HQ_PILOT_MODE", value)
        assert roles.pilot_mode_enabled() is False
        assert roles.allowed_pages() == PACKET_PAGES
