import json
from pathlib import Path

import pytest

from jarvis.model_routing.acceptance import inspect_routing_acceptance
from jarvis.model_routing.models import (
    EligibilitySnapshot,
    EvidenceSizeClass,
    LocalityRequirement,
    PrivacyClass,
    ResponseContractResult,
    RoutingAttempt,
    RoutingAttemptKind,
    RoutingDecision,
    RoutingRequest,
)
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.store import SQLiteWorkStore


def _work(store: SQLiteWorkStore, *, turn: str = "turn-1") -> WorkItem:
    item = WorkItem(
        request="PRIVATE_ACCEPTANCE_PROMPT_4812",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="session-acceptance",
        source_turn_id=turn,
    )
    store.create(item)
    return item


def _route(
    routing: ModelRoutingStore,
    work: WorkItem,
    *,
    suffix: str = "1",
) -> RoutingDecision:
    request = RoutingRequest(
        routing_request_id=f"route-{suffix}",
        work_id=work.work_id,
        change_id=f"change-{suffix}",
        stage_key="development",
        task_kind="development",
        strategy_key="engineering_stage",
        strategy_version=1,
        required_capabilities=("engineering_reasoning", "structured_output"),
        privacy_class=PrivacyClass.STANDARD,
        locality_requirement=LocalityRequirement.ANY,
        estimated_context_tokens=1200,
        evidence_size_class=EvidenceSizeClass.SMALL,
        recent_progress_signals=("plan_settled",),
        recent_failure_signals=(),
        latency_preference="balanced",
        cost_preference="balanced",
    )
    eligibility = EligibilitySnapshot(
        snapshot_id=f"eligibility-{suffix}",
        routing_request_id=request.routing_request_id,
        considered_target_ids=("target-a", "target-b"),
        eligible_target_ids=("target-a", "target-b"),
        exclusions=(),
        target_health_versions={},
        credential_availability={"target-a": True, "target-b": True},
        required_capabilities=request.required_capabilities,
        privacy_class=request.privacy_class,
        locality_requirement=request.locality_requirement,
        policy_version=1,
        policy_digest="a" * 64,
    )
    decision = RoutingDecision(
        decision_id=f"decision-{suffix}",
        routing_request_id=request.routing_request_id,
        strategy_key="engineering_stage",
        strategy_version=1,
        strategy_digest="b" * 64,
        ordered_target_ids=("target-a", "target-b"),
        selected_target_id="target-a",
        reason_codes=("routine_progress",),
        selected_role="efficient",
        fallback_budget=1,
        created_at_epoch=100.0,
    )
    routing.record_decision(
        request=request,
        eligibility=eligibility,
        decision=decision,
        registry_digest="c" * 64,
    )
    return decision


def test_acceptance_inspector_reports_bounded_route_lineage(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    work = _work(store)
    routing = ModelRoutingStore(store)
    decision = _route(routing, work)
    routing.record_attempt(
        RoutingAttempt(
            attempt_id="attempt-1",
            decision_id=decision.decision_id,
            work_id=work.work_id,
            target_id="target-a",
            attempt_ordinal=1,
            started_at_epoch=101.0,
            ended_at_epoch=102.0,
            latency_ms=1000.0,
            kind=RoutingAttemptKind.PRIMARY,
            failure_class=None,
            usage={"input_tokens": 100, "output_tokens": 20},
            estimated_cost_usd=0.01,
            response_contract_result=ResponseContractResult.VALID,
            correlation_key="PRIVATE_CORRELATION_9917",
        )
    )

    result = inspect_routing_acceptance(store, work.work_id)

    assert result["result"] == "PENDING"
    assert result["work_id"] == work.work_id
    assert result["decision_id"] == decision.decision_id
    assert result["change_id"] == "change-1"
    assert result["strategy"] == "engineering_stage.v1"
    assert result["fallback_path"] == ["target-a"]
    assert result["attempt_count"] == 1
    assert set(result["store_gates"].values()) == {"PASS"}
    assert set(result["external_gates"].values()) == {"PENDING"}

    encoded = json.dumps(result, sort_keys=True)
    assert "PRIVATE_ACCEPTANCE_PROMPT_4812" not in encoded
    assert "PRIVATE_CORRELATION_9917" not in encoded


def test_acceptance_inspector_fails_closed_without_route_decision(
    tmp_path: Path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    work = _work(store)

    result = inspect_routing_acceptance(store, work.work_id)

    assert result["result"] == "FAIL"
    assert result["store_gates"]["routing_decision_present"] == "FAIL"


def test_acceptance_inspector_rejects_decision_for_another_work(
    tmp_path: Path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    first = _work(store, turn="first")
    second = _work(store, turn="second")
    routing = ModelRoutingStore(store)
    decision = _route(routing, first)

    with pytest.raises(ValueError, match="does not belong"):
        inspect_routing_acceptance(
            store,
            second.work_id,
            decision_id=decision.decision_id,
        )


def test_acceptance_inspector_rejects_attempts_beyond_fallback_bound(
    tmp_path: Path,
) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    work = _work(store)
    routing = ModelRoutingStore(store)
    decision = _route(routing, work)

    for ordinal in range(1, 5):
        routing.record_attempt(
            RoutingAttempt(
                attempt_id=f"attempt-{ordinal}",
                decision_id=decision.decision_id,
                work_id=work.work_id,
                target_id="target-a",
                attempt_ordinal=ordinal,
                started_at_epoch=100.0 + ordinal,
                ended_at_epoch=101.0 + ordinal,
                latency_ms=1000.0,
                kind=RoutingAttemptKind.PRIMARY,
                response_contract_result=ResponseContractResult.VALID,
            )
        )

    result = inspect_routing_acceptance(store, work.work_id)

    assert result["result"] == "FAIL"
    assert result["store_gates"]["bounded_attempt_lineage"] == "FAIL"
