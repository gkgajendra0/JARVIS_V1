import pytest

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
from jarvis.model_routing.registry import (
    DuplicateRegistrationError,
    ModelAdapterRegistry,
    ModelTargetRegistry,
    RoutingStrategyRegistry,
    UnknownModelAdapterError,
    UnknownModelTargetError,
    UnknownRoutingStrategyError,
)


class DummyAdapter:
    def __init__(self, adapter_id: str) -> None:
        self.adapter_id = adapter_id

    async def invoke_structured(self, **kwargs: object) -> object:
        return kwargs


class DummyStrategy:
    strategy_key = "engineering_stage"
    strategy_version = 1

    def rank(
        self,
        *,
        request: RoutingRequest,
        eligible_targets: tuple[ModelTarget, ...],
        history: object | None,
    ) -> RoutingStrategyResult:
        del request, history
        return RoutingStrategyResult(
            ordered_target_ids=tuple(target.target_id for target in eligible_targets),
            reason_codes=("deterministic_test",),
            selected_role="efficient",
        )


def _target(
    target_id: str = "cloud.efficient.v1",
    *,
    adapter_id: str = "openai",
    locality: ModelLocality = ModelLocality.CLOUD,
) -> ModelTarget:
    return ModelTarget(
        target_id=target_id,
        adapter_id=adapter_id,
        provider_id=("local" if locality is ModelLocality.LOCAL else "openai"),
        model_id="model-example",
        locality=locality,
        capabilities=(
            "structured_output",
            "engineering_reasoning",
        ),
        roles=("efficient", "capable"),
        max_context_tokens=64_000,
        supports_structured_output=True,
        supports_tools=False,
        supports_streaming=False,
        latency_class="standard",
        benchmark_status=BenchmarkStatus.ACCEPTED,
        registry_version=1,
        credential_ref=(None if locality is ModelLocality.LOCAL else "config:api_key"),
    )


def _request() -> RoutingRequest:
    return RoutingRequest(
        routing_request_id="route-1",
        work_id="work-1",
        task_kind="engineering",
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


def test_model_target_registry_rejects_duplicate_target_identity() -> None:
    adapters = ModelAdapterRegistry((DummyAdapter("openai"),))
    registry = ModelTargetRegistry(adapters)
    registry.register(_target())

    with pytest.raises(
        DuplicateRegistrationError,
        match="already registered",
    ):
        registry.register(_target())


def test_model_target_registry_fails_closed_for_unknown_adapter() -> None:
    registry = ModelTargetRegistry(ModelAdapterRegistry())

    with pytest.raises(
        UnknownModelAdapterError,
        match="unknown model adapter",
    ):
        registry.register(_target(adapter_id="not_registered"))


def test_model_target_registry_fails_closed_for_unknown_target() -> None:
    registry = ModelTargetRegistry(ModelAdapterRegistry((DummyAdapter("openai"),)))

    with pytest.raises(
        UnknownModelTargetError,
        match="unknown model target",
    ):
        registry.require("missing-target")


def test_model_adapter_registry_rejects_duplicate_adapter() -> None:
    registry = ModelAdapterRegistry((DummyAdapter("openai"),))

    with pytest.raises(
        DuplicateRegistrationError,
        match="already registered",
    ):
        registry.register(DummyAdapter("OPENAI"))


def test_future_local_adapter_and_target_register_without_schema_change() -> None:
    adapters = ModelAdapterRegistry(
        (
            DummyAdapter("openai"),
            DummyAdapter("local_native"),
        )
    )
    targets = ModelTargetRegistry(adapters)
    local = _target(
        "local.engineering.v1",
        adapter_id="local_native",
        locality=ModelLocality.LOCAL,
    )
    targets.register(local)

    assert targets.require("LOCAL.ENGINEERING.V1") is local
    assert local in targets.for_role("capable")
    assert local in targets.for_capability("structured_output")


def test_routing_strategy_registry_requires_exact_known_version() -> None:
    strategy = DummyStrategy()
    registry = RoutingStrategyRegistry((strategy,))

    assert (
        registry.require(
            "ENGINEERING_STAGE",
            1,
        )
        is strategy
    )
    with pytest.raises(
        UnknownRoutingStrategyError,
        match="engineering_stage.v2",
    ):
        registry.require(
            "engineering_stage",
            2,
        )


def test_routing_strategy_registry_rejects_duplicate_key_version() -> None:
    registry = RoutingStrategyRegistry((DummyStrategy(),))

    with pytest.raises(
        DuplicateRegistrationError,
        match="already registered",
    ):
        registry.register(DummyStrategy())


def test_registered_strategy_can_order_more_than_two_candidates() -> None:
    adapters = ModelAdapterRegistry(
        (DummyAdapter("openai"),)
    )
    targets = ModelTargetRegistry(
        adapters,
        (
            _target("target-a"),
            _target("target-b"),
            _target("target-c"),
        ),
    )
    strategy = RoutingStrategyRegistry((DummyStrategy(),)).require(
        "engineering_stage",
        1,
    )

    result = strategy.rank(
        request=_request(),
        eligible_targets=targets.all(),
        history=None,
    )

    assert result.ordered_target_ids == (
        "target-a",
        "target-b",
        "target-c",
    )
