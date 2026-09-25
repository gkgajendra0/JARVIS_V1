import pytest

from jarvis.model_routing.eligibility import (
    EligibilityPolicy,
    EligibilityReason,
    EligibilityRuntimeState,
    EligibleTargets,
    IneligibleStrategyTargetError,
    NoEligibleTargets,
    TargetHealthEligibility,
)
from jarvis.model_routing.models import (
    BenchmarkStatus,
    EvidenceSizeClass,
    LocalityRequirement,
    ModelLocality,
    ModelTarget,
    PrivacyClass,
    RoutingRequest,
    RoutingStrategyResult,
)
from jarvis.model_routing.registry import ModelAdapterRegistry


class DummyAdapter:
    def __init__(self, adapter_id: str) -> None:
        self.adapter_id = adapter_id

    async def invoke_structured(self, **kwargs: object) -> object:
        return kwargs


def _target(
    target_id: str,
    *,
    adapter_id: str = "openai",
    locality: ModelLocality = ModelLocality.CLOUD,
    capabilities: tuple[str, ...] = (
        "structured_output",
        "engineering_reasoning",
    ),
    roles: tuple[str, ...] = ("efficient", "capable"),
    max_context_tokens: int = 64_000,
    structured_output: bool = True,
    credential_ref: str | None = "config:api_key",
    benchmark_status: BenchmarkStatus = BenchmarkStatus.ACCEPTED,
    enabled: bool = True,
) -> ModelTarget:
    return ModelTarget(
        target_id=target_id,
        adapter_id=adapter_id,
        provider_id="local" if locality is ModelLocality.LOCAL else "openai",
        model_id=f"model-{target_id}",
        locality=locality,
        capabilities=capabilities,
        roles=roles,
        max_context_tokens=max_context_tokens,
        supports_structured_output=structured_output,
        supports_tools=False,
        supports_streaming=False,
        latency_class="standard",
        benchmark_status=benchmark_status,
        registry_version=1,
        credential_ref=credential_ref,
        enabled=enabled,
    )


def _request(
    *,
    privacy_class: PrivacyClass = PrivacyClass.STANDARD,
    locality_requirement: LocalityRequirement = LocalityRequirement.ANY,
    required_capabilities: tuple[str, ...] = ("structured_output",),
    estimated_context_tokens: int = 4_000,
    required_role: str | None = None,
) -> RoutingRequest:
    features = {} if required_role is None else {"required_role": required_role}
    return RoutingRequest(
        routing_request_id="route-1",
        work_id="work-1",
        task_kind="engineering",
        strategy_key="engineering_stage",
        strategy_version=1,
        required_capabilities=required_capabilities,
        privacy_class=privacy_class,
        locality_requirement=locality_requirement,
        estimated_context_tokens=estimated_context_tokens,
        evidence_size_class=EvidenceSizeClass.SMALL,
        recent_progress_signals=(),
        recent_failure_signals=(),
        latency_preference="balanced",
        cost_preference="balanced",
        routing_features=features,
    )


def _adapters(*adapter_ids: str) -> ModelAdapterRegistry:
    return ModelAdapterRegistry(
        tuple(DummyAdapter(adapter_id) for adapter_id in adapter_ids)
    )


def _runtime(
    *,
    credentials: dict[str, bool] | None = None,
    health: dict[str, TargetHealthEligibility] | None = None,
    versions: dict[str, int] | None = None,
) -> EligibilityRuntimeState:
    return EligibilityRuntimeState(
        credential_availability=credentials or {},
        target_health=health or {},
        target_health_versions=versions or {},
    )


def _reasons(result: EligibleTargets | NoEligibleTargets, target_id: str) -> set[str]:
    for exclusion in result.snapshot.exclusions:
        if exclusion.target_id == target_id:
            return set(exclusion.reason_codes)
    return set()


def test_local_only_privacy_and_locality_never_select_cloud() -> None:
    local = _target(
        "local",
        adapter_id="local_native",
        locality=ModelLocality.LOCAL,
        credential_ref=None,
    )
    cloud = _target("cloud")
    result = EligibilityPolicy().evaluate(
        request=_request(
            privacy_class=PrivacyClass.LOCAL_ONLY,
            locality_requirement=LocalityRequirement.LOCAL_ONLY,
        ),
        targets=(cloud, local),
        adapter_registry=_adapters("openai", "local_native"),
        runtime_state=_runtime(credentials={"cloud": True}),
        snapshot_id="eligibility-1",
    )

    assert isinstance(result, EligibleTargets)
    assert tuple(target.target_id for target in result.targets) == ("local",)
    assert EligibilityReason.LOCALITY_MISMATCH.value in _reasons(result, "cloud")
    assert EligibilityReason.PRIVACY_MISMATCH.value in _reasons(result, "cloud")


def test_missing_capability_excludes_target() -> None:
    target = _target("limited", capabilities=("structured_output",))
    result = EligibilityPolicy().evaluate(
        request=_request(
            required_capabilities=(
                "structured_output",
                "engineering_reasoning",
            )
        ),
        targets=(target,),
        adapter_registry=_adapters("openai"),
        runtime_state=_runtime(credentials={"limited": True}),
        snapshot_id="eligibility-2",
    )

    assert isinstance(result, NoEligibleTargets)
    assert EligibilityReason.CAPABILITY_MISSING.value in _reasons(result, "limited")


def test_missing_credential_excludes_without_persisting_reference_value() -> None:
    target = _target("cloud")
    result = EligibilityPolicy().evaluate(
        request=_request(),
        targets=(target,),
        adapter_registry=_adapters("openai"),
        runtime_state=_runtime(credentials={"cloud": False}),
        snapshot_id="eligibility-3",
    )

    assert isinstance(result, NoEligibleTargets)
    assert result.snapshot.credential_availability == {"cloud": False}
    assert EligibilityReason.CREDENTIAL_UNAVAILABLE.value in _reasons(result, "cloud")
    assert target.credential_ref not in repr(result.snapshot)


def test_context_overflow_excludes_target() -> None:
    target = _target("small-context", max_context_tokens=8_000)
    result = EligibilityPolicy().evaluate(
        request=_request(estimated_context_tokens=8_001),
        targets=(target,),
        adapter_registry=_adapters("openai"),
        runtime_state=_runtime(credentials={"small-context": True}),
        snapshot_id="eligibility-4",
    )

    assert isinstance(result, NoEligibleTargets)
    assert EligibilityReason.CONTEXT_TOO_SMALL.value in _reasons(
        result,
        "small-context",
    )


def test_structured_output_flag_is_a_hard_capability_floor() -> None:
    target = _target("lying-target", structured_output=False)
    result = EligibilityPolicy().evaluate(
        request=_request(),
        targets=(target,),
        adapter_registry=_adapters("openai"),
        runtime_state=_runtime(credentials={"lying-target": True}),
        snapshot_id="eligibility-5",
    )

    assert isinstance(result, NoEligibleTargets)
    assert EligibilityReason.STRUCTURED_OUTPUT_UNSUPPORTED.value in _reasons(
        result,
        "lying-target",
    )


@pytest.mark.parametrize(
    ("target", "expected_reason"),
    [
        (
            _target("disabled", enabled=False),
            EligibilityReason.TARGET_DISABLED,
        ),
        (
            _target(
                "unverified",
                benchmark_status=BenchmarkStatus.UNVERIFIED,
            ),
            EligibilityReason.BENCHMARK_NOT_ACCEPTED,
        ),
        (
            _target("missing-adapter", adapter_id="missing"),
            EligibilityReason.ADAPTER_UNAVAILABLE,
        ),
    ],
)
def test_static_target_guards_fail_closed(
    target: ModelTarget,
    expected_reason: EligibilityReason,
) -> None:
    result = EligibilityPolicy().evaluate(
        request=_request(),
        targets=(target,),
        adapter_registry=_adapters("openai"),
        runtime_state=_runtime(credentials={target.target_id: True}),
        snapshot_id=f"eligibility-{target.target_id}",
    )

    assert isinstance(result, NoEligibleTargets)
    assert expected_reason.value in _reasons(result, target.target_id)


@pytest.mark.parametrize(
    ("health", "expected_reason"),
    [
        (
            TargetHealthEligibility.COOLDOWN,
            EligibilityReason.TARGET_COOLDOWN,
        ),
        (
            TargetHealthEligibility.UNAVAILABLE,
            EligibilityReason.TARGET_UNHEALTHY,
        ),
        (
            TargetHealthEligibility.DISABLED,
            EligibilityReason.TARGET_UNHEALTHY,
        ),
    ],
)
def test_unavailable_health_states_exclude_target(
    health: TargetHealthEligibility,
    expected_reason: EligibilityReason,
) -> None:
    target = _target("health-target")
    result = EligibilityPolicy().evaluate(
        request=_request(),
        targets=(target,),
        adapter_registry=_adapters("openai"),
        runtime_state=_runtime(
            credentials={"health-target": True},
            health={"health-target": health},
            versions={"health-target": 7},
        ),
        snapshot_id="eligibility-health",
    )

    assert isinstance(result, NoEligibleTargets)
    assert expected_reason.value in _reasons(result, "health-target")
    assert result.snapshot.target_health_versions == {"health-target": 7}


def test_unknown_and_degraded_health_remain_eligible() -> None:
    unknown = _target("unknown")
    degraded = _target("degraded")
    result = EligibilityPolicy().evaluate(
        request=_request(),
        targets=(unknown, degraded),
        adapter_registry=_adapters("openai"),
        runtime_state=_runtime(
            credentials={"unknown": True, "degraded": True},
            health={"degraded": TargetHealthEligibility.DEGRADED},
        ),
        snapshot_id="eligibility-health-available",
    )

    assert isinstance(result, EligibleTargets)
    assert result.snapshot.eligible_target_ids == ("unknown", "degraded")


def test_required_role_is_a_hard_filter_when_explicitly_requested() -> None:
    efficient = _target("efficient", roles=("efficient",))
    capable = _target("capable", roles=("capable",))
    result = EligibilityPolicy().evaluate(
        request=_request(required_role="capable"),
        targets=(efficient, capable),
        adapter_registry=_adapters("openai"),
        runtime_state=_runtime(
            credentials={"efficient": True, "capable": True},
        ),
        snapshot_id="eligibility-role",
    )

    assert isinstance(result, EligibleTargets)
    assert result.snapshot.eligible_target_ids == ("capable",)
    assert EligibilityReason.ROLE_MISMATCH.value in _reasons(result, "efficient")


def test_all_excluded_returns_typed_no_route_without_relaxing_constraints() -> None:
    result = EligibilityPolicy().evaluate(
        request=_request(
            privacy_class=PrivacyClass.LOCAL_ONLY,
            locality_requirement=LocalityRequirement.LOCAL_ONLY,
        ),
        targets=(_target("cloud"),),
        adapter_registry=_adapters("openai"),
        runtime_state=_runtime(credentials={"cloud": True}),
        snapshot_id="eligibility-none",
    )

    assert isinstance(result, NoEligibleTargets)
    assert result.reason_code == "no_eligible_target"
    assert result.snapshot.eligible_target_ids == ()


def test_strategy_cannot_reintroduce_excluded_target() -> None:
    local = _target(
        "local",
        adapter_id="local_native",
        locality=ModelLocality.LOCAL,
        credential_ref=None,
    )
    cloud = _target("cloud")
    policy = EligibilityPolicy()
    eligibility = policy.evaluate(
        request=_request(
            privacy_class=PrivacyClass.LOCAL_ONLY,
            locality_requirement=LocalityRequirement.LOCAL_ONLY,
        ),
        targets=(local, cloud),
        adapter_registry=_adapters("local_native", "openai"),
        runtime_state=_runtime(credentials={"cloud": True}),
        snapshot_id="eligibility-strategy",
    )
    strategy_result = RoutingStrategyResult(
        ordered_target_ids=("local", "cloud"),
        reason_codes=("test",),
        selected_role="capable",
    )

    with pytest.raises(IneligibleStrategyTargetError, match="cloud"):
        policy.validate_strategy_result(
            eligibility=eligibility,
            strategy_result=strategy_result,
        )


def test_policy_digest_is_deterministic_and_reason_safe() -> None:
    first = EligibilityPolicy()
    second = EligibilityPolicy()

    assert first.policy_version == 1
    assert first.policy_digest == second.policy_digest
    assert len(first.policy_digest) == 64
