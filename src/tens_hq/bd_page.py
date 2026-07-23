"""Streamlit UI for the public-evidence BD feasibility scanner.

This page is intentionally separate from the synthetic planning dashboards.
It manages public-location cases, analyst-attested workbook imports, evidence
review, route resolution, and a nonnumeric readiness decision.  It never
fetches a URL or joins public directory rows to synthetic people/outcomes.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from .case_store import CaseRepository
from .cases import ROLE_ALIASES, TEAM_ALIASES
from .connectors import (
    DEFAULT_ACS_YEAR,
    SYNTHETIC_EXAMPLE_PIID,
    WORKBOOK_SOURCE_KINDS,
    AbilityOneServicesConnector,
    ConnectorError,
    ContractFactsRecord,
    NIBNPAConnector,
    SourceKind,
    load_synthetic_example_facts,
    pull_contract_facts,
    pull_geography_context,
    pull_pl_notices,
    pull_subawards,
)
from .eligibility_gate import assess_eligibility
from .opportunity_packet import build_opportunity_packet_markdown
from .packet_export import (
    assemble_packet_export,
    derive_section_ledger,
    derive_source_manifest,
    packet_export_filename,
)
from .pl_match import find_pl_service_matches
from .radar_handoff import RadarHandoffError, parse_radar_handoff
from .scanner import ScanStatus, WorkbookScanner
from .staffing_whatif import StaffingWhatIfInput, WhatIfMode, assess_staffing_whatif

# Packet-path `except Exception:` handlers log here before showing a public
# message (never the URL, key, or PII -- a short static context string only).
# This restores a server-side diagnostic trail for an unexpected internal
# error without changing what the operator sees beyond the message itself.
logger = logging.getLogger(__name__)


def _sample_pl_services_bytes() -> bytes:
    """Read the bundled SYNTHETIC example PL Services workbook (offline)."""

    path = Path(__file__).resolve().parents[2] / "data" / "samples" / "sample_pl_services.xlsx"
    return path.read_bytes()


def _sample_radar_handoff_bytes() -> bytes:
    """Read the bundled SYNTHETIC example Radar handoff JSON (offline)."""

    path = Path(__file__).resolve().parents[2] / "data" / "samples" / "sample_radar_handoff.json"
    return path.read_bytes()


def _sample_nib_npa_bytes() -> bytes:
    """Read the bundled SYNTHETIC example NIB/NPA directory workbook (offline)."""

    path = Path(__file__).resolve().parents[2] / "data" / "samples" / "sample_nib_npa.xlsx"
    return path.read_bytes()


_PUBLIC_BANNER = (
    "PUBLIC EVIDENCE PILOT — ORGANIZATIONAL / CONTRACT DIRECTORY DATA ONLY. "
    "Imports are analyst-attested snapshots, not proof of capacity, availability, capability, or commitment."
)
_ROUTE_KINDS = (
    "UNKNOWN",
    "OTHER_FEDERAL_CONFIRMED",
    "ABILITYONE_CONFIRMED",
    "ABILITYONE_REVIEW_REQUIRED",
    "OTHER_FEDERAL_REVIEW",
)

_AWARD_PLACE_PREFILL_SUFFIX = (
    " Prefilled empty place inputs from the award's cited place of performance — "
    "confirm them."
)

# Toast messages render as Markdown, and prefill makes some interpolated inputs
# upstream-fed, so they get the packet renderers' vendored _md treatment:
# flatten line boundaries first (a line break is structural injection), then
# escape link/code/emphasis syntax.
_INLINE_MD_ESCAPE = {ch: "\\" + ch for ch in "\\`*[]()<>"}


def _inline_md(value: object) -> str:
    flat = " ".join(str(value).splitlines())
    return "".join(_INLINE_MD_ESCAPE.get(ch, ch) for ch in flat)


def _prefill_award_place_inputs(record: ContractFactsRecord) -> bool:
    """Fill only blank domestic place inputs from the award's reported components."""

    country = record.pop_country_code
    if country is not None and str(country).strip().upper() != "USA":
        return False
    prefilled = False
    for key, value in (
        ("op_packet_county", record.pop_county_name),
        ("op_packet_state", record.pop_state_code),
        ("op_packet_worksite_city", record.pop_city_name),
    ):
        # A whitespace-only component is judged blank exactly like the target
        # widget, so the success suffix never claims a prefill the renderer
        # would call "Not reported".
        if value is None or not str(value).strip():
            continue
        if not str(st.session_state.get(key) or "").strip():
            st.session_state[key] = value
            prefilled = True
    return prefilled


def _default_db_path() -> str:
    configured = os.getenv("TENS_HQ_DB_PATH")
    if configured:
        return configured
    # bd_page.py lives at repo/src/tens_hq/bd_page.py.
    return str(Path(__file__).resolve().parents[2] / "data" / "runtime" / "tens_hq.sqlite3")


@st.cache_resource(show_spinner=False)
def _repository(db_path: str) -> CaseRepository:
    path = Path(db_path)
    if db_path != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    repo = CaseRepository(db_path)
    repo.recover_interrupted_scans()
    # Startup is a command context (not a passive read), so it is the right
    # place to persist validation reconciliation: get_case is side-effect free,
    # so any case already stale when the process boots is demoted here once and
    # the demotion is durable.  This runs ONCE per server process, so it does NOT
    # cover a case that ages past its freshness budget later during uptime -- the
    # cached repository stays live and this is not re-run.  That gap is closed at
    # read time by deriving the DISPLAYED state live (see _cases_frame /
    # _case_label -> CaseRepository.displayed_state) and in the close command
    # (close_case reconciles the specific case before its transition check).
    repo.reconcile_validations()
    return repo


def _case_options(repo: CaseRepository) -> list[Any]:
    return repo.list_cases()


def _case_label(repo: CaseRepository, case: Any) -> str:
    """Selector label whose state reflects the live freshness-derived display.

    The parenthetical state is the read-only display state (a case that has gone
    stale during uptime reads 'Needs Verification', not a stale 'Validated'),
    not the raw persisted ``case.state``.
    """

    return f"{case.title} — {case.city}, {case.state_code} ({repo.displayed_state(case).value})"


def _case_select(repo: CaseRepository, *, key: str) -> Any | None:
    cases = _case_options(repo)
    if not cases:
        st.info("Create a location case before importing public evidence.")
        return None
    labels = {case.case_id: _case_label(repo, case) for case in cases}
    selected = st.selectbox(
        "Case",
        [case.case_id for case in cases],
        format_func=lambda value: labels.get(value, value),
        key=key,
    )
    return repo.get_case(selected)


def _resource_label(resource: Any) -> str:
    payload = dict(resource.payload)
    return str(
        payload.get("agency_name")
        or payload.get("cna")
        or payload.get("display_name")
        or resource.display_name
        or resource.resource_id
    )


def _resource_frame(resources: list[Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for resource in resources:
        payload = dict(resource.payload)
        rows.append(
            {
                "resource_id": resource.resource_id,
                "source": resource.source_kind,
                "name": _resource_label(resource),
                "city": payload.get("city") or payload.get("parsed_city"),
                "state": payload.get("state") or payload.get("parsed_state"),
                "service": payload.get("service_type"),
                "location": payload.get("service_location"),
                "current": "Current" if resource.current else "Historical",
                "review": resource.review_status,
            }
        )
    return pd.DataFrame(rows)


def _cases_frame(repo: CaseRepository, cases: list[Any]) -> pd.DataFrame:
    """Build the Cases table.

    The ``state`` column is the live display state derived at render time from
    the freshness view (``CaseRepository.displayed_state``), a pure read.  A case
    that was Validated + fresh at startup but has since aged past its freshness
    budget therefore shows 'Needs Verification' here rather than a stale
    'Validated', even though the persisted row still reads 'Validated' until a
    reconcile command writes the demotion.  The caseload is deliberately tiny, so
    the per-row freshness recompute is intended, not an N+1 concern.
    """

    rows = [
        {
            "title": case.title,
            "location": f"{case.city}, {case.state_code}" + (f" {case.postal_code}" if case.postal_code else ""),
            "state": repo.displayed_state(case).value,
            "team": case.team_alias,
            "role": case.role_alias,
            "contract": case.contract_type or "",
            "service": case.service_type or "",
            "headcount": case.target_headcount or "",
            "start": case.target_start_date or "",
            "job families": ", ".join(case.job_family_requirements),
            "case_id": case.case_id,
        }
        for case in cases
    ]
    # Optional columns that are empty across the whole current caseload add
    # visual noise for no information; drop them from the displayed frame
    # (case_id, the internal id, stays available on every row -- just last
    # and not the widest, leading column; `version`, an internal optimistic-
    # concurrency detail, is not user-facing and is dropped entirely).
    optional_columns = ("contract", "service", "headcount", "start", "job families")
    for column in optional_columns:
        if rows and all(not row[column] for row in rows):
            for row in rows:
                del row[column]
    return pd.DataFrame(rows)


def _render_cases(repo: CaseRepository) -> None:
    st.subheader("Feasibility cases")
    st.caption("Cases are prospective public locations. Ownership is a controlled team/role alias, not a person record.")
    cases = repo.list_cases()
    if cases:
        st.dataframe(
            _cases_frame(repo, cases),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No cases yet. Use New Case to start a governed public-evidence review.")


def _render_new_case(repo: CaseRepository) -> None:
    st.subheader("New location case")
    with st.form("public_case_form", clear_on_submit=True):
        title = st.text_input("Case title", placeholder="Denver janitorial market review")
        city = st.text_input("City")
        state = st.text_input("State", max_chars=2, placeholder="CO")
        postal_code = st.text_input("ZIP (optional)", max_chars=5)
        contract_type = st.text_input("Contract / opportunity type (optional)")
        service_type = st.text_input("Service type (optional)")
        has_headcount = st.checkbox("Capture target headcount", value=False)
        target_headcount = st.number_input("Target headcount", min_value=1, step=1, value=1, disabled=not has_headcount)
        target_start_date = st.text_input("Target start date (optional)", placeholder="YYYY-MM-DD")
        job_families = st.text_input("Job-family requirements (comma-separated, optional)")
        cols = st.columns(2)
        team = cols[0].selectbox("Owning team alias", sorted(TEAM_ALIASES), index=sorted(TEAM_ALIASES).index("bd"))
        role = cols[1].selectbox("Working role alias", sorted(ROLE_ALIASES), index=sorted(ROLE_ALIASES).index("owner"))
        submitted = st.form_submit_button("Create case", type="primary")
    if submitted:
        try:
            case = repo.create_case(
                title=title,
                city=city,
                state=state,
                postal_code=postal_code or None,
                team_alias=team,
                role_alias=role,
                contract_type=contract_type.strip() or None,
                service_type=service_type.strip() or None,
                target_headcount=int(target_headcount) if has_headcount else None,
                target_start_date=target_start_date.strip() or None,
                job_family_requirements=tuple(item.strip() for item in job_families.split(",") if item.strip()),
            )
            st.success(f"Created {case.title} ({case.case_id}).")
        except Exception:
            st.error("The case could not be created. Check the title, city, state, and ZIP format.")


def _render_scan(repo: CaseRepository) -> None:
    st.subheader("Scan and evidence")
    case = _case_select(repo, key="scan_case")
    if case is None:
        return
    st.caption("Upload one approved official workbook export per run. The app parses locally and stores provenance plus normalized public rows; it does not scrape or fetch at runtime.")
    with st.form("public_scan_form"):
        source = st.selectbox("Approved source", [kind.value for kind in WORKBOOK_SOURCE_KINDS])
        workbook = st.file_uploader("Official workbook export (.xlsx)", type=["xlsx"])
        use_sample_nib_npa = st.checkbox(
            "Use the bundled SYNTHETIC NIB/NPA example instead of an upload",
            key="scan_use_sample_nib_npa",
            value=False,
        )
        idempotency_key = st.text_input("Retry key (optional)", placeholder="capture-2026-07-18-denver-nib")
        actor_role = st.selectbox("Analyst role", ["Analyst", "Reviewer", "Compliance Reviewer"])
        retrieved_at = st.text_input("Source retrieval time (UTC; leave blank if unknown)", placeholder="2026-07-18T14:30:00Z")
        attested = st.checkbox("I attest this is an approved public AbilityOne workbook export", value=False)
        submitted = st.form_submit_button("Run local scan", type="primary")
    if submitted:
        if use_sample_nib_npa:
            scan_source = SourceKind.NIB_NPA.value
            scan_bytes: bytes | None = _sample_nib_npa_bytes()
            scan_filename: str | None = "sample_nib_npa.xlsx"
        elif workbook is not None:
            scan_source = source
            scan_bytes = workbook.getvalue()
            scan_filename = workbook.name
        else:
            scan_source = source
            scan_bytes = None
            scan_filename = None
        if scan_bytes is None:
            st.warning("Choose an approved workbook before running the scan.")
        elif not attested:
            st.warning("Confirm the public-source attestation before running a scan.")
        else:
            result = WorkbookScanner(repo).run_scan(
                case.case_id,
                scan_source,
                scan_bytes,
                scan_filename,
                idempotency_key=idempotency_key or None,
                actor_role=actor_role,
                retrieved_at=retrieved_at.strip() or None,
            )
            if result.status is ScanStatus.FAILED:
                st.error(f"Scan failed: {result.message or 'The workbook could not be processed.'}")
            elif result.status is ScanStatus.PARTIAL:
                st.warning(f"Partial import: {result.record_count} rows retained; resolve the blocking anomaly task before verification.")
            elif result.status is ScanStatus.IDEMPOTENT_REPLAY:
                st.info("Retry key matched an earlier scan; no duplicate import was created.")
            else:
                st.success(f"Scan succeeded: {result.record_count} normalized public rows.")
            with st.expander("Scan detail (raw)", expanded=False):
                st.json(result.to_dict())

    resources = repo.list_resources(case.case_id, current_only=True)
    if resources:
        st.markdown("#### Current public evidence")
        st.dataframe(_resource_frame(resources), hide_index=True, use_container_width=True)
    scans = repo.list_scans(case.case_id)
    if scans:
        st.markdown("#### Scan history")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "scan_id": scan.scan_id,
                        "source": scan.source_kind,
                        "workbook": scan.workbook_name,
                        "status": scan.status,
                        "rows": scan.row_count,
                        "started": scan.started_at,
                        "finished": scan.finished_at,
                        "error": scan.error_message,
                    }
                    for scan in scans[:25]
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        snapshots = repo.list_snapshots(case.case_id)
        if snapshots:
            st.markdown("#### Source manifest")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "source": snapshot.source_kind,
                            "workbook": snapshot.workbook_name,
                            "source_uri": snapshot.source_uri or "",
                            "workbook_sha256": snapshot.workbook_sha256,
                            "schema_fingerprint": snapshot.schema_fingerprint or "",
                            "observed_at": snapshot.observed_at,
                            "retrieved_at": snapshot.retrieved_at or "Not supplied",
                            "rows_retained": snapshot.row_count,
                            "rows_seen": snapshot.source_row_count or snapshot.row_count,
                            "excluded": snapshot.excluded_row_count,
                            "assurance": snapshot.assurance or "USER_ATTESTED",
                            "parser": snapshot.source_version or "abilityone-xlsx-v1",
                            "bytes": snapshot.byte_size,
                            "payload_retained": snapshot.payload_retained,
                        }
                        for snapshot in snapshots[:25]
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
        exclusions = repo.list_exclusions(case.case_id)
        if exclusions:
            st.caption(f"{len(exclusions)} source rows are in quarantine; only bounded identifiers are shown here.")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "exclusion_id": item["exclusion_id"],
                            "scan_id": item["scan_id"],
                            "source": item["source_kind"],
                            "row_hash": item["row_hash"],
                            "source_row": item["source_row"],
                            "reason": item["reason"],
                        }
                        for item in exclusions[:100]
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )


def _render_verification(repo: CaseRepository) -> None:
    st.subheader("Verification queue")
    case = _case_select(repo, key="verification_case")
    if case is None:
        return
    resources = repo.list_resources(case.case_id, current_only=True)
    if resources:
        st.markdown("#### Review current resources")
        st.caption("Review status is an analyst assertion about relevance for this case. It is not a capacity or relationship claim.")
        for resource in resources[:100]:
            label = f"{_resource_label(resource)} · {resource.source_kind} · {resource.resource_id[:12]}"
            with st.expander(label):
                st.json(dict(resource.payload))
                cols = st.columns([1, 2, 1])
                review = cols[0].selectbox("Review", ["unreviewed", "verified", "rejected"], index=["unreviewed", "verified", "rejected"].index(resource.review_status), key=f"review_{resource.resource_id}")
                note = cols[1].text_input("Review note", value=resource.review_note or "", key=f"review_note_{resource.resource_id}")
                if cols[2].button("Save", key=f"save_review_{resource.resource_id}"):
                    try:
                        repo.update_resource_review(resource.resource_id, review, review_note=note or None)
                        st.success("Review saved.")
                    except Exception:
                        st.error("Review could not be saved.")
    else:
        st.info("No current public resources are available for review.")

    st.markdown("#### Route hypotheses")
    with st.form("route_hypothesis_form"):
        route_kind = st.selectbox("Route status", _ROUTE_KINDS)
        target = st.text_input("Public route target", placeholder="AbilityOne Procurement List")
        source_label = st.text_input("Public source/page label", placeholder="AbilityOne Procurement List / official report page")
        rationale = st.text_area("Analyst rationale (no personal data)")
        add_route = st.form_submit_button("Add route hypothesis")
    if add_route:
        if route_kind == "UNKNOWN" or not target.strip() or (route_kind in {"ABILITYONE_CONFIRMED", "OTHER_FEDERAL_CONFIRMED"} and (not source_label.strip() or not rationale.strip())):
            st.warning("Choose a route category, public target, source label, and rationale before saving a confirmed route.")
        else:
            try:
                repo.add_route_hypothesis(case.case_id, route_kind, target.strip(), rationale=rationale.strip(), source_label=source_label.strip() or None)
                st.success("Route hypothesis added for analyst resolution.")
            except Exception:
                st.error("Route hypothesis could not be saved.")
    for hypothesis in repo.list_route_hypotheses(case.case_id):
        cols = st.columns([2, 2, 1, 1])
        cols[0].write(f"**{hypothesis.route_kind}**")
        cols[1].write(hypothesis.target)
        cols[2].write(hypothesis.status.value)
        if hypothesis.status.value == "hypothesis" and hypothesis.route_kind in {"ABILITYONE_CONFIRMED", "OTHER_FEDERAL_CONFIRMED"}:
            resolution_source = st.text_input("Resolution source label", value=hypothesis.source_label or "", key=f"route_source_{hypothesis.hypothesis_id}")
            resolution_rationale = st.text_area("Resolution rationale", value=hypothesis.rationale or "", key=f"route_rationale_{hypothesis.hypothesis_id}")
        else:
            resolution_source = ""
            resolution_rationale = ""
        if hypothesis.status.value == "hypothesis" and hypothesis.route_kind in {"ABILITYONE_CONFIRMED", "OTHER_FEDERAL_CONFIRMED"} and cols[3].button("Resolve", key=f"resolve_route_{hypothesis.hypothesis_id}"):
            try:
                repo.resolve_route(hypothesis.hypothesis_id, "resolved", rationale=resolution_rationale.strip(), source_label=resolution_source.strip())
                st.success("Route resolved.")
            except Exception:
                st.error("Route could not be resolved.")

    st.markdown("#### Open tasks")
    tasks = repo.list_tasks(case.case_id, open_only=True)
    if tasks:
        for task in tasks:
            cols = st.columns([1, 3, 1, 2, 1])
            cols[0].write(task.severity.value.upper())
            cols[1].write(task.title)
            cols[2].write(task.task_type)
            if task.task_type == "SCAN_FAILED":
                cols[3].write("Retry scan")
            else:
                reason = cols[3].text_input("Resolution reason", key=f"task_reason_{task.task_id}")
                if not cols[4].button("Resolve", key=f"resolve_task_{task.task_id}"):
                    continue
                try:
                    repo.resolve_task(task.task_id, reason=reason)
                    st.success("Task resolved.")
                except Exception:
                    st.error("Enter a resolution reason before closing this task.")
    else:
        st.caption("No open scanner tasks.")


def _readiness_label(repo: CaseRepository, case: Any, assessment: Any) -> str:
    if case.state.value == "Validated" and assessment.ready and not repo.list_tasks(case.case_id, open_only=True, severity="blocking"):
        return "Validated"
    if assessment.ready:
        return "Verified"
    if repo.list_scans(case.case_id, status="succeeded") or repo.list_scans(case.case_id, status="partial"):
        return "Researching"
    return "Insufficient"


def _render_assessment(repo: CaseRepository) -> None:
    st.subheader("Readiness assessment")
    case = _case_select(repo, key="assessment_case")
    if case is None:
        return
    assessment = repo.compute_readiness(case.case_id)
    label = _readiness_label(repo, case, assessment)
    st.metric("Public-evidence readiness", label)
    st.caption("This is a nonnumeric evidence state. It is not a bid/no-bid recommendation, candidate forecast, capacity claim, or partner commitment.")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "requirement": item.label,
                    "state": item.state.value,
                    "blocking": "Yes" if item.blocking else "Advisory",
                    "note": item.note or "",
                }
                for item in assessment.items
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
    snapshots = repo.list_snapshots(case.case_id)
    open_tasks = repo.list_tasks(case.case_id, open_only=True)
    export_lines = [
        f"# Public-evidence assessment: {case.title}",
        "",
        f"- Location: {case.city}, {case.state_code}" + (f" {case.postal_code}" if case.postal_code else ""),
        f"- As of: {datetime.now(timezone.utc).isoformat()}",
        f"- State: {label}",
        f"- Case version: {case.version}",
        "- Readiness contract: PUBLIC-EVIDENCE-1 (nonnumeric)",
        "- Parser contract: abilityone-xlsx-v1",
        f"- Contract / opportunity type: {case.contract_type or 'Not supplied'}",
        f"- Service type: {case.service_type or 'Not supplied'}",
        f"- Target headcount: {case.target_headcount if case.target_headcount is not None else 'Not supplied'}",
        f"- Target start date: {case.target_start_date or 'Not supplied'}",
        f"- Job-family requirements: {', '.join(case.job_family_requirements) or 'Not supplied'}",
        "- This report contains public directory evidence only; it is not a capacity, candidate, partner, or acquisition claim.",
        "- Workbook bytes are not retained. Retrieval time is analyst-supplied and may be unknown.",
        "",
        "| Requirement | State | Blocking | Note |",
        "|---|---|---|---|",
    ]
    export_lines.extend(
        f"| {item.label.replace('|', '/')} | {item.state.value} | {'Yes' if item.blocking else 'No'} | {(item.note or '').replace('|', '/')} |"
        for item in assessment.items
    )
    export_lines.extend(["", "## Source manifest", "", "| Source | Workbook | URI | SHA-256 | Schema | Retrieved at | Rows retained | Rows seen | Excluded |", "|---|---|---|---|---|---|---:|---:|---:|"])
    export_lines.extend(
        f"| {snapshot.source_kind} | {snapshot.workbook_name.replace('|', '/')} | {(snapshot.source_uri or '').replace('|', '/')} | {snapshot.workbook_sha256} | {(snapshot.schema_fingerprint or '').replace('|', '/')} | {snapshot.retrieved_at or 'Not supplied'} | {snapshot.row_count} | {snapshot.source_row_count if snapshot.source_row_count is not None else snapshot.row_count} | {snapshot.excluded_row_count} |"
        for snapshot in snapshots[:25]
    )
    export_lines.extend(["", "## Open tasks", ""])
    if open_tasks:
        export_lines.extend(f"- {task.severity.value.upper()}: {task.title} (`{task.task_type}`)" for task in open_tasks)
    else:
        export_lines.append("- None")
    st.download_button(
        "Export Markdown assessment",
        data="\n".join(export_lines) + "\n",
        file_name=f"{case.case_id}-public-assessment.md",
        mime="text/markdown",
        key=f"export_assessment_{case.case_id}",
    )
    if assessment.blocking:
        st.warning("Resolve every blocking requirement and open task before validating this case.")
        for item in assessment.blocking:
            st.markdown(f"- **{item.label}** — {item.state.value}")
    if assessment.advisory:
        st.info("Advisory review remains open; it does not create a numeric score.")
    if st.button("Record analyst validation", key=f"validate_case_{case.case_id}", disabled=not assessment.ready):
        try:
            validated = repo.validate_case(case.case_id, expected_version=case.version)
            if validated.state.value == "Validated":
                st.success("Case validated with a durable evidence fingerprint.")
            else:
                st.warning("Case still needs verification.")
        except Exception:
            st.error("The case could not be validated; refresh and resolve any newly opened task.")


def _render_opportunity_packet() -> None:
    """Cited Opportunity Packet: pasted PIID + place -> one-page evidence sheet.

    This surface is deliberately case-independent and paste-driven. It composes
    an optional Origin (Radar handoff) section (A2, :mod:`tens_hq.radar_handoff`,
    ADR-019), the Eligibility Gate, analyst-entered Contract Facts, Capture
    Window, Incumbent & teaming leads / PL-impact context, an optional
    Staffing what-if section (A6, :mod:`tens_hq.staffing_whatif`, ADR-021),
    an ACS geography context panel, the R2b Procurement List
    cross-reference, and an optional Procurement List activity (Federal
    Register) section (A4, :mod:`tens_hq.pl_activity`, ADR-023), and renders
    NO score (N1). The geography figure is context, not candidate supply
    (N2/N4).
    Four independent pieces of evidence are pulled live only on their own
    explicit analyst action (contract facts, subaward records, ACS geography
    context, and Federal Register PL-notice activity); the packet renders
    offline until then. The Radar handoff is an
    UPLOAD, never a live pull -- it prefills only the retrieval inputs (PIID,
    county, state, worksite city) and never an assessment input. The
    Staffing what-if is entirely analyst-typed, independent of Contract
    Facts, and renders only once a baseline value is entered.
    """

    st.subheader("Opportunity Packet")
    st.caption(
        "Paste a contract identifier and place. The packet assembles a cited, "
        "provenance-tracked evidence sheet for human review. It never renders a "
        "score, ranking, or bid/no-bid recommendation."
    )

    st.markdown("#### Origin — Radar handoff intake")
    st.caption(
        "Optional. Upload a versioned handoff JSON exported from GovConRadar to "
        "prefill this packet's retrieval inputs below (PIID, county, state, "
        "worksite city). The handoff renders as a labeled, caveat-first claim "
        "in an Origin section -- it is never packet evidence and never feeds "
        "the Eligibility Gate or any other assessment."
    )
    handoff_upload = st.file_uploader(
        "Radar handoff (.json)", type=["json"], key="op_packet_handoff_upload"
    )
    use_handoff_sample = st.checkbox(
        "Use the bundled SYNTHETIC example instead of an upload",
        key="op_packet_handoff_use_sample",
        value=False,
    )
    handoff_action_cols = st.columns(2)
    if handoff_action_cols[0].button("Use handoff", key="op_packet_handoff_use"):
        if use_handoff_sample:
            handoff_bytes: bytes | None = _sample_radar_handoff_bytes()
            handoff_label: str | None = "sample_radar_handoff.json (SYNTHETIC example)"
        elif handoff_upload is not None:
            handoff_bytes = handoff_upload.getvalue()
            handoff_label = handoff_upload.name
        else:
            handoff_bytes = None
            handoff_label = None
        if handoff_bytes is None:
            st.warning("Upload a handoff JSON file or select the bundled example.")
        else:
            try:
                parsed_handoff = parse_radar_handoff(handoff_bytes)
                st.session_state["op_packet_handoff"] = {
                    "sha256": sha256(handoff_bytes).hexdigest(),
                    "source_label": handoff_label,
                    "synthetic": parsed_handoff.synthetic_sample,
                    "handoff": parsed_handoff,
                }
                # Prefill ONLY the retrieval inputs (§1.2) -- never the
                # analyst set-aside input. The intake sits above these
                # widgets, so this same-run session-state assignment is safe
                # (mirrors app.py's own nav/tour prefill pattern).
                place = parsed_handoff.claims.place_of_performance
                st.session_state["op_packet_piid"] = parsed_handoff.piid
                st.session_state["op_packet_county"] = (
                    place.county if place and place.county else ""
                )
                st.session_state["op_packet_state"] = (
                    place.state if place and place.state else ""
                )
                st.session_state["op_packet_worksite_city"] = (
                    place.city if place and place.city else ""
                )
                st.success("Attached the Radar handoff and prefilled the retrieval inputs.")
            except RadarHandoffError as exc:
                st.session_state.pop("op_packet_handoff", None)
                st.error(f"Could not read the handoff: {exc.public_message}")
            except Exception:
                logger.exception("radar-handoff parsing failed unexpectedly")
                st.session_state.pop("op_packet_handoff", None)
                st.error(
                    "Could not read the handoff. Confirm it is a valid "
                    "radar-handoff/v1 JSON file."
                )
    if handoff_action_cols[1].button("Clear handoff", key="op_packet_handoff_clear"):
        st.session_state.pop("op_packet_handoff", None)
    st.divider()

    piid = st.text_input("Contract PIID (analyst paste)", key="op_packet_piid", placeholder="47QRAA24D0012")
    # The handoff never re-gates itself off a stale reuse -- it is a fresh
    # strip-only PIID compare every render (D9, mirrors the reuse-guard at
    # bd_page.py:583 exactly: no casefold). The handoff's own piid is stored
    # VERBATIM, so only an actual analyst edit to the PIID input breaks the
    # match; dropping context on a mismatch is the safe direction.
    handoff_stored = st.session_state.get("op_packet_handoff")
    handoff = handoff_stored.get("handoff") if handoff_stored is not None else None
    handoff_source_label = (
        handoff_stored.get("source_label") if handoff_stored is not None else None
    )
    handoff_piid_matched = handoff is not None and handoff.piid.strip() == piid.strip()
    st.caption(
        "The contract-facts pull performs one analyst-initiated live request to "
        "USAspending and fails loud if the source is unavailable. This packet "
        "page has four independent analyst-initiated live requests in total "
        "(contract facts, subaward records, ACS geography context, and Federal "
        "Register PL-notice activity); each fires only on its own explicit "
        "button."
    )
    if st.button("Pull contract facts (live)", key="op_packet_facts_pull"):
        if not piid.strip():
            st.warning("Enter a contract PIID before pulling live facts.")
        else:
            try:
                # ADR-025: the bundled synthetic PIID resolves offline, from the
                # committed sample -- no network call. Every other PIID is the
                # unchanged live path.
                if piid.strip() == SYNTHETIC_EXAMPLE_PIID:
                    resolution = load_synthetic_example_facts()
                else:
                    resolution = pull_contract_facts(piid.strip())
                st.session_state["op_packet_facts_result"] = {
                    "piid": piid.strip(),
                    "resolution": resolution,
                }
                if resolution.resolved:
                    prefilled = (
                        resolution.record is not None
                        and _prefill_award_place_inputs(resolution.record)
                    )
                    if resolution.record is not None and resolution.record.synthetic_example:
                        success_message = (
                            "Loaded the bundled SYNTHETIC example contract facts "
                            "(offline) — not a live retrieval."
                        )
                    else:
                        success_message = "Attached live USAspending contract facts."
                    if prefilled:
                        success_message += _AWARD_PLACE_PREFILL_SUFFIX
                    st.success(success_message)
                else:
                    st.warning(
                        f"{len(resolution.candidates)} awards share PIID {piid.strip()} "
                        "(a PIID is not unique). Pick the exact award below."
                    )
            except ConnectorError as exc:
                st.session_state.pop("op_packet_facts_result", None)
                st.error(f"Could not retrieve contract facts: {exc.public_message}")
                if exc.code in {"AWARD_NOT_FOUND", "UPSTREAM_UNAVAILABLE"}:
                    # §5.3 / QW8: reconcile the offline/synthetic-PIID failure at
                    # the point of failure instead of only in operator notes --
                    # both codes cover the same reader intent ("why didn't my
                    # paste resolve?"): a made-up PIID that a live search cannot
                    # find, or a live search that cannot run at all offline.
                    st.caption(
                        "Offline or a synthetic example PIID cannot resolve live facts -- "
                        "use the bundled SYNTHETIC example (below, at Origin) for an offline "
                        "walkthrough, or a real PIID with a network connection."
                    )
            except Exception:
                logger.exception("contract-facts pull failed unexpectedly")
                st.session_state.pop("op_packet_facts_result", None)
                st.error(
                    "An unexpected internal error occurred while retrieving "
                    "contract facts; it has been logged."
                )

    facts_stored = st.session_state.get("op_packet_facts_result")
    resolution = None
    contract_facts = None
    if facts_stored is not None and facts_stored.get("piid") == piid.strip():
        resolution = facts_stored.get("resolution")
        if resolution is not None and resolution.resolved:
            contract_facts = resolution.record

    if resolution is not None and resolution.ambiguous:
        labels = {}
        for candidate in resolution.candidates:
            # A null money amount is "not reported", never a fabricated $0.00; the
            # same honesty the packet renderer holds for absent fields.
            amount = (
                f"${candidate.award_amount:,.2f}"
                if candidate.award_amount is not None
                else "amount not reported"
            )
            labels[candidate.generated_internal_id] = (
                f"{candidate.recipient_name or 'Recipient not reported'} · "
                f"{candidate.subagency_name or 'sub-agency not reported'} · "
                f"{amount} · start {candidate.start_date or 'not reported'} · "
                f"PSC {candidate.psc_code or 'not reported'} · {candidate.generated_internal_id}"
            )
        chosen = st.selectbox(
            "Select the exact award",
            list(labels),
            format_func=lambda value: labels[value],
            key="op_packet_facts_pick",
        )
        if st.button("Use this award", key="op_packet_facts_pick_go"):
            try:
                resolved = pull_contract_facts(
                    piid.strip(), generated_internal_id=chosen
                )
                st.session_state["op_packet_facts_result"] = {
                    "piid": piid.strip(),
                    "resolution": resolved,
                }
                prefilled = (
                    resolved.resolved
                    and resolved.record is not None
                    and _prefill_award_place_inputs(resolved.record)
                )
                success_message = "Attached the selected award's live contract facts."
                if prefilled:
                    success_message += _AWARD_PLACE_PREFILL_SUFFIX
                st.success(success_message)
                contract_facts = resolved.record
            except ConnectorError as exc:
                st.error(f"Could not retrieve contract facts: {exc.public_message}")
            except Exception:
                logger.exception("contract-facts award-selection pull failed unexpectedly")
                st.error(
                    "An unexpected internal error occurred while retrieving "
                    "the selected award's contract facts; it has been logged."
                )

    st.caption(
        "Optional -- incumbent & teaming leads. The subaward pull performs one "
        "analyst-initiated live request to USAspending for the resolved award's "
        "reported subawards (teaming-posture evidence, not proof of a "
        "relationship) and fails loud if the source is unavailable. Enabled "
        "only once a single award is resolved above."
    )
    if st.button(
        "Pull subaward records (live)",
        key="op_packet_subawards_pull",
        disabled=contract_facts is None or not contract_facts.generated_unique_award_id,
    ):
        award_id = contract_facts.generated_unique_award_id
        try:
            subawards_result = pull_subawards(award_id)
            st.session_state["op_packet_subawards_result"] = {
                "award_id": award_id,
                "result": subawards_result,
            }
            st.success(f"Attached {len(subawards_result.records)} subaward record(s) for this award.")
        except ConnectorError as exc:
            st.session_state.pop("op_packet_subawards_result", None)
            st.error(f"Could not retrieve subaward records: {exc.public_message}")
        except Exception:
            logger.exception("subaward records pull failed unexpectedly")
            st.session_state.pop("op_packet_subawards_result", None)
            st.error(
                "An unexpected internal error occurred while retrieving "
                "subaward records; it has been logged."
            )

    # Reuse a stored subawards pull only when it matches the CURRENTLY resolved
    # award's generated id (mirrors the R2b upload reuse-guard style below): a
    # stale pull from a previously-resolved award must never attach to a
    # different one.
    subawards_stored = st.session_state.get("op_packet_subawards_result")
    subawards = None
    if (
        subawards_stored is not None
        and contract_facts is not None
        and subawards_stored.get("award_id") == contract_facts.generated_unique_award_id
    ):
        subawards = subawards_stored.get("result")

    st.caption(
        "Optional. Upload a current NIB or SourceAmerica nonprofit-agency "
        "directory export (.xlsx) to cross-reference reported subawardee names "
        "against it by normalized EXACT name match only (no fuzzy matching). "
        "Parsed locally; the workbook is not persisted, stored, or joined to "
        "any case -- packet-local only, exactly like the R2b upload below."
    )
    directory_upload = st.file_uploader(
        "AbilityOne NPA directory workbook (.xlsx)", type=["xlsx"], key="op_packet_directory_upload"
    )
    # USER_ATTESTED provenance label for the export's Source manifest -- the
    # upload's own filename, carried through independent of whether it parsed.
    directory_source_label = directory_upload.name if directory_upload is not None else None
    directory_agency_names = None
    if directory_upload is not None:
        try:
            directory_records = NIBNPAConnector().parse(directory_upload.getvalue()).records
            directory_agency_names = [
                name for record in directory_records if (name := record.get("agency_name"))
            ]
        except ConnectorError as exc:
            st.error(f"Could not read the directory workbook: {exc.public_message}")
        except Exception:
            logger.exception("directory workbook parsing failed unexpectedly")
            st.error("Could not read the directory workbook. Confirm it is an approved .xlsx export.")

    st.divider()
    # Distinct wording from the packet's own rendered section header
    # (staffing_whatif.STAFFING_HEADER, "## Staffing what-if (ODLH planning
    # indicator)") -- deliberately NOT "Staffing what-if" as a contiguous
    # phrase, since a Markdown "####" heading contains "##" as a leading
    # substring and would otherwise false-positive a "## Staffing what-if in
    # packet" containment check the way the Radar-handoff intake/section
    # pair already must avoid above.
    st.markdown("#### Contract staffing scenario inputs")
    st.caption(
        "Optional. Enter the agency's current staffing baseline and a "
        "contract staffing scenario to see the marginal effect on the "
        "agency-wide ODLH ratio -- a labeled planning indicator, never an "
        "official ODLH compliance determination. Framed as evidence toward "
        "suitability criterion (a)(2) only; the Commission determines "
        "suitability. Independent of the live Contract Facts pulled above; "
        "the packet stays usable without it."
    )
    # A checkbox, not a radio (test_app_runtime.py's page-navigation tests key
    # off ``app.radio[0]`` being the sidebar nav radio; a second top-level
    # radio widget elsewhere changes AppTest's positional radio ordering and
    # breaks that assumption -- a checkbox avoids the collision entirely).
    whatif_use_fte = st.checkbox(
        "Use FTE headcount entry mode (approximation) instead of direct "
        "labor hours",
        key="op_packet_whatif_fte_mode",
        value=False,
    )
    whatif_mode = WhatIfMode.FTE if whatif_use_fte else WhatIfMode.HOURS
    baseline_entered = False
    if whatif_mode is WhatIfMode.HOURS:
        st.caption(
            "Enter DIRECT labor hours only -- supervisory and indirect "
            "hours are excluded from the ODLH computation."
        )
        hrs_cols = st.columns(2)
        whatif_baseline_qh = hrs_cols[0].number_input(
            "Baseline disabled direct labor hours (agency-wide)",
            min_value=0.0, value=None, key="op_packet_whatif_baseline_qh",
        )
        whatif_baseline_th = hrs_cols[1].number_input(
            "Baseline total direct labor hours (agency-wide)",
            min_value=0.0, value=None, key="op_packet_whatif_baseline_th",
        )
        whatif_scenario_th = st.number_input(
            "Scenario: direct labor hours added by this contract",
            min_value=0.0, value=None, key="op_packet_whatif_scenario_th",
        )
        qual_cols = st.columns(2)
        whatif_share_pct = qual_cols[0].number_input(
            "Assumed qualifying share of the addition (0-100%; leave "
            "blank if entering a count instead)",
            min_value=0.0, max_value=100.0, value=None, key="op_packet_whatif_share_hours",
        )
        whatif_qual_count = qual_cols[1].number_input(
            "OR assumed qualifying hours added (leave blank if entering "
            "a share instead)",
            min_value=0.0, value=None, key="op_packet_whatif_count_hours",
        )
        whatif_input = StaffingWhatIfInput(
            mode=WhatIfMode.HOURS,
            baseline_qualifying_hours=whatif_baseline_qh,
            baseline_total_hours=whatif_baseline_th,
            scenario_total_hours=whatif_scenario_th,
            scenario_qualifying_share=(
                whatif_share_pct / 100.0 if whatif_share_pct is not None else None
            ),
            scenario_qualifying_count=whatif_qual_count,
        )
        baseline_entered = whatif_baseline_qh is not None or whatif_baseline_th is not None
    else:
        st.caption(
            "A headcount cannot separate a person's supervisory/indirect "
            "hours from their direct-labor hours, so this mode is only an "
            "APPROXIMATION of the hours-based statutory ratio."
        )
        fte_cols = st.columns(3)
        whatif_baseline_01 = fte_cols[0].number_input(
            "Baseline code 01 (non-disabled) FTE (agency-wide)",
            min_value=0.0, value=None, key="op_packet_whatif_baseline_01",
        )
        whatif_baseline_02 = fte_cols[1].number_input(
            "Baseline code 02 (disabled) FTE (agency-wide)",
            min_value=0.0, value=None, key="op_packet_whatif_baseline_02",
        )
        whatif_baseline_07 = fte_cols[2].number_input(
            "Baseline code 07 (pending documentation) FTE (optional, "
            "display-only)",
            min_value=0.0, value=None, key="op_packet_whatif_baseline_07",
        )
        whatif_scenario_fte = st.number_input(
            "Scenario: FTE added by this contract",
            min_value=0.0, value=None, key="op_packet_whatif_scenario_fte",
        )
        qual_cols = st.columns(2)
        whatif_share_pct = qual_cols[0].number_input(
            "Assumed qualifying share of the addition (0-100%; leave "
            "blank if entering a count instead)",
            min_value=0.0, max_value=100.0, value=None, key="op_packet_whatif_share_fte",
        )
        whatif_qual_count = qual_cols[1].number_input(
            "OR assumed qualifying FTE added (leave blank if entering a "
            "share instead)",
            min_value=0.0, value=None, key="op_packet_whatif_count_fte",
        )
        whatif_input = StaffingWhatIfInput(
            mode=WhatIfMode.FTE,
            baseline_code_01=whatif_baseline_01,
            baseline_code_02=whatif_baseline_02,
            baseline_code_07=whatif_baseline_07,
            scenario_total_fte=whatif_scenario_fte,
            scenario_qualifying_share=(
                whatif_share_pct / 100.0 if whatif_share_pct is not None else None
            ),
            scenario_qualifying_count=whatif_qual_count,
        )
        baseline_entered = (
            whatif_baseline_01 is not None
            or whatif_baseline_02 is not None
            or whatif_baseline_07 is not None
        )
    staffing = assess_staffing_whatif(whatif_input) if baseline_entered else None

    set_aside_value = st.text_input(
        "Contract set-aside status (raw code; leave blank if unknown)",
        key="op_packet_set_aside",
    )
    st.caption(
        "Blank = Unknown (not unrestricted); `NONE` = no set-aside restriction "
        "reported. "
        "Analyst-entered and not independently verified."
    )
    eligibility = assess_eligibility(set_aside_value)
    place_cols = st.columns([2, 1, 1])
    county = place_cols[0].text_input("County", key="op_packet_county", placeholder="Denver")
    state = place_cols[1].text_input("State", key="op_packet_state", max_chars=2, placeholder="CO")
    year = int(
        place_cols[2].number_input(
            "ACS 5-year vintage",
            min_value=2010,
            max_value=2100,
            value=DEFAULT_ACS_YEAR,
            step=1,
            key="op_packet_year",
        )
    )
    st.caption(
        "The ACS pull performs one analyst-initiated live request to the public "
        "Census API -- the third of this packet page's four independent live "
        "requests (contract facts, subaward records, ACS geography context, and "
        "Federal Register PL-notice activity) -- and fails loud if the source is "
        "unavailable."
    )
    if st.button("Pull ACS geography context (live)", key="op_packet_pull"):
        if not county.strip() or not state.strip():
            st.warning("Enter a county and state before pulling ACS context.")
        else:
            try:
                record = pull_geography_context(county.strip(), state.strip(), year=year)
                st.session_state["op_packet_result"] = {
                    "county": county.strip().casefold(),
                    "state": state.strip().upper(),
                    "year": year,
                    "geography": record,
                }
                st.success("Attached ACS geography context.")
            except ConnectorError as exc:
                st.session_state.pop("op_packet_result", None)
                st.error(f"Could not retrieve ACS context: {exc.public_message}")
            except Exception:
                logger.exception("ACS geography context pull failed unexpectedly")
                st.session_state.pop("op_packet_result", None)
                st.error(
                    "An unexpected internal error occurred while retrieving "
                    "ACS geography context; it has been logged."
                )

    # Only reuse a stored geography when it matches the current place inputs, so
    # a figure is never shown against the wrong county.
    stored = st.session_state.get("op_packet_result")
    geography = None
    if (
        stored is not None
        and stored.get("county") == county.strip().casefold()
        and stored.get("state") == state.strip().upper()
        and stored.get("year") == year
    ):
        geography = stored.get("geography")

    st.divider()
    st.markdown("#### Procurement List cross-reference (R2b)")
    st.caption(
        "Optional. Cross-reference this worksite against an AbilityOne PL Services "
        "workbook to see any Procurement List line at the exact same city/state. "
        "Discovery evidence only -- it never asserts a route, a convertibility, or "
        "which agency holds a line."
    )
    # The worksite city is a SEPARATE input from the ACS County above: exact
    # city/state is the PL match key (a county is not a city) and the state is
    # shared with the place-of-performance field.
    pl_cols = st.columns([2, 2])
    worksite_city = pl_cols[0].text_input(
        "Worksite city (PL match; may differ from the ACS County above)",
        key="op_packet_worksite_city",
        placeholder="Denver",
    )
    pl_service_type = pl_cols[1].text_input(
        "Contract service type (optional)",
        key="op_packet_service_type",
        placeholder="Custodial",
    )
    pl_retrieved = st.text_input(
        "PL workbook retrieval date (analyst attests; leave blank if unknown)",
        key="op_packet_pl_retrieved",
        placeholder="2026-07-15",
    )
    pl_upload = st.file_uploader(
        "AbilityOne PL Services workbook (.xlsx)", type=["xlsx"], key="op_packet_pl_upload"
    )
    use_sample = st.checkbox(
        "Use the bundled SYNTHETIC example instead of an upload",
        key="op_packet_pl_use_sample",
        value=False,
    )
    # Resolve the selected PL source once so the button handler and the reuse
    # guard agree on which workbook a stored result belongs to.
    state_up = state.strip().upper()
    if use_sample:
        pl_source_label: str | None = "sample_pl_services.xlsx (SYNTHETIC example)"
        pl_synthetic = True
    elif pl_upload is not None:
        pl_source_label = pl_upload.name
        pl_synthetic = False
    else:
        pl_source_label = None
        pl_synthetic = False

    if st.button("Cross-reference the Procurement List", key="op_packet_pl_run"):
        if not worksite_city.strip() or not state_up:
            st.warning("Enter a worksite city and state before cross-referencing.")
        elif pl_source_label is None:
            st.warning("Upload a PL Services workbook or select the bundled example.")
        else:
            try:
                data = _sample_pl_services_bytes() if use_sample else pl_upload.getvalue()
                records = AbilityOneServicesConnector().parse(data).records
                result = find_pl_service_matches(
                    records,
                    city=worksite_city.strip(),
                    state=state_up,
                    service_type=pl_service_type.strip() or None,
                    source_label=pl_source_label,
                    retrieved_at=pl_retrieved.strip() or None,
                    synthetic_sample=pl_synthetic,
                )
                st.session_state["op_packet_pl_result"] = {
                    "city": worksite_city.strip().casefold(),
                    "state": state_up,
                    "service_type": pl_service_type.strip().casefold(),
                    "source": pl_source_label,
                    "synthetic": pl_synthetic,
                    "result": result,
                }
                st.success(
                    f"Cross-referenced {result.same_location_count} Procurement List "
                    f"line(s) parsed to {_inline_md(worksite_city.strip())}, "
                    f"{_inline_md(state_up)}."
                )
            except ConnectorError as exc:
                st.session_state.pop("op_packet_pl_result", None)
                st.error(f"Could not read the PL workbook: {exc.public_message}")
            except Exception:
                logger.exception("PL Services workbook parsing failed unexpectedly")
                st.session_state.pop("op_packet_pl_result", None)
                st.error("Could not read the PL workbook. Confirm it is an approved .xlsx export.")

    # Reuse a stored cross-reference only when the worksite, the service type, AND
    # the selected workbook (source label + synthetic flag) all still match, so a
    # swapped upload or a toggled example can never show a stale result.
    pl_stored = st.session_state.get("op_packet_pl_result")
    pl_matches = None
    if (
        pl_stored is not None
        and pl_stored.get("city") == worksite_city.strip().casefold()
        and pl_stored.get("state") == state_up
        and pl_stored.get("service_type") == pl_service_type.strip().casefold()
        and pl_stored.get("source") == pl_source_label
        and pl_stored.get("synthetic") == pl_synthetic
    ):
        pl_matches = pl_stored.get("result")

    st.divider()
    # Distinct wording from the packet's own rendered section header
    # (pl_activity.PL_ACTIVITY_HEADER, "## Procurement List activity
    # (Federal Register)") -- deliberately NOT that phrase, since a Markdown
    # "####" heading contains "##" as a leading substring and would
    # otherwise false-positive a "## Procurement List activity ... in
    # packet" containment check (mirrors the Staffing what-if intake/section
    # pair's own established avoidance of this collision above).
    st.markdown("#### Federal Register PL-notice pull")
    st.caption(
        "Optional. Pull the AbilityOne Commission's own Federal Register "
        "notice stream (page 1, newest-first, up to 20 notices) -- a cited "
        "national notice list, never a claim about this contract. An "
        "optional search term is a text search, not a relevance "
        "determination. This is the fourth of this packet page's four "
        "independent analyst-initiated live requests (contract facts, "
        "subaward records, ACS geography context, and Federal Register "
        "PL-notice activity); it fires only on its own explicit button and "
        "fails loud if the source is unavailable."
    )
    fr_term = st.text_input(
        "Search term (optional)",
        key="op_packet_fr_term",
        placeholder="Procurement List",
    )
    if st.button("Pull Procurement List activity (live)", key="op_packet_fr_pull"):
        try:
            fr_result = pull_pl_notices(fr_term.strip() or None)
            st.session_state["op_packet_fr_result"] = {
                # D6 (audit MAJOR): the canonical reuse-guard key is computed
                # IDENTICALLY here (the stored side, at pull time) and below
                # (the compare side, at render time) -- None/""/whitespace all
                # canonicalize to "" on BOTH sides, so a no-term pull never
                # attaches to a term-search render and vice versa.
                "term_key": (fr_term or "").strip().casefold(),
                "result": fr_result,
            }
            st.success(
                f"Attached {len(fr_result.records)} Federal Register "
                "notice(s)."
            )
        except ConnectorError as exc:
            st.session_state.pop("op_packet_fr_result", None)
            st.error(
                f"Could not retrieve Federal Register notices: {exc.public_message}"
            )
        except Exception:
            logger.exception("Federal Register notices pull failed unexpectedly")
            st.session_state.pop("op_packet_fr_result", None)
            st.error(
                "An unexpected internal error occurred while retrieving "
                "Federal Register notices; it has been logged."
            )

    # Reuse a stored pull only when its canonical term matches the CURRENT
    # search-term input's canonical term (D6) -- the same "blank canonicalizes
    # to no query" discipline the R2b service-type query already holds.
    fr_stored = st.session_state.get("op_packet_fr_result")
    pl_notices = None
    if (
        fr_stored is not None
        and fr_stored.get("term_key") == (fr_term or "").strip().casefold()
    ):
        pl_notices = fr_stored.get("result")

    # Resolved ONCE per render so the on-screen body's "As of" stamp and the
    # downloaded export's header stamp always agree (A7).
    packet_as_of = datetime.now(timezone.utc)
    packet = build_opportunity_packet_markdown(
        piid=piid,
        county=county,
        state=state,
        geography=geography,
        pl_matches=pl_matches,
        pl_notices=pl_notices,
        eligibility=eligibility,
        contract_facts=contract_facts,
        subawards=subawards,
        directory_agency_names=directory_agency_names,
        # The builder receives the ALREADY PIID-gated value (D9) -- a
        # mismatched handoff is never even passed in, so it cannot leak into
        # the on-screen render.
        radar_handoff=(handoff if handoff_piid_matched else None),
        staffing=staffing,
        as_of=packet_as_of,
    )
    st.markdown(packet)

    ledger = derive_section_ledger(
        eligibility=eligibility,
        contract_facts=contract_facts,
        geography=geography,
        pl_matches=pl_matches,
        subawards=subawards,
        directory_agency_names=directory_agency_names,
        handoff_attached=handoff is not None,
        handoff_piid_matched=handoff_piid_matched,
        staffing=staffing,
        pl_notices=pl_notices,
    )
    manifest = derive_source_manifest(
        contract_facts=contract_facts,
        subawards=subawards,
        geography=geography,
        pl_matches=pl_matches,
        directory_source_label=directory_source_label,
        set_aside_analyst_value=set_aside_value,
        handoff=handoff,
        handoff_source_label=handoff_source_label,
        handoff_piid_matched=handoff_piid_matched,
        staffing=staffing,
        pl_notices=pl_notices,
    )
    export_doc = assemble_packet_export(
        body_markdown=packet,
        piid=piid,
        county=county,
        state=state,
        ledger=ledger,
        manifest=manifest,
        as_of=packet_as_of,
    )
    st.caption(
        "The download adds a Section ledger (which sections are included, and "
        "the honest reason when one is not) and a Source manifest (every "
        "attached source's reference, retrieval time, and assurance) -- not "
        "shown on screen, only in the exported file."
    )
    st.download_button(
        "Export Opportunity Packet (Markdown)",
        data=export_doc,
        file_name=packet_export_filename(piid, packet_as_of),
        mime="text/markdown",
        key="op_packet_export",
    )


def render_public_bd_page(data: Any, target: float, scenario: str) -> None:
    """Render the governed public-evidence BD tracker."""

    del data, target, scenario
    st.markdown('<div class="page-kicker">Business Development / Public Evidence</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="page-title">Opportunity Packet & Public-Evidence Tracker</h1>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Turn an approved location into a repeatable evidence case: import, reconcile, review, resolve the route, and validate.</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="planning-banner">{_PUBLIC_BANNER}</div>', unsafe_allow_html=True)
    st.warning("Public directory evidence is discovery evidence only. The scanner never infers capacity, candidate supply, a relationship, or an acquisition outcome.")

    try:
        repo = _repository(_default_db_path())
    except Exception:
        st.error("The local evidence ledger could not be opened. Check the configured TENS_HQ_DB_PATH and filesystem permissions.")
        return

    packet_tab, cases_tab, new_tab, scan_tab, verify_tab, assess_tab = st.tabs(
        ["Opportunity Packet", "Cases", "New Case", "Scan & Evidence", "Verification", "Assessment"]
    )
    with packet_tab:
        _render_opportunity_packet()
    with cases_tab:
        _render_cases(repo)
    with new_tab:
        _render_new_case(repo)
    with scan_tab:
        _render_scan(repo)
    with verify_tab:
        _render_verification(repo)
    with assess_tab:
        _render_assessment(repo)
