from __future__ import annotations

import io
import sqlite3
from datetime import datetime, timedelta, timezone

from openpyxl import Workbook
import pytest

from tens_hq.case_store import CaseRepository, CaseStoreError
from tens_hq.cases import CaseState, CaseValidationError, ensure_transition
from tens_hq.connectors import SourceKind, parse_workbook
from tens_hq.scanner import ScanFailure, ScanStatus, WorkbookScanner


def _services_workbook() -> bytes:
    return _workbook(
        ["CNA", "Service Type", "Service Location", "Mandatory for Contracting Activity"],
        [["CNA A", "Janitorial", "Denver, CO 80202", "Yes"]],
    )


def _drive_case_to_validated(
    repository: CaseRepository,
    *,
    title: str = "Denver validated",
    retrieved_at: datetime | None = None,
    clock=None,
):
    """Drive a case through the full evidence workflow to ``Validated``.

    A fresh attested ``retrieved_at`` is always supplied so the case satisfies
    the source-time freshness gate regardless of which trust fix is in force.
    """

    when = retrieved_at or (clock() if clock is not None else datetime.now(timezone.utc))
    case = repository.create_case(title, "Denver", "CO")
    scanner = WorkbookScanner(repository, clock=clock) if clock is not None else WorkbookScanner(repository)
    scanner.run_scan(
        case.case_id, SourceKind.NIB_NPA, _nib([["Agency A", "Denver", "CO", "80202"]]), "nib.xlsx", retrieved_at=when
    )
    npa = repository.list_resources(case.case_id, source_kind=SourceKind.NIB_NPA.value, current_only=True)[0]
    repository.update_resource_review(npa.resource_id, "verified", review_note="Location and source row checked")
    scanner.run_scan(
        case.case_id, SourceKind.ABILITYONE_SERVICES, _services_workbook(), "services.xlsx", retrieved_at=when
    )
    svc = repository.list_resources(case.case_id, source_kind=SourceKind.ABILITYONE_SERVICES.value, current_only=True)[0]
    repository.update_resource_review(svc.resource_id, "verified", review_note="Service location checked")
    hypothesis = repository.add_route_hypothesis(case.case_id, "ABILITYONE_CONFIRMED", "Official Procurement List review")
    repository.resolve_route(
        hypothesis.hypothesis_id, "resolved", rationale="Analyst confirmed route for follow-up", source_label="AbilityOne Procurement List"
    )
    validated = repository.validate_case(case.case_id)
    assert validated.state is CaseState.VALIDATED
    return validated


def _workbook(headers: list[str], rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _nib(rows: list[list[object]]) -> bytes:
    return _workbook(["Nonprofit Agency Name", "City", "State", "Zip Code"], rows)


def test_scan_persists_evidence_and_requires_explicit_validation(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "tracker.sqlite3")
    try:
        # A fresh attested retrieval time is part of the readiness contract:
        # without it the source-time freshness gate keeps the case unvalidated.
        when = datetime.now(timezone.utc)
        case = repository.create_case("Denver review", "Denver", "CO", "80202")
        result = WorkbookScanner(repository).run_scan(
            case.case_id,
            SourceKind.NIB_NPA,
            _nib([["Agency A", "Denver", "CO", "80202"]]),
            "nib.xlsx",
            retrieved_at=when,
        )

        assert result.status is ScanStatus.SUCCEEDED
        assert repository.require_case(case.case_id).state is CaseState.NEEDS_VERIFICATION
        resource = repository.list_resources(case.case_id, current_only=True)[0]
        assert resource.payload["agency_name"] == "Agency A"
        assert repository.list_observations(case_id=case.case_id, current_only=True)
        snapshot = repository.list_snapshots(case.case_id, source_kind=SourceKind.NIB_NPA.value)[0]
        assert snapshot.assurance == "USER_ATTESTED"
        assert snapshot.source_version == "abilityone-xlsx-v1"
        assert snapshot.source_uri == "https://plims.abilityone.gov/reports/"
        assert snapshot.byte_size and snapshot.byte_size > 0
        assert snapshot.payload_retained is False
        assert snapshot.retrieved_at == when.isoformat()

        repository.update_resource_review(resource.resource_id, "verified", review_note="Location and source row checked")
        services = _workbook(
            ["CNA", "Service Type", "Service Location", "Mandatory for Contracting Activity"],
            [["CNA A", "Janitorial", "Denver, CO 80202", "Yes"]],
        )
        WorkbookScanner(repository).run_scan(case.case_id, SourceKind.ABILITYONE_SERVICES, services, "services.xlsx", retrieved_at=when)
        service_resource = repository.list_resources(case.case_id, source_kind=SourceKind.ABILITYONE_SERVICES.value, current_only=True)[0]
        repository.update_resource_review(service_resource.resource_id, "verified", review_note="Service location checked")
        hypothesis = repository.add_route_hypothesis(
            case.case_id,
            "ABILITYONE_CONFIRMED",
            "Official Procurement List review",
        )
        repository.resolve_route(hypothesis.hypothesis_id, "resolved", rationale="Analyst confirmed route for follow-up", source_label="AbilityOne Procurement List")
        assert repository.compute_readiness(case.case_id).ready
        validated = repository.validate_case(case.case_id)
        assert validated.state is CaseState.VALIDATED
        assert any(event.event_type == "case_validated" for event in repository.list_events(case.case_id))
    finally:
        repository.close()


def test_failed_newer_scan_preserves_rows_and_blocks_until_retry(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "tracker.sqlite3")
    try:
        case = repository.create_case("Denver review", "Denver", "CO")
        good = _nib([["Agency A", "Denver", "CO", "80202"]])
        assert WorkbookScanner(repository).run_scan(case.case_id, SourceKind.NIB_NPA, good, "nib.xlsx").ok

        failed = WorkbookScanner(repository).run_scan(case.case_id, SourceKind.NIB_NPA, b"not an xlsx", "nib.xlsx")
        assert failed.status is ScanStatus.FAILED
        assert len(repository.list_resources(case.case_id, current_only=True)) == 1
        open_failures = repository.list_tasks(case.case_id, open_only=True)
        assert any(task.task_type == "SCAN_FAILED" for task in open_failures)

        retried = WorkbookScanner(repository).run_scan(case.case_id, SourceKind.NIB_NPA, good, "nib.xlsx")
        assert retried.status is ScanStatus.SUCCEEDED
        assert not any(task.task_type == "SCAN_FAILED" and task.status.value == "open" for task in repository.list_tasks(case.case_id))
    finally:
        repository.close()


def test_partial_service_scan_keeps_unparsed_row_and_opens_blocker(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "tracker.sqlite3")
    try:
        case = repository.create_case("Denver services", "Denver", "CO")
        services = _workbook(
            ["CNA", "Service Type", "Service Location", "Mandatory for Contracting Activity"],
            [["CNA A", "Janitorial", "Denver, CO 80202", "Yes"], ["CNA B", "Other", "unknown", "No"]],
        )
        result = WorkbookScanner(repository).run_scan(case.case_id, SourceKind.ABILITYONE_SERVICES, services, "services.xlsx")
        assert result.status is ScanStatus.PARTIAL
        assert result.unparsed_rows == 1
        # The malformed/unparsed row is quarantined; the latest partial
        # snapshot defines current evidence and therefore does not carry
        # forward omitted prior rows as current.
        assert len(repository.list_resources(case.case_id, current_only=True)) == 1
        partial_tasks = [task for task in repository.list_tasks(case.case_id, open_only=True) if task.task_type == "SCAN_PARTIAL"]
        assert len(partial_tasks) == 1
        assert partial_tasks[0].severity.value == "blocking"
        assert repository.list_scans(case.case_id, status="partial")[0].status == "partial"
    finally:
        repository.close()


def test_partial_scan_surfaces_disappearance_without_deactivating_prior_row(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "partial-reconcile.sqlite3")
    try:
        case = repository.create_case("Denver partial", "Denver", "CO")
        first = _nib([["Agency A", "Denver", "CO", "80202"], ["Agency B", "Denver", "CO", "80203"]])
        assert WorkbookScanner(repository).run_scan(case.case_id, SourceKind.NIB_NPA, first, "first.xlsx").status is ScanStatus.SUCCEEDED
        second = _nib([["Agency A", "Denver", "CO", "80202"], [None, "Denver", "CO", "80203"]])
        result = WorkbookScanner(repository).run_scan(case.case_id, SourceKind.NIB_NPA, second, "partial.xlsx")
        assert result.status is ScanStatus.PARTIAL
        assert {item.payload["agency_name"] for item in repository.list_resources(case.case_id, current_only=True)} == {"Agency A"}
        tasks = repository.list_tasks(case.case_id, open_only=True)
        assert any(task.task_type == "SOURCE_RECORD_DISAPPEARED" for task in tasks)
    finally:
        repository.close()


def test_excluded_rows_are_durable_quarantine_metadata(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "exclusions.sqlite3")
    try:
        case = repository.create_case("Denver exclusions", "Denver", "CO")
        result = WorkbookScanner(repository).run_scan(
            case.case_id,
            SourceKind.NIB_NPA,
            _nib([["Agency A", "Aurora", "CO", "80012"]]),
            "national.xlsx",
        )
        assert result.record_count == 0
        exclusions = repository.list_exclusions(case.case_id)
        assert len(exclusions) == 1
        assert exclusions[0]["reason"] == "SOURCE_LOCATION_MISMATCH"
        assert exclusions[0]["payload"]["agency_name"] == "Agency A"
    finally:
        repository.close()


def test_state_identifiable_unparsed_service_is_broad_candidate_not_local_proof(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "broad-service.sqlite3")
    try:
        case = repository.create_case("Denver broad service", "Denver", "CO")
        services = _workbook(
            ["CNA", "Service Type", "Service Location", "Mandatory for Contracting Activity"],
            [["CNA statewide", "Janitorial", "CO (statewide)", "No"]],
        )
        result = WorkbookScanner(repository).run_scan(case.case_id, SourceKind.ABILITYONE_SERVICES, services, "services.xlsx")
        assert result.status is ScanStatus.PARTIAL
        resources = repository.list_resources(case.case_id, source_kind=SourceKind.ABILITYONE_SERVICES.value, current_only=True)
        assert len(resources) == 1
        assert resources[0].payload["location_parse_status"] == "UNPARSED"
        assert repository.compute_readiness(case.case_id).ready is False
    finally:
        repository.close()


def test_connector_rejects_unknown_projection_columns() -> None:
    workbook = _workbook(
        ["Nonprofit Agency Name", "City", "State", "Zip Code", "Private Notes"],
        [["Agency A", "Denver", "CO", "80202", "should not be accepted"]],
    )
    try:
        parse_workbook(SourceKind.NIB_NPA, workbook)
    except Exception as error:
        assert getattr(error, "code", None) == "HEADER_NOT_FOUND"
    else:  # pragma: no cover - assertion makes the fail-closed contract clear
        raise AssertionError("unknown source columns must fail closed")


def test_scan_scopes_national_directory_to_exact_case_location(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "scope.sqlite3")
    try:
        case = repository.create_case("Denver scope", "Denver", "CO", "80202")
        workbook = _nib(
            [
                ["Agency A", "Denver", "CO", "80202"],
                ["Agency B", "Aurora", "CO", "80012"],
                ["Agency C", "Denver", "CA", "90210"],
            ]
        )
        result = WorkbookScanner(repository).run_scan(case.case_id, SourceKind.NIB_NPA, workbook, "national.xlsx")
        assert result.status is ScanStatus.SUCCEEDED
        assert result.record_count == 1
        current = repository.list_resources(case.case_id, current_only=True)
        assert [item.payload["agency_name"] for item in current] == ["Agency A"]
        mismatch = [task for task in repository.list_tasks(case.case_id, open_only=True) if task.task_type == "SOURCE_LOCATION_MISMATCH"]
        assert len(mismatch) == 1
        assert mismatch[0].details["excluded_row_count"] == 2
        assert mismatch[0].severity.value == "advisory"
    finally:
        repository.close()


def test_idempotency_is_case_scoped_and_failed_keys_can_retry(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "idempotency.sqlite3")
    try:
        first = repository.create_case("First", "Denver", "CO")
        second = repository.create_case("Second", "Denver", "CO")
        workbook = _nib([["Agency A", "Denver", "CO", "80202"]])
        scanner = WorkbookScanner(repository)
        initial = scanner.run_scan(first.case_id, SourceKind.NIB_NPA, workbook, "original.xlsx", idempotency_key="same-key")
        replay = scanner.run_scan(first.case_id, SourceKind.NIB_NPA, workbook, "renamed.xlsx", idempotency_key="same-key")
        assert initial.status is ScanStatus.SUCCEEDED
        assert replay.status is ScanStatus.IDEMPOTENT_REPLAY
        assert len(repository.list_scans(first.case_id)) == 1

        failed = scanner.run_scan(first.case_id, SourceKind.NIB_NPA, b"not xlsx", "bad.xlsx", idempotency_key="retry-key")
        retried = scanner.run_scan(first.case_id, SourceKind.NIB_NPA, workbook, "good.xlsx", idempotency_key="retry-key")
        assert failed.status is ScanStatus.FAILED
        assert retried.status is ScanStatus.SUCCEEDED

        other_case = WorkbookScanner(repository).run_scan(second.case_id, SourceKind.NIB_NPA, workbook, "second.xlsx", idempotency_key="same-key")
        assert other_case.status is ScanStatus.SUCCEEDED
    finally:
        repository.close()


def test_idempotency_key_rejects_payload_conflict_and_replay_uses_persisted_metadata(tmp_path) -> None:
    base = datetime(2026, 7, 18, 14, 0, tzinfo=timezone.utc)
    repository = CaseRepository(tmp_path / "idempotency-provenance.sqlite3", clock=lambda: base)
    try:
        case = repository.create_case("Denver provenance", "Denver", "CO")
        first_time = "2026-07-18T12:00:00Z"
        first = _nib([["Agency A", "Denver", "CO", "80202"]])
        second = _nib([["Agency B", "Denver", "CO", "80202"]])
        scanner = WorkbookScanner(repository, clock=lambda: base)
        original = scanner.run_scan(case.case_id, SourceKind.NIB_NPA, first, "original.xlsx", idempotency_key="bound-key", retrieved_at=first_time)
        replay = scanner.run_scan(case.case_id, SourceKind.NIB_NPA, first, "renamed.xlsx", idempotency_key="bound-key", retrieved_at="2026-07-18T13:00:00Z")
        assert replay.status is ScanStatus.IDEMPOTENT_REPLAY
        assert replay.metadata["workbook_sha256"] == original.metadata["workbook_sha256"]
        assert replay.metadata["source_label"] == "original.xlsx"
        assert replay.retrieved_at == original.retrieved_at
        conflict = scanner.run_scan(case.case_id, SourceKind.NIB_NPA, second, "different.xlsx", idempotency_key="bound-key", retrieved_at=first_time)
        assert conflict.status is ScanStatus.FAILED
        assert conflict.error_code == "IDEMPOTENCY"
        assert len(repository.list_scans(case.case_id)) == 1
    finally:
        repository.close()


def test_successful_idempotency_receipt_replays_after_newer_source_scan(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "idempotency-receipt.sqlite3")
    try:
        case = repository.create_case("Denver receipt", "Denver", "CO")
        scanner = WorkbookScanner(repository)
        first = _nib([["Agency A", "Denver", "CO", "80202"]])
        expanded = _nib([["Agency A", "Denver", "CO", "80202"], ["Agency B", "Denver", "CO", "80203"]])
        initial = scanner.run_scan(case.case_id, SourceKind.NIB_NPA, first, "a.xlsx", idempotency_key="receipt-key")
        newer = scanner.run_scan(case.case_id, SourceKind.NIB_NPA, expanded, "b.xlsx", idempotency_key="new-key")
        replay = scanner.run_scan(case.case_id, SourceKind.NIB_NPA, first, "renamed-a.xlsx", idempotency_key="receipt-key")
        assert initial.status is ScanStatus.SUCCEEDED
        assert newer.status is ScanStatus.SUCCEEDED
        assert replay.status is ScanStatus.IDEMPOTENT_REPLAY
        assert replay.run_id == initial.run_id
        assert len(repository.list_scans(case.case_id)) == 2
        assert {item.payload["agency_name"] for item in repository.list_resources(case.case_id, current_only=True)} == {"Agency A", "Agency B"}
    finally:
        repository.close()


def test_failed_rescan_never_restores_validated_state(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "failure-state.sqlite3")
    try:
        when = datetime.now(timezone.utc)
        case = repository.create_case("Denver review", "Denver", "CO")
        good = _nib([["Agency A", "Denver", "CO", "80202"]])
        WorkbookScanner(repository).run_scan(case.case_id, SourceKind.NIB_NPA, good, "nib.xlsx", retrieved_at=when)
        repository.update_resource_review(repository.list_resources(case.case_id, current_only=True)[0].resource_id, "verified")
        services = _workbook(
            ["CNA", "Service Type", "Service Location", "Mandatory for Contracting Activity"],
            [["CNA A", "Janitorial", "Denver, CO", "Yes"]],
        )
        WorkbookScanner(repository).run_scan(case.case_id, SourceKind.ABILITYONE_SERVICES, services, "services.xlsx", retrieved_at=when)
        repository.update_resource_review(repository.list_resources(case.case_id, source_kind=SourceKind.ABILITYONE_SERVICES.value, current_only=True)[0].resource_id, "verified")
        route = repository.add_route_hypothesis(case.case_id, "ABILITYONE_CONFIRMED", "Official Procurement List")
        repository.resolve_route(route.hypothesis_id, "resolved", rationale="Official source reviewed", source_label="AbilityOne Procurement List")
        assert repository.validate_case(case.case_id).state is CaseState.VALIDATED
        failed = WorkbookScanner(repository).run_scan(case.case_id, SourceKind.NIB_NPA, b"not xlsx", "nib.xlsx")
        assert failed.status is ScanStatus.FAILED
        assert repository.require_case(case.case_id).state is CaseState.NEEDS_VERIFICATION
    finally:
        repository.close()


def test_future_retrieval_time_is_rejected(tmp_path) -> None:
    base = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    repository = CaseRepository(tmp_path / "future-retrieval.sqlite3", clock=lambda: base)
    try:
        case = repository.create_case("Denver future", "Denver", "CO")
        with pytest.raises(ScanFailure) as error:
            WorkbookScanner(repository, clock=lambda: base).run_scan(
                case.case_id,
                SourceKind.NIB_NPA,
                _nib([["Agency A", "Denver", "CO", "80202"]]),
                "future.xlsx",
                retrieved_at="2099-01-01T00:00:00Z",
            )
        assert error.value.code == "INVALID_INPUT"
        assert repository.list_scans(case.case_id) == []
    finally:
        repository.close()


def test_pre_v2_ledger_fails_closed_before_index_ddl(tmp_path) -> None:
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);"
        "INSERT INTO schema_meta VALUES ('schema_version','1','2026-01-01T00:00:00+00:00');"
        "CREATE TABLE scan_runs(scan_id TEXT PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('running','succeeded','partial','failed')));"
    )
    connection.close()
    with pytest.raises(CaseStoreError):
        CaseRepository(path)


def test_restart_recovery_leaves_recent_running_scan_alone(tmp_path) -> None:
    base = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    repository = CaseRepository(tmp_path / "recovery.sqlite3", clock=lambda: base)
    case = repository.create_case("Denver recovery", "Denver", "CO")
    run = repository.start_scan(case.case_id, SourceKind.NIB_NPA.value, "nib.xlsx")
    assert repository.recover_interrupted_scans() == []
    repository.close()
    later = CaseRepository(tmp_path / "recovery.sqlite3", clock=lambda: base + timedelta(minutes=16))
    try:
        recovered = later.recover_interrupted_scans()
        assert len(recovered) == 1
        assert recovered[0].scan_id == run.scan_id
        assert recovered[0].status == "failed"
    finally:
        later.close()


def test_custom_readiness_rows_cannot_replace_core_gates(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "readiness.sqlite3")
    try:
        case = repository.create_case("Denver core gates", "Denver", "CO")
        repository.upsert_readiness_item(case.case_id, "custom_note", "Custom note", "verified", blocking=True)
        assessment = repository.compute_readiness(case.case_id)
        keys = {item.key for item in assessment.items}
        assert {"case_location", "current_import", "route_resolution", "geographic_relevance", "service_relevance", "custom_note"} <= keys
        assert not assessment.ready
        assert repository.validate_case(case.case_id).state is CaseState.NEEDS_VERIFICATION
    finally:
        repository.close()


def test_case_captures_public_requirement_metadata(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "requirements.sqlite3")
    try:
        case = repository.create_case(
            title="Denver contract",
            city="Denver",
            state="CO",
            contract_type="Janitorial services",
            service_type="Custodial",
            target_headcount=12,
            target_start_date="2027-01-15",
            job_family_requirements=("Custodian", "Lead",
            ),
        )
        loaded = repository.require_case(case.case_id)
        assert loaded.contract_type == "Janitorial services"
        assert loaded.service_type == "Custodial"
        assert loaded.target_headcount == 12
        assert loaded.target_start_date == "2027-01-15"
        assert loaded.job_family_requirements == ("Custodian", "Lead")
    finally:
        repository.close()


def test_case_cannot_close_without_passing_validation(tmp_path) -> None:
    # A case must never reach the terminal Closed state while skipping the
    # validation gate.  Premature Draft->Closed and NeedsVerification->Closed
    # are rejected by the transition graph; only a currently-Validated case may
    # close.  Otherwise the historical trail would show a case "closed" while
    # its evidence gates were still open.
    with pytest.raises(CaseValidationError):
        ensure_transition(CaseState.DRAFT, CaseState.CLOSED)
    with pytest.raises(CaseValidationError):
        ensure_transition(CaseState.NEEDS_VERIFICATION, CaseState.CLOSED)
    # The legitimate close edge from Validated is preserved.
    assert ensure_transition(CaseState.VALIDATED, CaseState.CLOSED) == (CaseState.VALIDATED, CaseState.CLOSED)

    repository = CaseRepository(tmp_path / "closure.sqlite3")
    try:
        case = repository.create_case("Denver closure", "Denver", "CO")
        with pytest.raises(CaseValidationError):
            repository.close_case(case.case_id, reason="created by mistake")
        assert repository.require_case(case.case_id).state is CaseState.DRAFT
    finally:
        repository.close()


def test_validated_case_closes_only_with_an_explicit_reason(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "closure-reason.sqlite3")
    try:
        validated = _drive_case_to_validated(repository, title="Denver closeable")
        # A blank reason is rejected: closure must carry an auditable rationale.
        with pytest.raises(CaseValidationError):
            repository.close_case(validated.case_id, reason="   ")
        assert repository.require_case(validated.case_id).state is CaseState.VALIDATED

        closed = repository.close_case(validated.case_id, reason="Pursuit declined after review")
        assert closed.state is CaseState.CLOSED
        assert closed.closed_at is not None
        close_events = [event for event in repository.list_events(validated.case_id) if event.event_type == "case_closed"]
        assert len(close_events) == 1
        assert close_events[0].detail.get("reason") == "Pursuit declined after review"
    finally:
        repository.close()


def test_get_case_is_read_only_and_does_not_mutate(tmp_path) -> None:
    # A read must never write.  get_case previously demoted a stale Validated
    # case and bumped its optimistic version from inside a read; that state
    # change now belongs to an explicit reconciliation command.
    clock = {"t": datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)}
    repository = CaseRepository(tmp_path / "readonly.sqlite3", clock=lambda: clock["t"])
    try:
        validated = _drive_case_to_validated(repository, retrieved_at=clock["t"], clock=lambda: clock["t"])
        # Advance the clock far past any freshness budget so the persisted
        # Validated case is now stale purely due to time; no write occurred.
        clock["t"] = clock["t"] + timedelta(days=400)

        first = repository.get_case(validated.case_id)
        second = repository.get_case(validated.case_id)
        assert first.state is CaseState.VALIDATED
        assert second.state is CaseState.VALIDATED
        # Repeated reads never bump the optimistic version and never emit an
        # invalidation event.
        assert first.version == second.version == validated.version
        assert not any(
            event.event_type == "validation_invalidated" for event in repository.list_events(validated.case_id)
        )

        # The explicit reconciliation command performs the demotion a read used
        # to smuggle in.
        reconciled = repository.reconcile_case_validation(validated.case_id)
        assert reconciled.state is CaseState.NEEDS_VERIFICATION
        assert any(
            event.event_type == "validation_invalidated" for event in repository.list_events(validated.case_id)
        )
    finally:
        repository.close()


def test_reconcile_validations_demotes_stale_case_via_startup_command(tmp_path) -> None:
    # FIX 2: get_case is a pure read, so a Validated case whose evidence goes
    # stale is demoted only by the explicit reconcile_validations() command the
    # app runs at startup -- never by a passive read.  This pins the chosen
    # path and proves get_case stays side-effect free.
    clock = {"t": datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)}
    repository = CaseRepository(tmp_path / "reconcile-all.sqlite3", clock=lambda: clock["t"])
    try:
        validated = _drive_case_to_validated(repository, retrieved_at=clock["t"], clock=lambda: clock["t"])
        # Time passes past every source freshness budget with no intervening
        # write: the persisted state is still 'Validated' but no longer holds.
        clock["t"] = clock["t"] + timedelta(days=400)

        # A plain read never writes: the stale case still reads Validated and
        # its version/events are unchanged.
        before = repository.get_case(validated.case_id)
        assert before.state is CaseState.VALIDATED
        assert before.version == validated.version
        assert not any(
            event.event_type == "validation_invalidated" for event in repository.list_events(validated.case_id)
        )

        # The startup command demotes it and reports it in the demoted list.
        demoted = repository.reconcile_validations()
        assert [case.case_id for case in demoted] == [validated.case_id]

        # After this explicit reconcile command persists the demotion, a plain
        # read reflects the true state.  (A read never triggers this on its own;
        # a case that goes stale later during uptime keeps a stale 'Validated'
        # row until a write, which is why the UI also derives the DISPLAYED state
        # live -- see test_stale_validated_case_displays_as_needs_verification.)
        after = repository.get_case(validated.case_id)
        assert after.state is CaseState.NEEDS_VERIFICATION
        assert any(
            event.event_type == "validation_invalidated" for event in repository.list_events(validated.case_id)
        )
    finally:
        repository.close()


def test_bd_page_repository_reconciles_stale_validation_at_startup(tmp_path) -> None:
    # FIX 2 wiring: reconcile_validations() must have a production caller.  The
    # BD page builds its repository once per session; that startup path persists
    # the demotion for any case that is ALREADY stale when the process boots, so
    # such a case does not reopen reading a stale 'Validated'.  This startup pass
    # runs once and does NOT by itself keep the live UI accurate for a case that
    # ages during uptime -- that is covered by the render-time display derivation
    # (test_stale_validated_case_displays_as_needs_verification_without_restart).
    from tens_hq import bd_page

    db_path = tmp_path / "bd-startup.sqlite3"
    # Seed a case validated while fresh under a fixed clock far in the past, so a
    # real-time reopen is well beyond every source freshness budget regardless
    # of when the test runs.
    seed_clock = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)
    seed = CaseRepository(db_path, clock=lambda: seed_clock)
    try:
        validated = _drive_case_to_validated(seed, retrieved_at=seed_clock, clock=lambda: seed_clock)
        assert validated.state is CaseState.VALIDATED
    finally:
        seed.close()

    # The page's startup repository (default real-time clock) reopens the same
    # ledger and reconciles on open.
    bd_page._repository.clear()
    repo = bd_page._repository(str(db_path))
    try:
        reopened = repo.get_case(validated.case_id)
        assert reopened.state is CaseState.NEEDS_VERIFICATION
    finally:
        repo.close()
        bd_page._repository.clear()


def test_stale_validated_case_displays_as_needs_verification_without_restart(tmp_path) -> None:
    # DISPLAY ACCURACY (read-only): a case that is Validated + fresh at process
    # start but whose evidence ages past its freshness budget DURING uptime --
    # no restart, no cache clear, no intervening write -- must not render as a
    # current 'Validated'.  The startup reconcile only persists demotions known
    # when the server booted; it cannot re-run for a case that goes stale later
    # while the single cached repository stays live.  So the Cases table and the
    # case selector derive the DISPLAYED state live from the same freshness view
    # compute_readiness uses -- a pure read that never writes.
    from tens_hq import bd_page

    clock = {"t": datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)}
    repository = CaseRepository(tmp_path / "display-stale.sqlite3", clock=lambda: clock["t"])
    try:
        validated = _drive_case_to_validated(
            repository, title="Denver market review", retrieved_at=clock["t"], clock=lambda: clock["t"]
        )
        # Same process, same repository object (mirrors @st.cache_resource holding
        # one repo for the server's lifetime): only the wall clock advances.
        clock["t"] = clock["t"] + timedelta(days=400)

        # The persisted row is deliberately still 'Validated' -- no reconcile
        # command has run since it went stale, and a pure read must not write.
        assert repository.get_case(validated.case_id).state is CaseState.VALIDATED

        # ...but the derived display state is Needs Verification.
        assert repository.displayed_state(validated) is CaseState.NEEDS_VERIFICATION

        # The Cases table shows the derived state, not the stale 'Validated'.
        frame = bd_page._cases_frame(repository, repository.list_cases())
        state_cell = frame.loc[frame["case_id"] == validated.case_id, "state"].iloc[0]
        assert state_cell == CaseState.NEEDS_VERIFICATION.value
        assert state_cell != CaseState.VALIDATED.value

        # The case selector label shows the derived state too.
        label = bd_page._case_label(repository, repository.get_case(validated.case_id))
        assert CaseState.NEEDS_VERIFICATION.value in label
        assert CaseState.VALIDATED.value not in label

        # Deriving the display state is a pure read: it never bumps the optimistic
        # version and never emits an invalidation event (persisting the demotion
        # remains the reconcile command's job).
        assert repository.get_case(validated.case_id).version == validated.version
        assert not any(
            event.event_type == "validation_invalidated"
            for event in repository.list_events(validated.case_id)
        )
    finally:
        repository.close()


def test_close_case_rejects_stale_persisted_validation(tmp_path) -> None:
    # TRANSITION CORRECTNESS: a case persisted as 'Validated' whose evidence has
    # aged past its freshness budget during uptime -- with no restart and no
    # reconcile since -- must not be closeable as if still validated.  close_case
    # reconciles the specific case inside the command path before the transition
    # check (close is already a write, so this is a command action, not
    # write-on-read); the demotion to Needs Verification is persisted and the
    # transition graph then refuses to close it.
    clock = {"t": datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)}
    repository = CaseRepository(tmp_path / "close-stale.sqlite3", clock=lambda: clock["t"])
    try:
        validated = _drive_case_to_validated(
            repository, title="Denver closeable stale", retrieved_at=clock["t"], clock=lambda: clock["t"]
        )
        clock["t"] = clock["t"] + timedelta(days=400)
        # No reconcile has run: the row is still persisted 'Validated'.
        assert repository.get_case(validated.case_id).state is CaseState.VALIDATED

        # The close is rejected -- a stale-but-persisted-Validated case cannot
        # close as validated.
        with pytest.raises(CaseValidationError):
            repository.close_case(validated.case_id, reason="Pursuit declined after review")

        # It was reconciled (demotion persisted), not closed.
        after = repository.get_case(validated.case_id)
        assert after.state is CaseState.NEEDS_VERIFICATION
        assert after.closed_at is None
        assert not any(
            event.event_type == "case_closed" for event in repository.list_events(validated.case_id)
        )
    finally:
        repository.close()


def test_old_workbook_uploaded_today_is_not_fresh(tmp_path) -> None:
    # Freshness must be measured from the analyst-attested source retrieval
    # time, not the system import time.  A two-year-old workbook imported today
    # is NOT fresh even though its import just finished.
    now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    repository = CaseRepository(tmp_path / "stale-source.sqlite3", clock=lambda: now)
    try:
        case = repository.create_case("Denver stale source", "Denver", "CO")
        old_retrieval = now - timedelta(days=730)
        result = WorkbookScanner(repository, clock=lambda: now).run_scan(
            case.case_id,
            SourceKind.NIB_NPA,
            _nib([["Agency A", "Denver", "CO", "80202"]]),
            "old.xlsx",
            retrieved_at=old_retrieval,
        )
        assert result.status is ScanStatus.SUCCEEDED
        assessment = repository.compute_readiness(case.case_id)
        states = {item.key: item.state.value for item in assessment.items}
        assert states["current_import"] == "needs_verification"
        assert not assessment.ready
    finally:
        repository.close()


def test_unknown_retrieval_time_is_not_fresh(tmp_path) -> None:
    # A missing (unknown) retrieval time must NOT count as fresh; the readiness
    # matrix must fall to needs_verification rather than silently passing on
    # system import time.
    now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    repository = CaseRepository(tmp_path / "unknown-retrieval.sqlite3", clock=lambda: now)
    try:
        case = repository.create_case("Denver unknown retrieval", "Denver", "CO")
        # No retrieved_at supplied: the attested retrieval time is unknown.
        WorkbookScanner(repository, clock=lambda: now).run_scan(
            case.case_id,
            SourceKind.NIB_NPA,
            _nib([["Agency A", "Denver", "CO", "80202"]]),
            "unknown.xlsx",
        )
        snapshot = repository.list_snapshots(case.case_id, source_kind=SourceKind.NIB_NPA.value)[0]
        assert snapshot.retrieved_at is None
        assessment = repository.compute_readiness(case.case_id)
        states = {item.key: item.state.value for item in assessment.items}
        assert states["current_import"] == "needs_verification"
        assert not assessment.ready
    finally:
        repository.close()


def test_service_review_does_not_substitute_for_geographic_review(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "separate-review.sqlite3")
    try:
        when = datetime.now(timezone.utc)
        case = repository.create_case("Denver services only", "Denver", "CO")
        services = _workbook(
            ["CNA", "Service Type", "Service Location", "Mandatory for Contracting Activity"],
            [["CNA A", "Janitorial", "Denver, CO", "Yes"]],
        )
        WorkbookScanner(repository).run_scan(case.case_id, SourceKind.ABILITYONE_SERVICES, services, "services.xlsx", retrieved_at=when)
        resource = repository.list_resources(case.case_id, current_only=True)[0]
        repository.update_resource_review(resource.resource_id, "verified", review_note="Service row checked")
        assessment = repository.compute_readiness(case.case_id)
        states = {item.key: item.state.value for item in assessment.items}
        assert states["service_relevance"] == "verified"
        assert states["geographic_relevance"] != "verified"
    finally:
        repository.close()


def test_cases_frame_leads_with_title_and_drops_internal_columns(tmp_path) -> None:
    # §6.2: the Cases table's default developer-table feel (leading raw
    # UUID, internal `version`) undersells the product. Human-readable
    # fields lead; the raw case_id is available but last, not first/widest;
    # `version` (an internal optimistic-concurrency detail) is dropped.
    from tens_hq.bd_page import _cases_frame

    repository = CaseRepository(tmp_path / "cases-frame.sqlite3")
    try:
        case = repository.create_case(
            "Denver review",
            "Denver",
            "CO",
            "80202",
            contract_type="IDIQ",
            service_type="Custodial",
            target_headcount=12,
            target_start_date="2027-01-01",
            job_family_requirements=("Custodial",),
        )
        frame = _cases_frame(repository, [case])
        columns = list(frame.columns)
        assert "version" not in columns
        assert columns[0] == "title"
        assert columns.index("case_id") == len(columns) - 1
        assert columns[:5] == ["title", "location", "state", "team", "role"]
        # `state` still carries the live freshness-derived display state, not
        # the persisted value -- unchanged semantics, just reordered.
        assert frame.iloc[0]["state"] == repository.displayed_state(case).value
    finally:
        repository.close()


def test_cases_frame_drops_all_empty_optional_columns(tmp_path) -> None:
    from tens_hq.bd_page import _cases_frame

    repository = CaseRepository(tmp_path / "cases-frame-empty.sqlite3")
    try:
        case = repository.create_case("Denver review", "Denver", "CO")
        frame = _cases_frame(repository, [case])
        columns = list(frame.columns)
        for optional in ("contract", "service", "headcount", "start", "job families"):
            assert optional not in columns
        assert columns == ["title", "location", "state", "team", "role", "case_id"]
    finally:
        repository.close()


def test_bundled_sample_nib_npa_workbook_parses_offline() -> None:
    # ADR-026 / §15-#6 / §5.4: the bundled data/samples/sample_nib_npa.xlsx must
    # satisfy the real NIB_NPA schema so a stranger can drive the tracker's
    # Scan -> Validated readiness lifecycle offline. This is the primary proof
    # -- it parses the actual committed artifact, not an in-test fixture.
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "data" / "samples" / "sample_nib_npa.xlsx"
    data = path.read_bytes()
    result = parse_workbook(SourceKind.NIB_NPA, data)

    assert result.record_count == 3
    assert result.rejected_rows == 0
    assert result.unparsed_rows == 0
    values = [dict(record.values) for record in result.records]
    assert {
        "agency_name": "Mile High Community Workshop",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80202",
    } in values
    assert {
        "agency_name": "Front Range Ability Partners",
        "city": "Denver",
        "state": "CO",
        "zip_code": "80204",
    } in values
    assert {
        "agency_name": "Rocky Mountain Vocational Services",
        "city": "Aurora",
        "state": "CO",
        "zip_code": "80010",
    } in values
