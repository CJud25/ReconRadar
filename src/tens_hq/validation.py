"""Synthetic-only and mathematical validation gates."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import PROHIBITED_COLUMN_TOKENS
from .synthetic import DemoData


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_demo_data(data: DemoData) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    expected_counts = {
        "counties": 48,
        "sites": 12,
        "organizations": 320,
        "contacts": 540,
        "outreach": 1800,
        "applicants": 1500,
        "labor_hours": 288,
        "opportunities": 60,
    }
    for name, expected in expected_counts.items():
        actual = len(getattr(data, name))
        if actual != expected:
            errors.append(f"{name}: expected {expected} rows, found {actual}")

    for name, frame in data.frames().items():
        prohibited = [
            column
            for column in frame.columns
            if any(token in column.lower() for token in PROHIBITED_COLUMN_TOKENS)
        ]
        if prohibited:
            errors.append(f"{name}: prohibited columns present: {', '.join(prohibited)}")
        if "synthetic_flag" not in frame.columns:
            errors.append(f"{name}: synthetic_flag is missing")
        elif not frame["synthetic_flag"].fillna(False).all():
            errors.append(f"{name}: one or more rows are not marked synthetic")

    id_contracts = {
        "counties": ("county_id", "SYN-CTY-"),
        "sites": ("site_id", "SYN-SITE-"),
        "organizations": ("organization_id", "SYN-ORG-"),
        "contacts": ("contact_id", "SYN-CON-"),
        "outreach": ("outreach_activity_id", "SYN-OUT-"),
        "applicants": ("applicant_id", "SYN-APP-"),
        "labor_hours": ("labor_hours_monthly_id", "SYN-LHM-"),
        "opportunities": ("opportunity_id", "SYN-OPP-"),
    }
    for name, (column, prefix) in id_contracts.items():
        frame = getattr(data, name)
        if not frame[column].astype(str).str.startswith(prefix).all():
            errors.append(f"{name}: ID prefix contract failed")
        if frame[column].duplicated().any():
            errors.append(f"{name}: duplicate IDs detected")

    if not data.contacts["contact_email"].str.endswith("@example.invalid").all():
        errors.append("contacts: non-reserved email domain detected")
    if not data.organizations["website_url"].str.endswith(".example.invalid").all():
        errors.append("organizations: non-reserved website domain detected")
    if (data.labor_hours["mock_qdl_hours"] > data.labor_hours["total_direct_labor_hours"]).any():
        errors.append("labor_hours: QDL hours exceed total direct labor hours")
    if (data.labor_hours[["mock_qdl_hours", "total_direct_labor_hours"]].min().min() < 0):
        errors.append("labor_hours: negative hours detected")
    recomputed = data.labor_hours["mock_qdl_hours"] / data.labor_hours["total_direct_labor_hours"] * 100.0
    if ((recomputed - data.labor_hours["current_ratio_pct"]).abs() > 0.02).any():
        errors.append("labor_hours: stored ratios do not reproduce from numerator and denominator")

    if not data.applicants["display_label"].str.contains("Synthetic", case=False).all():
        errors.append("applicants: synthetic display label missing")
    pre_start = data.applicants["start_date"].isna()
    if not (data.applicants.loc[pre_start, "eligibility_review_status"] == "Not Started").all():
        errors.append("applicants: eligibility status used before the synthetic start-stage gate")
    if not (data.applicants.loc[pre_start, "documentation_status"] == "Not Requested").all():
        errors.append("applicants: documentation status used before the synthetic start-stage gate")

    missing_source = ~data.applicants["source_organization_id"].isin(data.organizations["organization_id"])
    if missing_source.any():
        errors.append("applicants: unknown source organization reference")
    missing_site = ~data.applicants["target_site_id"].isin(data.sites["site_id"])
    if missing_site.any():
        errors.append("applicants: unknown target site reference")

    if len(data.stage_history) < 4000:
        warnings.append("stage_history: fewer than 4,000 events; dashboard story may be thin")
    return ValidationResult(tuple(errors), tuple(warnings))
