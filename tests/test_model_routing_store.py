from pathlib import Path

import pytest

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
    RoutingRequest,
)
from jarvis.model_routing.store import ModelRoutingStore, RoutingStoreError
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.privacy import build_protected_work_payload_codec
from jarvis.work.store import SQLiteWorkStore


class FakeKeyProtector:
    protector_id = "fake-test-protector"

    def seal(self, plaintext: bytes, *, purpose: str) -> bytes:
        return purpose.encode("utf-8") + b"|" + plaintext

    def unseal(self, sealed: bytes, *, purpose: str) -> bytes:
        prefix = purpose.encode("utf-8") + b"|"
        assert sealed.startswith(prefix)
        return sealed[len(prefix) :]


def _raw_storage(path: Path) -> bytes:
    chunks = []
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists():
            chunks.append(candidate.read_bytes())
    return b"".join(chunks)


def _work(store: SQLiteWorkStore, *, suffix: str = "1") -> WorkItem:
    item = WorkItem(
        request=f"route work {suffix}",
        work_type=WorkType.DIAGNOSTICS,
        source_session_id="session-routing",
        source_turn_id=f"turn-{suffix}",
    )
    store.create(item)
    return item


def _request(work: WorkItem, *, suffix: str = "1") -> RoutingRequest:
    return RoutingRequest(
        routing_request_id=f"routing-request-{suffix}",
        work_id=work.work_id,
        task_kind="diagnostics",
        strategy_key="engineering_stage",
        strategy_version=1,
        required_capabilities=("structured_output",),
        privacy_class=PrivacyClass.STANDARD,
        locality_requirement=LocalityRequirement.ANY,
        estimated_context_tokens=4_000,
        evidence_size_class=EvidenceSizeClass.SMALL,
        recent_progress_signals=(),
        recent_failure_signals=(),
        latency_preference="balanced",
        cost_preference="balanced",
    )


def _eligibility(request: RoutingRequest) -> EligibilitySnapshot:
    return EligibilitySnapshot(
        snapshot_id=f"eligibility-{request.routing_request_id}",
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


def _decision(request: RoutingRequest, *, suffix: str = "1") -> RoutingDecision:
    return RoutingDecision(
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


def _attempt(
    work: WorkItem,
    decision: RoutingDecision,
    *,
    attempt_id: str = "attempt-1",
    ordinal: int = 1,
    target_id: str = "target-a",
    failure_class: str | None = None,
    correlation_key: str | None = None,
) -> RoutingAttempt:
    return RoutingAttempt(
        attempt_id=attempt_id,
        decision_id=decision.decision_id,
        work_id=work.work_id,
        target_id=target_id,
        attempt_ordinal=ordinal,
        started_at_epoch=101.0,
        ended_at_epoch=102.0,
        latency_ms=1000.0,
        kind=(
            RoutingAttemptKind.PRIMARY
            if ordinal == 1
            else RoutingAttemptKind.FALLBACK
        ),
        failure_class=failure_class,
        usage={"input_tokens": 100, "output_tokens": 20},
        estimated_cost_usd=0.01,
        response_contract_result=ResponseContractResult.VALID,
        correlation_key=correlation_key,
    )


def test_routing_decision_and_attempt_round_trip_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite"
    work_store = SQLiteWorkStore(path)
    work = _work(work_store)
    request = _request(work)
    eligibility = _eligibility(request)
    decision = _decision(request)
    routing_store = ModelRoutingStore(work_store)

    routing_store.record_decision(
        request=request,
        eligibility=eligibility,
        decision=decision,
        registry_digest="c" * 64,
    )
    routing_store.record_attempt(_attempt(work, decision))

    reopened = ModelRoutingStore(SQLiteWorkStore(path))
    persisted = reopened.get_decision(decision.decision_id)
    assert persisted is not None
    assert persisted.work_id == work.work_id
    assert persisted.registry_digest == "c" * 64
    assert persisted.decision.strategy_digest == "b" * 64
    assert persisted.eligibility.policy_digest == "a" * 64
    assert persisted.decision.ordered_target_ids == ("target-a", "target-b")

    attempts = reopened.list_attempts(decision.decision_id)
    assert len(attempts) == 1
    assert attempts[0].target_id == "target-a"
    assert attempts[0].usage["input_tokens"] == 100.0


def test_routing_records_are_append_only(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite"
    work_store = SQLiteWorkStore(path)
    work = _work(work_store)
    request = _request(work)
    eligibility = _eligibility(request)
    decision = _decision(request)
    routing_store = ModelRoutingStore(work_store)

    routing_store.record_decision(
        request=request,
        eligibility=eligibility,
        decision=decision,
        registry_digest="c" * 64,
    )

    with pytest.raises(RoutingStoreError, match="cannot be created"):
        routing_store.record_decision(
            request=request,
            eligibility=eligibility,
            decision=decision,
            registry_digest="c" * 64,
        )


def test_decision_and_attempt_transaction_rolls_back_on_attempt_failure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "work.sqlite"
    work_store = SQLiteWorkStore(path)
    routing_store = ModelRoutingStore(work_store)

    first_work = _work(work_store, suffix="first")
    first_request = _request(first_work, suffix="first")
    first_decision = _decision(first_request, suffix="first")
    routing_store.record_decision_and_attempt(
        request=first_request,
        eligibility=_eligibility(first_request),
        decision=first_decision,
        registry_digest="c" * 64,
        attempt=_attempt(
            first_work,
            first_decision,
            attempt_id="shared-attempt-id",
        ),
    )

    second_work = _work(work_store, suffix="second")
    second_request = _request(second_work, suffix="second")
    second_decision = _decision(second_request, suffix="second")
    with pytest.raises(RoutingStoreError, match="could not be committed"):
        routing_store.record_decision_and_attempt(
            request=second_request,
            eligibility=_eligibility(second_request),
            decision=second_decision,
            registry_digest="d" * 64,
            attempt=_attempt(
                second_work,
                second_decision,
                attempt_id="shared-attempt-id",
            ),
        )

    assert routing_store.get_decision(second_decision.decision_id) is None
    assert routing_store.find_decision_by_request(
        second_request.routing_request_id
    ) is None


def test_target_health_cas_rejects_stale_concurrent_update(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite"
    routing_store = ModelRoutingStore(SQLiteWorkStore(path))
    original = TargetHealthRecord(
        target_id="target-a",
        state=TargetHealthEligibility.HEALTHY,
        updated_at_epoch=100.0,
        version=1,
    )
    routing_store.create_health(original)

    first = TargetHealthRecord(
        target_id="target-a",
        state=TargetHealthEligibility.DEGRADED,
        consecutive_failures=1,
        last_failure_kind="timeout",
        updated_at_epoch=101.0,
        version=2,
    )
    second = TargetHealthRecord(
        target_id="target-a",
        state=TargetHealthEligibility.COOLDOWN,
        consecutive_failures=1,
        cooldown_until_epoch=130.0,
        last_failure_kind="rate_limited",
        updated_at_epoch=102.0,
        version=2,
    )

    routing_store.save_health(first, expected_version=1)
    with pytest.raises(RoutingStoreError, match="stale target health"):
        routing_store.save_health(second, expected_version=1)

    stored = routing_store.get_health("target-a")
    assert stored == first


def test_target_health_round_trips_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite"
    routing_store = ModelRoutingStore(SQLiteWorkStore(path))
    record = TargetHealthRecord(
        target_id="target-a",
        state=TargetHealthEligibility.COOLDOWN,
        consecutive_failures=2,
        cooldown_until_epoch=150.0,
        last_failure_kind="rate_limited",
        updated_at_epoch=120.0,
        version=3,
    )
    routing_store.create_health(record)

    reopened = ModelRoutingStore(SQLiteWorkStore(path))
    assert reopened.get_health("target-a") == record


def test_protected_work_codec_also_protects_routing_payloads(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite"
    codec = build_protected_work_payload_codec(
        path,
        key_protector=FakeKeyProtector(),
        random_bytes=lambda size: b"r" * size,
    )
    work_store = SQLiteWorkStore(path, payload_codec=codec)
    work = _work(work_store)
    request = _request(work)
    decision = _decision(request)
    routing_store = ModelRoutingStore(work_store)
    marker = "ROUTING_PRIVATE_MARKER_9017"

    routing_store.record_decision_and_attempt(
        request=request,
        eligibility=_eligibility(request),
        decision=decision,
        registry_digest="c" * 64,
        attempt=_attempt(
            work,
            decision,
            failure_class=marker,
            correlation_key=marker,
        ),
    )

    assert marker.encode("utf-8") not in _raw_storage(path)
    stored_attempt = routing_store.list_attempts(decision.decision_id)[0]
    assert stored_attempt.failure_class == marker
    assert stored_attempt.correlation_key == marker


def test_attempt_must_stay_inside_decision_candidate_order(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite"
    work_store = SQLiteWorkStore(path)
    work = _work(work_store)
    request = _request(work)
    decision = _decision(request)
    routing_store = ModelRoutingStore(work_store)
    routing_store.record_decision(
        request=request,
        eligibility=_eligibility(request),
        decision=decision,
        registry_digest="c" * 64,
    )

    with pytest.raises(RoutingStoreError, match="outside decision order"):
        routing_store.record_attempt(
            _attempt(
                work,
                decision,
                target_id="not-approved",
            )
        )
