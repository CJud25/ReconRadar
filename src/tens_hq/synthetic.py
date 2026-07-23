"""Deterministic, privacy-safe synthetic data for the ReconRadar demonstration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .constants import (
    COUNTY_NAMES,
    DATA_AS_OF_DATE,
    DEFAULT_SEED,
    JOB_FAMILIES,
    ORGANIZATION_TYPES,
    RELATIONSHIP_STATUSES,
    SITE_PROFILES,
)


@dataclass(frozen=True)
class DemoData:
    counties: pd.DataFrame
    sites: pd.DataFrame
    organizations: pd.DataFrame
    coverage: pd.DataFrame
    org_job_families: pd.DataFrame
    contacts: pd.DataFrame
    outreach: pd.DataFrame
    applicants: pd.DataFrame
    stage_history: pd.DataFrame
    labor_hours: pd.DataFrame
    opportunities: pd.DataFrame

    def frames(self) -> dict[str, pd.DataFrame]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


def _date_minus(days: int) -> pd.Timestamp:
    return pd.Timestamp(DATA_AS_OF_DATE - timedelta(days=int(days)))


def _clamp_probability(value: float) -> float:
    return float(np.clip(value, 0.02, 0.98))


def _job_family_for_contract(contract_type: str) -> str:
    lookup = {
        "Custodial Services": "CUSTODIAL",
        "Facilities Support": "FACILITIES",
        "Food Services": "FOOD",
        "Contact Center": "CONTACT",
        "Administrative Support": "ADMIN",
        "IT Service Desk": "IT",
    }
    return lookup[contract_type]


def generate_demo_data(seed: int = DEFAULT_SEED) -> DemoData:
    """Generate the full synthetic demo with stable row counts and linked stories."""

    rng = np.random.default_rng(seed)
    as_of = pd.Timestamp(DATA_AS_OF_DATE)

    county_rows: list[dict] = []
    county_lookup: dict[tuple[str, str], str] = {}
    county_counter = 1
    for state, names in COUNTY_NAMES.items():
        for name in names:
            county_id = f"SYN-CTY-{state}-{county_counter:03d}"
            county_name = f"{name} County"
            county_lookup[(state, county_name)] = county_id
            county_rows.append(
                {
                    "county_id": county_id,
                    "county_name": county_name,
                    "state_code": state,
                    "region_name": "East" if state in {"VA", "MD", "NC", "PA"} else "Central/South",
                    "urbanicity": rng.choice(["Urban", "Mixed", "Rural"], p=[0.28, 0.47, 0.25]),
                    "fictional_geo_flag": True,
                    "synthetic_flag": True,
                }
            )
            county_counter += 1
    counties = pd.DataFrame(county_rows)

    site_rows: list[dict] = []
    for idx, (name, county_root, state, contract_type, staff, openings, ratio, trend, attrition) in enumerate(
        SITE_PROFILES, start=1
    ):
        county_name = county_root if county_root.endswith(" County") else f"{county_root} County"
        site_rows.append(
            {
                "site_id": f"SYN-SITE-{idx:03d}",
                "site_name": name,
                "county_id": county_lookup[(state, county_name)],
                "county_name": county_name,
                "state_code": state,
                "contract_type": contract_type,
                "job_family_code": _job_family_for_contract(contract_type),
                "current_mock_staffing": staff,
                "open_roles_count": openings,
                "default_weekly_dlh_per_hire": JOB_FAMILIES[_job_family_for_contract(contract_type)][1],
                "site_planning_target_pct": 75.0,
                "planning_buffer_pct": 3.0,
                "base_ratio": ratio,
                "monthly_ratio_trend": trend,
                "expected_attrition_fte": attrition,
                "data_as_of_date": as_of,
                "synthetic_flag": True,
            }
        )
    sites = pd.DataFrame(site_rows)

    type_names = list(ORGANIZATION_TYPES)
    type_probabilities = np.array([ORGANIZATION_TYPES[name]["weight"] for name in type_names], dtype=float)
    type_probabilities /= type_probabilities.sum()
    relationship_probabilities = np.array([0.04, 0.18, 0.18, 0.18, 0.20, 0.08, 0.10, 0.04])
    suffix_by_type = {
        "Vocational Rehabilitation": "Vocational Pathways",
        "Workforce Board": "Workforce Collaborative",
        "Supported Employment Provider": "Supported Employment Network",
        "Center for Independent Living": "Independent Living Center",
        "School Transition Program": "Transition Partnership",
        "Veteran-Serving Organization": "Veterans Career Bridge",
        "Community College": "Community Skills College",
        "Community Rehabilitation Provider": "Community Rehabilitation Services",
        "Local Workforce Nonprofit": "Opportunity Network",
    }

    organization_rows: list[dict] = []
    coverage_rows: list[dict] = []
    org_job_rows: list[dict] = []
    for idx in range(1, 321):
        org_type = str(rng.choice(type_names, p=type_probabilities))
        home = counties.iloc[int(rng.integers(0, len(counties)))]
        relationship = str(rng.choice(RELATIONSHIP_STATUSES, p=relationship_probabilities))
        if relationship in {"Unknown", "Cold"}:
            last_contact = pd.NaT if rng.random() < 0.65 else _date_minus(int(rng.integers(45, 300)))
        else:
            last_contact = _date_minus(int(rng.integers(2, 240)))
        if relationship == "Do Not Contact":
            next_follow_up = pd.NaT
        elif pd.isna(last_contact):
            next_follow_up = as_of + timedelta(days=int(rng.integers(1, 35)))
        else:
            next_follow_up = last_contact + timedelta(days=int(rng.integers(14, 100)))
        county_root = str(home["county_name"]).replace(" County", "")
        org_id = f"SYN-ORG-{idx:04d}"
        organization_rows.append(
            {
                "organization_id": org_id,
                "organization_name": f"{county_root} {suffix_by_type[org_type]} {idx:03d}",
                "organization_type": org_type,
                "home_county_id": home["county_id"],
                "county_name": home["county_name"],
                "state_code": home["state_code"],
                "website_url": f"https://org{idx:04d}.example.invalid",
                "main_phone": f"555-010-{idx % 10000:04d}",
                "relationship_status": relationship,
                "last_contact_date": last_contact,
                "next_follow_up_date": next_follow_up,
                "relationship_notes": "Synthetic business relationship note; no person or medical information.",
                "source_capacity_factor": 8.0
                if idx % 53 == 0
                else 4.0
                if idx % 17 == 0
                else round(float(rng.uniform(0.55, 1.45)), 3),
                "active_flag": relationship != "Do Not Contact",
                "synthetic_flag": True,
            }
        )

        same_state = counties[counties["state_code"] == home["state_code"]]
        extra_count = int(rng.integers(0, 3))
        candidate_ids = [value for value in same_state["county_id"].tolist() if value != home["county_id"]]
        covered_ids = [home["county_id"]]
        if extra_count and candidate_ids:
            covered_ids.extend(rng.choice(candidate_ids, size=min(extra_count, len(candidate_ids)), replace=False).tolist())
        for coverage_idx, county_id in enumerate(covered_ids):
            coverage_rows.append(
                {
                    "organization_id": org_id,
                    "county_id": county_id,
                    "coverage_strength": "Primary" if coverage_idx == 0 else "Secondary",
                    "verified_status": "Synthetic Confirmed",
                    "verified_as_of_date": as_of - timedelta(days=int(rng.integers(0, 120))),
                    "synthetic_flag": True,
                }
            )

        capability_count = int(rng.integers(1, 4))
        capabilities = rng.choice(list(JOB_FAMILIES), size=capability_count, replace=False)
        for job_code in capabilities:
            org_job_rows.append(
                {
                    "organization_id": org_id,
                    "job_family_code": str(job_code),
                    "capability_level": rng.choice(["Potential", "Claimed", "Demonstrated"], p=[0.25, 0.35, 0.40]),
                    "evidence_source": "Synthetic outcomes",
                    "last_observed_date": _date_minus(int(rng.integers(0, 300))),
                    "synthetic_flag": True,
                }
            )
    organizations = pd.DataFrame(organization_rows)
    coverage = pd.DataFrame(coverage_rows)
    org_job_families = pd.DataFrame(org_job_rows)

    contact_rows: list[dict] = []
    contact_org_ids = organizations["organization_id"].tolist() + rng.choice(
        organizations["organization_id"], size=220, replace=True
    ).tolist()
    for idx, organization_id in enumerate(contact_org_ids, start=1):
        contact_rows.append(
            {
                "contact_id": f"SYN-CON-{idx:04d}",
                "organization_id": organization_id,
                "contact_name": f"Partner Contact {idx:04d} (Synthetic)",
                "contact_title": rng.choice(
                    ["Employer Partnerships Manager", "Program Manager", "Career Services Lead", "Outreach Coordinator"]
                ),
                "contact_email": f"contact{idx:04d}@example.invalid",
                "contact_phone": f"555-011-{idx % 10000:04d}",
                "preferred_channel": rng.choice(["Email", "Phone", "Either"], p=[0.58, 0.17, 0.25]),
                "contact_status": "Active",
                "is_primary_contact": idx <= 320,
                "last_verified_date": _date_minus(int(rng.integers(0, 240))),
                "business_contact_basis": "Synthetic",
                "synthetic_flag": True,
            }
        )
    contacts = pd.DataFrame(contact_rows)

    relationship_factor = {
        "Unknown": 0.30,
        "Cold": 0.45,
        "Contacted": 0.70,
        "Warm": 1.10,
        "Active Partner": 1.65,
        "Strategic Partner": 1.85,
        "Dormant": 0.40,
        "Do Not Contact": 0.01,
    }
    org_weights = []
    for row in organizations.itertuples(index=False):
        profile = ORGANIZATION_TYPES[row.organization_type]
        org_weights.append(
            profile["volume"] * relationship_factor[row.relationship_status] * row.source_capacity_factor
        )
    org_weights = np.asarray(org_weights, dtype=float)
    org_weights /= org_weights.sum()

    outreach_rows: list[dict] = []
    contact_by_org = contacts.groupby("organization_id")["contact_id"].apply(list).to_dict()
    for idx in range(1, 1801):
        org_position = int(rng.choice(np.arange(len(organizations)), p=org_weights))
        org = organizations.iloc[org_position]
        activity_date = _date_minus(int(rng.integers(0, 550)))
        activity_type = rng.choice(["Cold Email", "Warm Follow-Up", "Call", "Meeting", "Role Briefing"])
        outcome = rng.choice(
            ["No Response", "Meeting Requested", "Information Shared", "Referral Process Confirmed", "Not Interested"],
            p=[0.31, 0.18, 0.24, 0.21, 0.06],
        )
        status = "Closed" if outcome in {"Referral Process Confirmed", "Not Interested"} else "Response Pending"
        site = sites.iloc[int(rng.integers(0, len(sites)))]
        outreach_rows.append(
            {
                "outreach_activity_id": f"SYN-OUT-{idx:06d}",
                "organization_id": org["organization_id"],
                "contact_id": rng.choice(contact_by_org[org["organization_id"]]),
                "site_id": site["site_id"],
                "outreach_type": activity_type,
                "purpose_code": rng.choice(["Pipeline Development", "Relationship Maintenance", "Role Briefing"]),
                "activity_date": activity_date,
                "owner": rng.choice(["Regional Recruiting", "Site Recruiting", "BD Outreach"]),
                "status": status,
                "outcome_code": outcome,
                "next_follow_up_date": activity_date + timedelta(days=int(rng.integers(14, 75)))
                if status == "Response Pending"
                else pd.NaT,
                "generated_message_used": bool(rng.random() < 0.38),
                "notes": "Synthetic outreach outcome; no applicant information.",
                "synthetic_flag": True,
            }
        )
    outreach = pd.DataFrame(outreach_rows)

    sites_by_county = sites.groupby("county_id")["site_id"].apply(list).to_dict()
    organization_records = organizations.to_dict("records")
    site_record_by_id = {record["site_id"]: record for record in sites.to_dict("records")}
    applicant_rows: list[dict] = []
    stage_rows: list[dict] = []
    for idx in range(1, 1501):
        org_position = int(rng.choice(np.arange(len(organizations)), p=org_weights))
        org = organization_records[org_position]
        profile = ORGANIZATION_TYPES[org["organization_type"]]
        random_effect = float(rng.normal(0, 0.045))
        referral_date = _date_minus(int(rng.integers(0, 541)))
        elapsed = int((as_of - referral_date).days)
        local_sites = sites_by_county.get(org["home_county_id"], [])
        target_site_id = str(rng.choice(local_sites)) if local_sites and rng.random() < 0.75 else str(rng.choice(sites["site_id"]))
        site = site_record_by_id[target_site_id]
        job_family_code = site["job_family_code"] if rng.random() < 0.82 else str(rng.choice(list(JOB_FAMILIES)))

        applied = elapsed >= 3 and rng.random() < _clamp_probability(profile["apply"] + random_effect)
        interviewed = applied and elapsed >= 12 and rng.random() < _clamp_probability(profile["interview"] + random_effect)
        hired = interviewed and elapsed >= 25 and rng.random() < _clamp_probability(profile["hire"] + random_effect)

        application_date = referral_date + timedelta(days=int(rng.integers(1, 8))) if applied else pd.NaT
        interview_date = application_date + timedelta(days=int(rng.integers(5, 18))) if interviewed else pd.NaT
        offer_date = interview_date + timedelta(days=int(rng.integers(2, 10))) if hired else pd.NaT
        start_delay = int(max(7, rng.normal(profile["days_clear"] + 14, 7)))
        start_date = offer_date + timedelta(days=start_delay) if hired else pd.NaT
        started = hired and pd.notna(start_date) and start_date <= as_of

        eligibility = "Not Started"
        documentation = "Not Requested"
        qdl_status = "Pending"
        days_to_clear = np.nan
        separation_date = pd.NaT
        retention = "Not Started"
        offer_status = "None"
        hire_status = "Not Hired"

        if not applied:
            current_stage = "Withdrawn" if elapsed > 45 and rng.random() < 0.25 else "Referred"
            stage_date = referral_date
        elif not interviewed:
            current_stage = "Not Selected" if elapsed > 60 and rng.random() < 0.46 else rng.choice(["Applied", "Screened"])
            stage_date = application_date
        elif not hired:
            current_stage = "Not Selected" if elapsed > 75 and rng.random() < 0.58 else rng.choice(
                ["Interview Scheduled", "Interviewed", "Offer Pending"], p=[0.20, 0.65, 0.15]
            )
            stage_date = interview_date
        elif not started:
            current_stage = "Offered"
            stage_date = offer_date
            offer_status = "Accepted"
        else:
            offer_status = "Accepted"
            hire_status = "Hired"
            days_since_start = int((as_of - start_date).days)
            documentation = "Complete" if rng.random() < profile["docs"] else rng.choice(["Partial", "Needs Review"])
            cleared = days_since_start >= 3 and rng.random() < _clamp_probability(profile["clear"] + random_effect)
            if cleared:
                days_to_clear = int(max(2, rng.normal(profile["days_clear"], 5)))
                eligibility = "Cleared"
                documentation = "Cleared" if documentation == "Complete" else documentation
                qdl_status = "Mock Countable"
                current_stage = "Eligibility Cleared"
                stage_date = min(as_of, start_date + timedelta(days=int(days_to_clear)))
            else:
                eligibility = rng.choice(["Pending", "Needs Follow-Up", "Not Cleared"], p=[0.54, 0.34, 0.12])
                qdl_status = "Mock Not Countable" if eligibility == "Not Cleared" else "Pending"
                current_stage = "Eligibility Review Pending"
                stage_date = start_date + timedelta(days=2)

            if days_since_start >= 90:
                retained = rng.random() < _clamp_probability(profile["retain90"] + random_effect)
                if retained:
                    retention = "Active-90+"
                else:
                    separation_date = start_date + timedelta(days=int(rng.integers(31, min(days_since_start, 180) + 1)))
                    retention = "Separated"
                    current_stage = "Separated"
                    stage_date = separation_date
                    hire_status = "Separated"
            elif days_since_start >= 30:
                retention = "Active-30+"
            else:
                retention = "Active-Under-30"

        applicant_id = f"SYN-APP-{idx:06d}"
        applicant_rows.append(
            {
                "applicant_id": applicant_id,
                "display_label": f"Candidate {idx:04d} (Synthetic)",
                "source_organization_id": org["organization_id"],
                "target_site_id": target_site_id,
                "job_family_code": job_family_code,
                "referral_date": referral_date,
                "application_date": application_date,
                "current_stage": current_stage,
                "stage_date": stage_date,
                "offer_status": offer_status,
                "hire_status": hire_status,
                "start_date": start_date if started else pd.NaT,
                "eligibility_review_status": eligibility,
                "documentation_status": documentation,
                "qdl_count_status": qdl_status,
                "expected_weekly_dlh": float(max(18, rng.normal(JOB_FAMILIES[job_family_code][1], 3.5))),
                "retention_status": retention,
                "separation_date": separation_date,
                "days_to_clear": days_to_clear,
                "synthetic_flag": True,
            }
        )

        history_events = [("Referred", referral_date)]
        if applied:
            history_events.append(("Applied", application_date))
        if interviewed:
            history_events.extend([("Interviewed", interview_date)])
        if hired:
            history_events.append(("Offered", offer_date))
        if started:
            history_events.append(("Hired", start_date))
        if eligibility == "Cleared":
            history_events.append(("Eligibility Cleared", min(as_of, start_date + timedelta(days=int(days_to_clear)))))
        if pd.notna(separation_date):
            history_events.append(("Separated", separation_date))
        for event_index, (stage, event_date) in enumerate(history_events, start=1):
            stage_rows.append(
                {
                    "stage_history_id": f"SYN-STG-{idx:06d}-{event_index:02d}",
                    "applicant_id": applicant_id,
                    "to_stage": stage,
                    "effective_at": event_date,
                    "reason_code": "Synthetic Stage Progression",
                    "synthetic_flag": True,
                }
            )
    applicants = pd.DataFrame(applicant_rows)
    stage_history = pd.DataFrame(stage_rows)

    labor_rows: list[dict] = []
    latest_month = as_of.replace(day=1)
    for site in sites.itertuples(index=False):
        for month_index in range(24):
            month_start = latest_month - pd.DateOffset(months=23 - month_index)
            total_hours = float(
                max(
                    100,
                    site.current_mock_staffing
                    * site.default_weekly_dlh_per_hire
                    * 4.33
                    * (1 + 0.025 * np.sin(month_index / 2.6))
                    * rng.normal(1.0, 0.018),
                )
            )
            ratio = float(
                np.clip(
                    site.base_ratio + site.monthly_ratio_trend * (month_index - 23) + rng.normal(0, 0.004),
                    0.58,
                    0.88,
                )
            )
            if month_index == 23:
                ratio = float(site.base_ratio)
            qdl_hours = total_hours * ratio
            labor_rows.append(
                {
                    "labor_hours_monthly_id": f"SYN-LHM-{site.site_id[-3:]}-{month_start:%Y%m}",
                    "site_id": site.site_id,
                    "month_start": month_start,
                    "total_direct_labor_hours": round(total_hours, 1),
                    "mock_qdl_hours": round(qdl_hours, 1),
                    "mock_non_qdl_hours": round(total_hours - qdl_hours, 1),
                    "current_ratio_pct": round(ratio * 100, 2),
                    "open_positions": site.open_roles_count,
                    "expected_attrition_fte": site.expected_attrition_fte,
                    "data_status": "Synthetic Complete",
                    "source_as_of_at": as_of,
                    "synthetic_flag": True,
                }
            )
    labor_hours = pd.DataFrame(labor_rows)

    opportunity_rows: list[dict] = []
    contract_types = [value[1][0] for value in JOB_FAMILIES.items()]
    for idx in range(1, 61):
        county = counties.iloc[int(rng.integers(0, len(counties)))]
        contract_type = str(rng.choice(contract_types))
        opportunity_rows.append(
            {
                "opportunity_id": f"SYN-OPP-{idx:04d}",
                "opportunity_name": f"{county['county_name']} {contract_type} Opportunity {idx:02d}",
                "county_id": county["county_id"],
                "county_name": county["county_name"],
                "state_code": county["state_code"],
                "contract_type": contract_type,
                "estimated_headcount": int(rng.integers(18, 121)),
                "estimated_start_date": as_of + timedelta(days=int(rng.integers(90, 540))),
                "existing_presence_flag": bool(rng.random() < 0.28),
                "known_partner_flag": bool(rng.random() < 0.48),
                "capture_stage": rng.choice(["Market Research", "Pipeline", "Qualification", "Proposal Planning"]),
                "status": "Active",
                "synthetic_flag": True,
            }
        )
    opportunities = pd.DataFrame(opportunity_rows)

    return DemoData(
        counties=counties,
        sites=sites,
        organizations=organizations,
        coverage=coverage,
        org_job_families=org_job_families,
        contacts=contacts,
        outreach=outreach,
        applicants=applicants,
        stage_history=stage_history,
        labor_hours=labor_hours,
        opportunities=opportunities,
    )


def export_demo_data(data: DemoData, output_dir: Path, seed: int = DEFAULT_SEED) -> dict:
    """Write reproducible CSVs and a checksum manifest for the user-facing demo."""

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "schema_version": "0.1.0",
        "seed": seed,
        "data_as_of_date": DATA_AS_OF_DATE.isoformat(),
        "synthetic_only": True,
        "datasets": {},
    }
    for name, frame in data.frames().items():
        path = output_dir / f"{name}.csv"
        frame.to_csv(path, index=False, date_format="%Y-%m-%d")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest["datasets"][name] = {"rows": len(frame), "sha256": digest, "file": path.name}
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
