from pathlib import Path

from jarvis.model_routing.eligibility import TargetHealthEligibility
from jarvis.model_routing.health import TargetHealthRecord
from jarvis.model_routing.models import (
    EligibilitySnapshot,
    EvidenceSizeClass,
    LocalityRequirement,
    PrivacyClass,
    ResponseContractResult,
    RoutingAttempt,
    RoutingAttemptKind,
    RoutingDecision,
    RoutingOutcome,
    RoutingRequest,
)
from jarvis.model_routing.status import RoutingStatusReader, VerificationStatus
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.store import SQLiteWorkStore


def _fixture(tmp_path: Path):
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite")
    routing_store = ModelRoutingStore(work_store)
    work = WorkItem(
        request="Inspect a bounded routing status",
        work_type=WorkType.DIAGNOSTICS,
        source_session_id="session-status",
        source_turn_id="turn-status",
    )
    work_store.create(work)
    request = RoutingRequest(
        routing_request_id="routing-status-1",
        work_id=work.work_id,
        change_id="change-42",
        stage_key="diagnostics",
        task_kind="diagnostics",
        strategy_key="engineering_stage",
        strategy_version=1,
        required_capabilities=("structured_output",),
        privacy_class=PrivacyClass.STANDARD,
        locality_requirement=LocalityRequirement.ANY,
        estimated_context_tokens=1000,
        evidence_size_class=EvidenceSizeClass.SMALL,
        recent_progress_signals=(),
        recent_failure_signals=(),
        latency_preference="balanced",
        cost_preference="balanced",
    )
    eligibility = EligibilitySnapshot(
        snapshot_id="eligibility-status-1",
        routing_request_id=request.routing_request_id,
        considered_target_ids=("target-a", "target-b"),
        eligible_target_ids=("target-a", "target-b"),
        exclusions=(),
        target_health_versions={"target-a": 1, "target-b": 1},
        credential_availability={"target-a": True, "target-b": True},
        required_capabilities=request.required_capabilities,
        privacy_class=request.privacy_class,
        locality_requirement=request.locality_requirement,
        policy_version=1,
        policy_digest="a" * 64,
    )
    decision = RoutingDecision(
        decision_id="decision-status-1",
        routing_request_id=request.routing_request_id,
        strategy_key="engineering_stage",
        strategy_version=1,
        strategy_digest="b" * 64,
        ordered_target_ids=("target-a", "target-b"),
        selected_target_id="target-a",
        reason_codes=("diagnostic_complexity",),
        selected_role="capable",
        fallback_budget=1,
        created_at_epoch=100.0,
    )
    routing_store.record_decision(
        request=request,
        eligibility=eligibility,
        decision=decision,
        registry_digest="c" * 64,
    )
    return work_store, routing_store, work, decision


def _attempt(
    *,
    decision: RoutingDecision,
    work_id: str,
    attempt_id: str,
    ordinal: int,
    target_id: str,
    failure_class: str | None,
    latency_ms: float | None,
    usage: dict[str, int | float] | None = None,
    cost: float | None = None,
) -> RoutingAttempt:
    return RoutingAttempt(
        attempt_id=attempt_id,
        decision_id=decision.decision_id,
        work_id=work_id,
        target_id=target_id,
        attempt_ordinal=ordinal,
        started_at_epoch=100.0 + ordinal,
        ended_at_epoch=101.0 + ordinal,
        latency_ms=latency_ms,
        kind=(
            RoutingAttemptKind.PRIMARY if ordinal == 1 else RoutingAttemptKind.FALLBACK
        ),
        failure_class=failure_class,
        usage=usage or {},
        estimated_cost_usd=cost,
        response_contract_result=(
            ResponseContractResult.UNKNOWN
            if failure_class is not None
            else ResponseContractResult.VALID
        ),
        correlation_key=f"corr-{ordinal}",
    )


def test_status_exposes_bounded_route_provenance_and_fallback_path(
    tmp_path: Path,
) -> None:
    _, routing_store, work, decision = _fixture(tmp_path)
    routing_store.record_attempt(
        _attempt(
            decision=decision,
            work_id=work.work_id,
            attempt_id="attempt-status-1",
            ordinal=1,
            target_id="target-a",
            failure_class="rate_limited",
            latency_ms=250.0,
            usage={"input_tokens": 100},
            cost=0.01,
        )
    )
    routing_store.record_attempt(
        _attempt(
            decision=decision,
            work_id=work.work_id,
            attempt_id="attempt-status-2",
            ordinal=2,
            target_id="target-b",
            failure_class=None,
            latency_ms=500.0,
            usage={"input_tokens": 50, "output_tokens": 20},
            cost=0.02,
        )
    )
    routing_store.create_health(
        TargetHealthRecord(
            target_id="target-a",
            state=TargetHealthEligibility.COOLDOWN,
            consecutive_failures=1,
            cooldown_until_epoch=200.0,
            last_failure_kind="rate_limited",
            updated_at_epoch=100.0,
        )
    )

    status = RoutingStatusReader(
        routing_store,
        clock=lambda: 150.0,
    ).for_decision(decision.decision_id)

    assert status is not None
    assert status.work_id == work.work_id
    assert status.change_id == "change-42"
    assert status.stage_key == "diagnostics"
    assert status.selected_target_id == "target-a"
    assert status.reason_codes == ("diagnostic_complexity",)
    assert status.fallback_path == ("target-a", "target-b")
    assert status.final_target_id == "target-b"
    assert status.attempt_count == 2
    assert status.target_health == {
        "target-a": "cooldown",
        "target-b": "unknown",
    }
    assert status.total_latency_ms == 750.0
    assert status.aggregate_usage == {
        "input_tokens": 150.0,
        "output_tokens": 20.0,
    }
    assert status.estimated_total_cost_usd == 0.03
    assert status.verification_status is VerificationStatus.UNKNOWN


def test_missing_usage_cost_and_latency_remain_unknown(tmp_path: Path) -> None:
    _, routing_store, work, decision = _fixture(tmp_path)
    routing_store.record_attempt(
        _attempt(
            decision=decision,
            work_id=work.work_id,
            attempt_id="attempt-status-unknown",
            ordinal=1,
            target_id="target-a",
            failure_class=None,
            latency_ms=None,
        )
    )

    status = RoutingStatusReader(routing_store).for_decision(decision.decision_id)

    assert status is not None
    assert status.total_latency_ms is None
    assert status.aggregate_usage is None
    assert status.estimated_total_cost_usd is None


def test_independent_verification_is_only_reported_from_persisted_outcome(
    tmp_path: Path,
) -> None:
    _, routing_store, work, decision = _fixture(tmp_path)
    routing_store.record_attempt(
        _attempt(
            decision=decision,
            work_id=work.work_id,
            attempt_id="attempt-status-verified",
            ordinal=1,
            target_id="target-a",
            failure_class=None,
            latency_ms=100.0,
            usage={"input_tokens": 10},
            cost=0.001,
        )
    )
    routing_store.record_outcome(
        RoutingOutcome(
            outcome_id="outcome-status-1",
            decision_id=decision.decision_id,
            work_id=work.work_id,
            fallback_path=("target-a",),
            total_attempts=1,
            total_latency_ms=100.0,
            final_target_id="target-a",
            work_step_succeeded=True,
            verifier_reference="verification:change-42",
            accepted_result=True,
            aggregate_usage={"input_tokens": 10},
            estimated_total_cost_usd=0.001,
            outcome_evidence_reference="evidence:change-42",
        )
    )

    status = RoutingStatusReader(routing_store).for_decision(decision.decision_id)

    assert status is not None
    assert status.verification_status is VerificationStatus.ACCEPTED
    assert status.verifier_reference == "verification:change-42"
    assert status.outcome_evidence_reference == "evidence:change-42"


def test_outcome_without_independent_verifier_does_not_claim_verification(
    tmp_path: Path,
) -> None:
    _, routing_store, work, decision = _fixture(tmp_path)
    routing_store.record_outcome(
        RoutingOutcome(
            outcome_id="outcome-status-unverified",
            decision_id=decision.decision_id,
            work_id=work.work_id,
            fallback_path=(),
            total_attempts=0,
            total_latency_ms=0.0,
            work_step_succeeded=True,
            accepted_result=True,
        )
    )

    status = RoutingStatusReader(routing_store).for_decision(decision.decision_id)

    assert status is not None
    assert status.verification_status is VerificationStatus.UNKNOWN
    assert status.verifier_reference is None


def test_latest_for_work_returns_latest_route_without_request_payload(
    tmp_path: Path,
) -> None:
    _, routing_store, work, decision = _fixture(tmp_path)

    status = RoutingStatusReader(routing_store).latest_for_work(work.work_id)

    assert status is not None
    assert status.decision_id == decision.decision_id
    rendered = repr(status)
    assert "Inspect a bounded routing status" not in rendered
    assert "credential" not in rendered.casefold()
