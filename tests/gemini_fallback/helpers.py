from jarvis.model_routing.gemini import GeminiFallbackConfig, build_gemini_role_targets
from jarvis.model_routing.models import (
    EvidenceSizeClass,
    LocalityRequirement,
    PrivacyClass,
    RoutingStrategyResult,
)
from jarvis.model_routing.registry import (
    ModelAdapterRegistry,
    ModelTargetRegistry,
    RoutingStrategyRegistry,
)
from jarvis.model_routing.router import ModelRouter
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.work.store import SQLiteWorkStore


class Adapter:
    adapter_id = "gemini"

    async def invoke_structured(self, **kwargs):
        raise AssertionError("No provider invocation expected in routing tests")


class Strategy:
    strategy_key = "test_slots"
    strategy_version = 1
    strategy_digest = "d" * 64

    def rank(self, *, request, eligible_targets, history):
        return RoutingStrategyResult(
            ordered_target_ids=tuple(t.target_id for t in eligible_targets),
            reason_codes=("test_slots",),
            selected_role="efficient",
        )


def make_router(tmp_path, *, model="gemini-test", historical_registries=None):
    adapters = ModelAdapterRegistry((Adapter(),))
    targets = build_gemini_role_targets(
        role="work",
        model=model,
        adapter_id="gemini",
        config=GeminiFallbackConfig(enabled=True),
    )
    registry = ModelTargetRegistry(adapters, targets)
    store = ModelRoutingStore(SQLiteWorkStore(tmp_path / "routing.db"))
    kwargs = (
        {}
        if historical_registries is None
        else {"historical_registries": historical_registries}
    )
    router = ModelRouter(
        target_registry=registry,
        adapter_registry=adapters,
        strategy_registry=RoutingStrategyRegistry((Strategy(),)),
        routing_store=store,
        credential_available=lambda t: True,
        clock=lambda: 100,
        **kwargs,
    )
    return router, store


def scoped_request(**changes):
    from jarvis.model_routing.models import ScopedRoutingRequest

    values = {
        "routing_request_id": "scope-request-1",
        "scope_kind": "memory",
        "scope_id": "source-1",
        "task_kind": "memory",
        "strategy_key": "test_slots",
        "strategy_version": 1,
        "required_capabilities": ("structured_output",),
        "privacy_class": PrivacyClass.STANDARD,
        "locality_requirement": LocalityRequirement.ANY,
        "estimated_context_tokens": 100,
        "evidence_size_class": EvidenceSizeClass.SMALL,
        "recent_progress_signals": (),
        "recent_failure_signals": (),
        "latency_preference": "balanced",
        "cost_preference": "low",
    }
    values.update(changes)
    return ScopedRoutingRequest(**values)
