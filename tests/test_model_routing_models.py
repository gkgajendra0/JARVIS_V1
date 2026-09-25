from dataclasses import FrozenInstanceError, fields

import pytest

from jarvis.model_routing.models import (
    BenchmarkStatus,
    CostProfile,
    EligibilitySnapshot,
    EvidenceSizeClass,
    LocalityRequirement,
    ModelLocality,
    ModelTarget,
    PrivacyClass,
    ResponseContractResult,
    RoutingAttempt,
    RoutingAttemptKind,
    RoutingDecision,
    RoutingOutcome,
    RoutingRequest,
    RoutingStrategyResult,
    TargetExclusion,
)


def _target(**overrides: object) -> ModelTarget:
    values: dict[str, object] = {
        "target_id": "cloud.capable.v1",
        "adapter_id": "openai",
        "provider_id": "openai",
        "model_id": "gpt-example",
        "locality": ModelLocality.CLOUD,
        "capabilities": (
            "structured_output",
            "engineering_reasoning",
        ),
        "roles": ("capable",),
        "max_context_tokens": 128_000,
        "supports_structured_output": True,
        "supports_tools": True,
        "supports_streaming": False,
        "latency_class": "standard",
        "benchmark_status": BenchmarkStatus.ACCEPTED,
        "registry_version": 1,
        "credential_ref": "config:openai_api_key",
    }
    values.update(overrides)
    return ModelTarget(**values)


def test_model_target_has_stable_immutable_identity() -> None:
    target = _target(target_id="Work.Capable.Primary")
    assert target.target_id == "work.capable.primary"
    assert target.stable_identity == "work.capable.primary"

    with pytest.raises(FrozenInstanceError):
        target.target_id = "changed"  # type: ignore[misc]


def test_model_target_schema_rejects_invalid_contracts() -> None:
    with pytest.raises(ValueError, match="capability"):
        _target(capabilities=())
    with pytest.raises(ValueError, match="role"):
        _target(roles=())
    with pytest.raises(ValueError, match="max_context_tokens"):
        _target(max_context_tokens=0)
    with pytest.raises(TypeError, match="locality"):
        _target(locality="cloud")


def test_model_target_exposes_reference_not_plaintext_credential_fields() -> None:
    names = {item.name for item in fields(ModelTarget)}
    assert "credential_ref" in names
    assert {
        "credential",
        "credential_value",
        "api_key",
        "secret",
        "password",
        "token",
    }.isdisjoint(names)


def test_future_local_target_fits_same_provider_neutral_schema() -> None:
    target = _target(
        target_id="local.qwen.engineering.v1",
        adapter_id="local_native",
        provider_id="local",
        model_id="qwen-local",
        locality=ModelLocality.LOCAL,
        credential_ref=None,
        endpoint_ref="runtime:local_gpu",
        roles=("efficient", "capable"),
    )

    assert target.locality is ModelLocality.LOCAL
    assert target.credential_ref is None
    assert target.roles == ("efficient", "capable")


def test_cost_profile_is_versioned_and_effective_dated() -> None:
    profile = CostProfile(
        profile_id="openai-work-2026-09",
        version=3,
        effective_from_epoch=100.0,
        effective_to_epoch=200.0,
        input_usd_per_million_tokens=1.25,
        output_usd_per_million_tokens=5.0,
    )
    assert profile.version == 3

    with pytest.raises(ValueError, match="cannot precede"):
        CostProfile(
            profile_id="bad",
            version=1,
            effective_from_epoch=200.0,
            effective_to_epoch=100.0,
        )


def test_routing_request_is_bounded_and_normalized() -> None:
    request = RoutingRequest(
        routing_request_id="route-1",
        work_id="work-1",
        task_kind="Diagnostics",
        strategy_key="Engineering_Stage",
        strategy_version=1,
        required_capabilities=(
            "Structured_Output",
            "structured_output",
        ),
        privacy_class=PrivacyClass.PRIVATE,
        locality_requirement=LocalityRequirement.PRIVATE_OR_LOCAL,
        estimated_context_tokens=12_000,
        evidence_size_class=EvidenceSizeClass.MEDIUM,
        recent_progress_signals=("Plan_Settled",),
        recent_failure_signals=(),
        latency_preference="Balanced",
        cost_preference="Balanced",
        stage_key="diagnostics",
        routing_features={
            "failed_hypotheses": 1,
            "uncertainty": 0.4,
        },
    )

    assert request.strategy_key == "engineering_stage"
    assert request.required_capabilities == ("structured_output",)
    assert request.routing_features["failed_hypotheses"] == 1

    with pytest.raises(ValueError, match="routing_features exceed"):
        RoutingRequest(
            routing_request_id="route-too-wide",
            work_id="work-1",
            task_kind="diagnostics",
            strategy_key="engineering_stage",
            strategy_version=1,
            required_capabilities=(),
            privacy_class=PrivacyClass.STANDARD,
            locality_requirement=LocalityRequirement.ANY,
            estimated_context_tokens=0,
            evidence_size_class=EvidenceSizeClass.SMALL,
            recent_progress_signals=(),
            recent_failure_signals=(),
            latency_preference="balanced",
            cost_preference="balanced",
            routing_features={f"f{i}": i for i in range(33)},
        )


def test_eligibility_snapshot_partitions_considered_targets() -> None:
    snapshot = EligibilitySnapshot(
        snapshot_id="eligibility-1",
        routing_request_id="route-1",
        considered_target_ids=("t1", "t2", "t3"),
        eligible_target_ids=("t1", "t3"),
        exclusions=(
            TargetExclusion(
                target_id="t2",
                reason_codes=("target_cooldown",),
            ),
        ),
        target_health_versions={
            "t1": 1,
            "t2": 3,
            "t3": 1,
        },
        credential_availability={
            "t1": True,
            "t2": True,
            "t3": False,
        },
        required_capabilities=("structured_output",),
        privacy_class=PrivacyClass.STANDARD,
        locality_requirement=LocalityRequirement.ANY,
        policy_version=1,
        policy_digest="a" * 64,
    )

    assert snapshot.eligible_target_ids == ("t1", "t3")
    assert snapshot.exclusions[0].reason_codes == ("target_cooldown",)

    with pytest.raises(ValueError, match="eligible or excluded"):
        EligibilitySnapshot(
            snapshot_id="eligibility-bad",
            routing_request_id="route-1",
            considered_target_ids=("t1", "t2"),
            eligible_target_ids=("t1",),
            exclusions=(),
            target_health_versions={},
            credential_availability={},
            required_capabilities=(),
            privacy_class=PrivacyClass.STANDARD,
            locality_requirement=LocalityRequirement.ANY,
            policy_version=1,
            policy_digest="b" * 64,
        )


def test_strategy_result_orders_more_than_two_candidates() -> None:
    result = RoutingStrategyResult(
        ordered_target_ids=(
            "efficient-a",
            "efficient-b",
            "capable-c",
        ),
        reason_codes=("routine_progress",),
        selected_role="efficient",
    )

    assert result.ordered_target_ids == (
        "efficient-a",
        "efficient-b",
        "capable-c",
    )


def test_routing_decision_requires_selected_target_in_ordered_candidates() -> None:
    decision = RoutingDecision(
        decision_id="decision-1",
        routing_request_id="route-1",
        strategy_key="engineering_stage",
        strategy_version=1,
        strategy_digest="c" * 64,
        ordered_target_ids=("target-a", "target-b"),
        selected_target_id="target-a",
        reason_codes=("routine_progress",),
        selected_role="efficient",
        fallback_budget=1,
        created_at_epoch=123.0,
    )
    assert decision.selected_target_id == "target-a"

    with pytest.raises(
        ValueError,
        match="must be in ordered_target_ids",
    ):
        RoutingDecision(
            decision_id="decision-bad",
            routing_request_id="route-1",
            strategy_key="engineering_stage",
            strategy_version=1,
            strategy_digest="d" * 64,
            ordered_target_ids=("target-a",),
            selected_target_id="target-b",
            reason_codes=(),
            selected_role="efficient",
            fallback_budget=0,
            created_at_epoch=123.0,
        )


def test_routing_attempt_and_outcome_validate_operational_provenance() -> None:
    attempt = RoutingAttempt(
        attempt_id="attempt-1",
        decision_id="decision-1",
        work_id="work-1",
        target_id="target-a",
        attempt_ordinal=1,
        started_at_epoch=100.0,
        ended_at_epoch=101.0,
        latency_ms=1000.0,
        kind=RoutingAttemptKind.PRIMARY,
        usage={
            "input_tokens": 100,
            "output_tokens": 20,
        },
        estimated_cost_usd=0.01,
        response_contract_result=ResponseContractResult.VALID,
    )
    assert attempt.attempt_ordinal == 1
    assert attempt.usage["input_tokens"] == 100.0

    outcome = RoutingOutcome(
        outcome_id="outcome-1",
        decision_id="decision-1",
        work_id="work-1",
        fallback_path=("target-a", "target-b"),
        final_target_id="target-b",
        total_attempts=2,
        total_latency_ms=1800.0,
        work_step_succeeded=True,
        verifier_reference="verification:step-9",
    )
    assert outcome.final_target_id == "target-b"

    with pytest.raises(ValueError, match="last fallback_path"):
        RoutingOutcome(
            outcome_id="outcome-bad",
            decision_id="decision-1",
            work_id="work-1",
            fallback_path=("target-a", "target-b"),
            final_target_id="target-a",
            total_attempts=2,
            total_latency_ms=1800.0,
        )
