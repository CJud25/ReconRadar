from __future__ import annotations

import pytest

from tens_hq.evidence import EvidenceValidationError, ensure_public_payload


# The two-app wall (N7) must be drawn at the right key: reject person-level PII
# while accepting the public organization contact fields a resource directory
# legitimately carries.  These regression tests pin both directions.


def test_person_pii_keys_are_still_rejected() -> None:
    person_pii = [
        "ssn",
        "social_security_number",
        "applicant_id",
        "candidate_id",
        "employee_id",
        "person_id",
        "contact_id",
        "diagnosis",
        "disability",
        "medical_record",
        "eligibility_document",
        "accommodation",
        "contact_name",
        "contact_email",
        "contact_phone",
        "personal_email",
        "home_address",
        # Bare, unprefixed contact keys are person PII too: a generic ``email``
        # or ``phone`` value may be a named individual's personal contact, so
        # the denylist rejects them.  The legitimate org-contact use case is
        # served by the ``org_``-prefixed keys instead.
        "phone",
        "mobile",
        "telephone",
        "email",
        "address",
        "street_address",
        "document",
        "attachment",
        "file_path",
    ]
    for key in person_pii:
        with pytest.raises(EvidenceValidationError):
            ensure_public_payload({key: "value"})

    # A forbidden field must not be smuggled through nesting either.
    with pytest.raises(EvidenceValidationError):
        ensure_public_payload({"organization": {"providers": [{"ssn": "123-45-6789"}]}})
    with pytest.raises(EvidenceValidationError):
        ensure_public_payload({"providers": [{"organization_name": "X", "email": "jane.personal@gmail.com"}]})
    # Case/spacing/hyphen normalization still catches person PII.
    with pytest.raises(EvidenceValidationError):
        ensure_public_payload({"Contact Name": "Jane Doe"})
    with pytest.raises(EvidenceValidationError):
        ensure_public_payload({"personal-email": "jane@example.com"})
    with pytest.raises(EvidenceValidationError):
        ensure_public_payload({"Street Address": "100 Main St"})


def test_public_org_contact_keys_are_accepted() -> None:
    # An organization web address is not personal PII, so bare ``url``/
    # ``website``/``public_url`` stay allowed; every other contact channel must
    # be attached through an explicit ``org_``-prefixed key.
    payload = {
        "organization_name": "Rocky Mountain Independent Living Center",
        "org_url": "https://example.org",
        "org_website": "https://example.org/home",
        "org_public_url": "https://example.org/directory",
        "org_phone": "555-0100",
        "org_email": "info@example.org",
        "org_address": "100 Main St, Denver, CO 80202",
        "url": "https://example.org/contact",
        "website": "https://example.org/services",
        "public_url": "https://example.org/public",
    }
    result = ensure_public_payload(payload)
    # Round-trips intact; nothing was rejected or dropped.
    assert result == payload
    # Nested public-org contact rows (an A4 resource directory) are accepted.
    nested = {"providers": [{"organization_name": "CARF Provider", "org_phone": "555-0200", "org_address": "5 Oak Ave"}]}
    assert ensure_public_payload(nested) == nested
