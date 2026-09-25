import pytest

from jarvis.model_routing.models import (
    BenchmarkStatus,
    EvidenceSizeClass,
    LocalityRequirement,
    ModelLocality,
    ModelTarget,
    PrivacyClass,
    RoutingRequest,
)
from jarvis.model_routing.strategy import (
    EngineeringStageStrategy,
    StrategyNoCandidateError,
    derive_work_step_signals,
)
from jarvis.work.models import WorkStep


def _target(
    target_id: str,
    *,
    roles: tuple[str, ...],
) -> ModelTarget:
    return ModelTarget(
        target_id=target_id,
        adapter_id="test",
        provider_id="test",
        model_id=f"model-{target_id}",
        locality=ModelLocality.CLOUD,
        capabilities=("structured_output", "engineering_reasoning"),
        roles=roles,
        max_context_tokens=64_000,
        supports_structured_output=True,
        supports_tools=False,
        supports_streaming=False,
        latency_class="standard",
        benchmark_status=BenchmarkStatus.ACCEPTED,
        registry_version=1,
        credential_ref="config:test",
    )


def _request(
    *,
    task_kind: str = "development",
    progress: tuple[str, ...] = (),
    failures: tuple[str, ...] = (),
    features: dict[str, int | float | bool | str | None] | None = None,
    evidence_size: EvidenceSizeClass = EvidenceSizeClass.SMALL,
    affinity_key: str | None = None,
) -> RoutingRequest:
    return RoutingRequest(
        routing_request_id="route-1",
        work_id="work-1",
        task_kind=task_kind,
        strategy_key="engineering_stage",
        strategy_version=1,
        required_capabilities=("structured_output",),
        privacy_class=PrivacyClass.STANDARD,
        locality_requirement=LocalityRequirement.ANY,
        estimated_context_tokens=4_000,
        evidence_size_class=evidence_size,
        recent_progress_signals=progress,
        recent_failure_signals=failures,
        latency_preference="balanced",
        cost_preference="balanced",
        affinity_key=affinity_key,
        routing_features=features or {},
    )


def _targets() -> tuple[ModelTarget, ...]:
    return (
        _target("capable-a", roles=("capable",)),
        _target("efficient-a", roles=("efficient",)),
        _target("hybrid-a", roles=("efficient", "capable")),
    )


def test_settled_mechanical_work_prefers_efficient_role() -> None:
    result = EngineeringStageStrategy().rank(
        request=_request(progress=("plan_settled",)),
        eligible_targets=_targets(),
    )

    assert result.selected_role == "efficient"
    assert result.ordered_target_ids[:2] == ("efficient-a", "hybrid-a")
    assert result.ordered_target_ids[-1] == "capable-a"


def test_repeated_quality_failures_escalate_to_capable() -> None:
    first = WorkStep(
        work_id="work-1",
        kind="sandbox_test",
        summary="Run tests",
    ).start().fail("controlled failure")
    second = WorkStep(
        work_id="work-1",
        kind="verification_test",
        summary="Verify again",
    ).start().fail("controlled failure")
    signals = derive_work_step_signals((first, second))

    result = EngineeringStageStrategy().rank(
        request=_request(
            failures=signals.failure_signals,
            features=signals.routing_features,
        ),
        eligible_targets=_targets(),
    )

    assert signals.routing_features["quality_failure_count"] == 2
    assert result.selected_role == "capable"
    assert result.ordered_target_ids == ("capable-a", "hybrid-a")
    assert "repeated_quality_failure" in result.reason_codes


def test_provider_pressure_alone_does_not_make_task_harder() -> None:
    pressure = WorkStep(
        work_id="work-1",
        kind="provider_pressure",
        summary="Provider rate limited",
    ).start().complete({"status_code": 429, "attempt": 1})
    signals = derive_work_step_signals((pressure,))

    result = EngineeringStageStrategy().rank(
        request=_request(
            progress=signals.progress_signals,
            failures=signals.failure_signals,
            features=signals.routing_features,
        ),
        eligible_targets=_targets(),
    )

    assert signals.failure_signals == ()
    assert signals.routing_features["provider_pressure_count"] == 1
    assert result.selected_role == "efficient"
    assert "repeated_quality_failure" not in result.reason_codes


def test_provider_pressure_failure_signal_is_ignored_for_difficulty() -> None:
    result = EngineeringStageStrategy().rank(
        request=_request(
            failures=("provider_pressure", "rate_limited"),
        ),
        eligible_targets=_targets(),
    )

    assert result.selected_role == "efficient"


def test_unknown_diagnostic_work_prefers_capable() -> None:
    result = EngineeringStageStrategy().rank(
        request=_request(task_kind="diagnostics"),
        eligible_targets=_targets(),
    )

    assert result.selected_role == "capable"
    assert result.ordered_target_ids == ("capable-a", "hybrid-a")
    assert "unknown_diagnostic" in result.reason_codes


def test_healthy_progress_can_deescalate_diagnostic_work() -> None:
    result = EngineeringStageStrategy().rank(
        request=_request(
            task_kind="diagnostics",
            progress=("healthy_progress",),
        ),
        eligible_targets=_targets(),
    )

    assert result.selected_role == "efficient"
    assert "healthy_progress" in result.reason_codes


def test_large_or_heterogeneous_evidence_prefers_capable() -> None:
    for size in (EvidenceSizeClass.LARGE, EvidenceSizeClass.HETEROGENEOUS):
        result = EngineeringStageStrategy().rank(
            request=_request(evidence_size=size),
            eligible_targets=_targets(),
        )
        assert result.selected_role == "capable"
        assert "evidence_complexity" in result.reason_codes


def test_same_snapshot_produces_same_deterministic_order() -> None:
    strategy = EngineeringStageStrategy()
    request = _request(progress=("plan_settled",))
    targets = tuple(reversed(_targets()))

    first = strategy.rank(request=request, eligible_targets=targets)
    second = strategy.rank(request=request, eligible_targets=targets)

    assert first == second
    assert first.ordered_target_ids == (
        "efficient-a",
        "hybrid-a",
        "capable-a",
    )
    assert len(strategy.strategy_digest) == 64


def test_future_specialist_role_can_be_added_without_schema_change() -> None:
    specialist = _target(
        "specialist-a",
        roles=("specialist", "capable"),
    )
    result = EngineeringStageStrategy().rank(
        request=_request(task_kind="diagnostics"),
        eligible_targets=(*_targets(), specialist),
    )

    assert result.selected_role == "capable"
    assert "specialist-a" in result.ordered_target_ids


def test_affinity_hold_is_bounded_to_a_suitable_candidate() -> None:
    result = EngineeringStageStrategy().rank(
        request=_request(
            progress=("healthy_progress",),
            affinity_key="work-cycle-1",
            features={"affinity_target_id": "hybrid-a"},
        ),
        eligible_targets=_targets(),
    )

    assert result.hold_affinity is True
    assert result.affinity_target_id == "hybrid-a"
    assert result.ordered_target_ids[0] == "hybrid-a"
    assert "affinity_hold" in result.reason_codes


def test_capable_requirement_fails_closed_without_capable_target() -> None:
    with pytest.raises(
        StrategyNoCandidateError,
        match="no capable target",
    ):
        EngineeringStageStrategy().rank(
            request=_request(task_kind="diagnostics"),
            eligible_targets=(
                _target("efficient-only", roles=("efficient",)),
            ),
        )
