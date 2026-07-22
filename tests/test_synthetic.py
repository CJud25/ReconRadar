from __future__ import annotations

from tens_hq.validation import validate_demo_data


def test_complete_dataset_passes_validation(demo_data):
    result = validate_demo_data(demo_data)
    assert result.ok, result.errors
    assert not result.warnings


def test_requested_demo_volumes_are_present(demo_data):
    assert len(demo_data.sites) == 12
    assert len(demo_data.counties) == 48
    assert len(demo_data.organizations) == 320
    assert len(demo_data.contacts) == 540
    assert len(demo_data.outreach) == 1800
    assert len(demo_data.applicants) == 1500
    assert len(demo_data.labor_hours) == 12 * 24
    assert len(demo_data.opportunities) == 60


def test_every_frame_is_explicitly_synthetic(demo_data):
    for name, frame in demo_data.frames().items():
        assert "synthetic_flag" in frame.columns, name
        assert frame["synthetic_flag"].all(), name


def test_safe_identity_contract(demo_data):
    assert demo_data.applicants["display_label"].str.contains("Synthetic").all()
    assert demo_data.contacts["contact_email"].str.endswith("@example.invalid").all()
    assert demo_data.organizations["website_url"].str.endswith(".example.invalid").all()


def test_status_stage_gate(demo_data):
    not_started = demo_data.applicants["start_date"].isna()
    assert (demo_data.applicants.loc[not_started, "eligibility_review_status"] == "Not Started").all()
    assert (demo_data.applicants.loc[not_started, "documentation_status"] == "Not Requested").all()
